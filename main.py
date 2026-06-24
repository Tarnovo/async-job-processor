import database # This is a temporary solution. A different approach should be chosen for production.
import os
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile
import uuid
import boto3
from mypy_boto3_s3 import S3Client
from mypy_boto3_sqs import SQSClient
import json
from models import (
    JobCreatedResponse,
    JobStatusResponse
)

load_dotenv()  # Load environment variables from a .env file if present

# Initialize the FastAPI application instance
app = FastAPI()

# Define the target S3 bucket name for raw CSV files
BUCKET_NAME = "csv-upload-bucket"

AWS_ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
QUEUE_URL = os.getenv("SQS_QUEUE_URL", "http://localstack:4566/000000000000/job-processing-queue")

# Initialize the S3 client using boto3.
s3_client: S3Client = boto3.client(
    's3',
    endpoint_url=AWS_ENDPOINT,
    aws_access_key_id='test',
    aws_secret_access_key='test',
    region_name='us-east-1'
)

# Initialize the SQS client using boto3.
sqs_client: SQSClient = boto3.client(
    'sqs',
    endpoint_url=AWS_ENDPOINT,
    aws_access_key_id='test',
    aws_secret_access_key='test',
    region_name='us-east-1'
)

# Standard health check endpoint.
# Crucial for AWS ALB and ECS to determine if the container is healthy.

@app.get("/health")
def health_check():
    return {"status": "ok"}


# Endpoint to receive CSV files, upload them to S3, and trigger an async job via SQS.
# Implements the Producer side of the Async Request-Reply pattern.

@app.post("/upload", response_model=JobCreatedResponse)
async def upload_csv(file: UploadFile):
    new_job_id = str(uuid.uuid4())
    s3_file_key = f"{new_job_id}.csv"
    
    import psycopg2
    from fastapi import HTTPException
    
    # We connect to the PostgreSQL database using credentials from environment variables. This connection allows us to execute SQL commands to insert a new job record with a "PENDING" status.
    try:
        connection = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            database=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            port=os.getenv("POSTGRES_PORT", "5432")
        )
        cur = connection.cursor()
        cur.execute(
            "INSERT INTO jobs (job_id, status) VALUES (%s, %s)",
            (new_job_id, "PENDING")
        )
        connection.commit()
        cur.close()
        connection.close()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    
    # Using 'upload_fileobj' is memory-efficient because it streams the file chunks 
    # instead of loading the entire large CSV into RAM.
    s3_client.upload_fileobj(file.file, BUCKET_NAME, s3_file_key)


    # We pass only the S3 reference not the file content itself, bypassing SQS size limits (256 KB) and saving queue costs.
    sqs_client.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({"job_id": new_job_id, "s3_key": s3_file_key})
    )

    
    return JobCreatedResponse(
        job_id=new_job_id, 
        status="PENDING", 
        message="The file has been added to the queue for processing."
    )

# Endpoint to check the status of a job by its ID.
@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    import psycopg2
    from fastapi import HTTPException
    try:
        connection = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        port=os.getenv("POSTGRES_PORT", "5432")
        )
        cur = connection.cursor()
        cur.execute(
            "SELECT status, result_summary, invalid_rows_s3_key, updated_at FROM jobs WHERE job_id = %s",
            (job_id,)
        )
        job = cur.fetchone() # Fetch the first row of the result set, which contains the job status information.
        cur.close()
        connection.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Unpack the job status information from the database query result.
    status, result_summary, invalid_rows_s3_key, updated_at = job

    # If the job is completed, we return the full details including the result summary and presigned URL for invalid rows.
    if status == "COMPLETED":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job processed successfully.",
            result_summary=result_summary,
            presigned_url=f"http://localhost:4566/csv-upload-bucket/{invalid_rows_s3_key}" if invalid_rows_s3_key else None,
            updated_at=updated_at
        )
    
    # For jobs that are still pending or in progress, we return a message indicating that the job is not yet completed, without the result summary or presigned URL.
    return JobStatusResponse(
        job_id=job_id,
        status=status,
        message="Job is still in progress. Please check again later.",
        result_summary=None,
        presigned_url=None,
        updated_at=None
    )