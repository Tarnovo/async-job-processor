import os
import io
import time
import json
from typing import TYPE_CHECKING
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

from app.core.database import get_db_cursor
from app.worker.employee_processor import process_csv

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient

# Standard practice to load environment variables from a .env file
load_dotenv()

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
if S3_BUCKET_NAME is None:
    raise ValueError("S3_BUCKET_NAME environment variable is not set. Please set it in your .env file or environment.")

SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
if SQS_QUEUE_URL is None:
    raise ValueError("SQS_QUEUE_URL environment variable is not set. Please set it in your .env file or environment.")

s3_client: S3Client = boto3.client('s3')
sqs_client: SQSClient = boto3.client('sqs')

# Persistent worker loop listening for queue events
while True:
    try:
        # Long-polling reduces empty responses, API call count, and overall AWS infrastructure cost
        messages = sqs_client.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20
        )   
    except ClientError as e:
        # Throttles polling and absorbs startup race conditions if endpoints/queues are initializing
        print(f"Error receiving message from SQS: {e}")
        time.sleep(5)
        continue
   
    messages = messages.get('Messages', [])

    if not messages:
        continue

    for message in messages:
        body = json.loads(message['Body'])
        job_id = body['job_id']
        s3_key = body['s3_key']
        receipt_handle = message['ReceiptHandle']
        
        print(f"Processing... {job_id} S3 key: {s3_key}")

        # IDEMPOTENCY GUARD & STATE TRANSITION:
        # Standard SQS guarantees At-Least-Once delivery. If a message is redelivered after
        # a previous successful run, verify state to prevent duplicate processing.
        try:
            with get_db_cursor() as cur:
                cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
                
                # If job was already marked COMPLETED by a previous worker attempt, acknowledge and skip
                if row and row[0] == 'COMPLETED':
                    print(f"Job {job_id} is already COMPLETED. Acknowledging message to prevent duplicate execution.")
                    sqs_client.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
                    continue

                # Transition state to PROCESSING to indicate active compute
                cur.execute(
                    "UPDATE jobs SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE job_id = %s",
                    ('PROCESSING', job_id)
                )
        except Exception as db_err:
            print(f"Failed during initial state check/transition for {job_id}: {db_err}")
            # If the database is unreachable, do not proceed with compute.
            # Skip acknowledgment and allow SQS visibility timeout to handle redelivery.
            continue

        try:
            # 1. Retrieve the raw CSV stream from S3 using the provided reference key
            s3_response = s3_client.get_object(
                Bucket=S3_BUCKET_NAME, 
                Key=s3_key
            )

            # 2. Convert payload to in-memory file-like buffer and execute domain validation logic
            raw_bytes = s3_response['Body'].read()
            csv_file_obj = io.BytesIO(raw_bytes)
            result = process_csv(csv_file_obj)

            summary_dict = result.summary.model_dump()
            full_dict = result.model_dump()
            invalid_rows_list = full_dict["invalid_rows"]
            invalid_s3_key = f"results/{job_id}_invalid_rows.json"
            
            # 3. Persist the isolated invalid rows report back to S3
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=invalid_s3_key,
                Body=json.dumps(invalid_rows_list).encode('utf-8')
            )
            print(f"Invalid rows saved to S3: {invalid_s3_key}")

            # 4. Atomically persist execution metrics and transition job state to COMPLETED
            with get_db_cursor() as cur:      
                cur.execute(
                    """
                    UPDATE jobs 
                    SET status = %s, 
                        result_summary = %s,
                        invalid_rows_s3_key = %s,  
                        updated_at = CURRENT_TIMESTAMP                   
                    WHERE job_id = %s
                    """,
                    ('COMPLETED', json.dumps(summary_dict), invalid_s3_key, job_id)
                )

            print(f"Job completed successfully!: {job_id} Summary: {summary_dict}")

            # 5. Explicitly acknowledge and delete message from SQS upon verified completion
            sqs_client.delete_message(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=receipt_handle
            )
            print(f"Message deleted from SQS: {job_id}")    
        
        except Exception as e:
            # Catch transient/permanent compute errors and mark job state as FAILED in DB
            print(f"Job processing failed for {job_id}: {e}")

            try:
                with get_db_cursor() as cur:
                    cur.execute(
                        "UPDATE jobs SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE job_id = %s",
                        ('FAILED', job_id)
                    )
            except Exception as db_fail_err:
                print(f"Critical: Failed to update job status to FAILED in DB: {db_fail_err}")