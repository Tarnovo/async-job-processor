import time
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient

import json
from app.worker.employee_processor import process_csv
import io
from app.core.database import get_db_connection
import os


# Standard practice to load environment variables from a .env file, especially for sensitive information like database credentials.
load_dotenv()

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
if S3_BUCKET_NAME is None:
    raise ValueError("S3_BUCKET_NAME environment variable is not set. Please set it in your .env file or environment.")

SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
if SQS_QUEUE_URL is None:
    raise ValueError("SQS_QUEUE_URL environment variable is not set. Please set it in your .env file or environment.")

s3_client: S3Client = boto3.client('s3')
sqs_client: SQSClient = boto3.client('sqs')


# We start an infinite loop so that the worker can listen continuously.
while True:
    try:
        messages = sqs_client.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20 # Long polling to reduce empty responses and costs, as the worker will wait up to 20 seconds for a message to arrive before returning.
        )   
    
    except ClientError as e:
        print(f"Error receiving message from SQS: {e}")
        time.sleep(5)  # Wait 5 seconds before retrying to prevent a startup race condition.
        continue       # Without this delay, worker.py would crash immediately if LocalStack hasn't created the queue yet.
   
    messages = messages.get('Messages', [])

    if not messages:
        continue

    
    # We retrieve the required values ​​from the incoming list.
    for message in messages:
        body = json.loads(message['Body'])
        job_id = body['job_id']
        s3_key = body['s3_key']
        receipt_handle = message['ReceiptHandle']
        
        print(f"Processing... {job_id} S3 key: {s3_key}")

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE jobs SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE job_id = %s",
                ('PROCESSING', job_id)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as db_err:
            print(f"Failed to set status to PROCESSING for {job_id}: {db_err}")

        try:
            # We retrieve the CSV file from S3 using the provided key. 
            s3_response = s3_client.get_object(
                Bucket=S3_BUCKET_NAME, 
                Key=s3_key
            )

            # We read the raw bytes from the S3 response and wrap them in a BytesIO object, which allows us to treat the bytes as a file-like object. This is necessary because the process_csv function expects a file-like object as input.
            raw_bytes = s3_response['Body'].read()
            csv_file_obj = io.BytesIO(raw_bytes)
            result = process_csv(csv_file_obj)

            # We convert the summary of the CSV processing result into a dictionary format, which is suitable for storage in the database. This summary includes counts of valid rows, underage rows, and invalid rows, providing a concise overview of the CSV processing outcome.
            summary_dict = result.summary.model_dump()

            # We save the invalid rows to S3 and update the job status in the database.
            full_dict = result.model_dump()
            invalid_rows_list = full_dict["invalid_rows"]
            invalid_s3_key = f"results/{job_id}_invalid_rows.json"
            
            s3_put = s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=invalid_s3_key,
                Body=json.dumps(invalid_rows_list).encode('utf-8')
            )
            print(f"Invalid rows saved to S3: {job_id}_invalid_rows.json")

            # We connect to the PostgreSQL database using credentials from environment variables. This connection allows us to execute SQL commands to update the job status and store the processing results.
            conn = get_db_connection()
            cur = conn.cursor()
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
            conn.commit()
            cur.close()
            conn.close()

            print(f"Job completed successfully!: {job_id} Summary: {summary_dict}")

            # We delete the message from the SQS queue after successfully processing the job.
            # This part might not work correctly in practice, so it will be changed.
            sqs_client.delete_message(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=receipt_handle
            )
            print(f"Message deleted from SQS: {job_id}")    
        
        except Exception as e:
            print(f"Job processing failed for {job_id}: {e}")

            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE jobs SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE job_id = %s",
                    ('FAILED', job_id)
                )
                conn.commit()
                cur.close()
                conn.close()
                print(f"Job status updated to FAILED for: {job_id}")

            except Exception as db_fail_err:
                print(f"Critical: Failed to update job status to FAILED in DB: {db_fail_err}")

        
        



