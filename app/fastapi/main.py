from app.core.database import get_db_connection, init_db
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid
import boto3
from botocore.config import Config 
from mypy_boto3_s3 import S3Client
from mypy_boto3_sqs import SQSClient
import json
from app.core.models import (
    JobCreatedResponse,
    JobStatusResponse
)

load_dotenv()  # Load environment variables from a .env file if present

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

# Initialize the FastAPI application instance
app = FastAPI(title="Async Job Platform API", lifespan=lifespan)

# Allow Cross-Origin Resource Sharing for Frontend
FRONTEND_DOMAIN = os.getenv("FRONTEND_DOMAIN")
if not FRONTEND_DOMAIN:
    raise RuntimeError("CRITICAL: 'FRONTEND_DOMAIN' environment variable is not defined.")

allowed_origins = [FRONTEND_DOMAIN]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"]
)

# Define the target S3 bucket name for raw CSV files
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
if S3_BUCKET_NAME is None:
    raise ValueError("S3_BUCKET_NAME environment variable is not set. Please set it in your .env file or environment.")

# Define the SQS queue URL for job processing.
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
if SQS_QUEUE_URL is None:
    raise ValueError("SQS_QUEUE_URL environment variable is not set. Please set it in your .env file or environment.")

# Initialize the S3 client using boto3.
s3_config = Config(
    region_name=os.getenv("AWS_DEFAULT_REGION", "eu-central-1"),
    signature_version='s3v4',
    s3={
        'addressing_style': 'virtual'
    }
)

s3_client: S3Client = boto3.client('s3', config=s3_config)

# Initialize the SQS client using boto3.
sqs_client: SQSClient = boto3.client('sqs')


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
    
    # We connect to the PostgreSQL database using credentials from environment variables. This connection allows us to execute SQL commands to insert a new job record with a "PENDING" status.
    try:
        if not file.filename or not file.filename.endswith(".csv"):
            raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

        # Using 'upload_fileobj' is memory-efficient because it streams the file chunks 
        # instead of loading the entire large CSV into RAM.
        s3_client.upload_fileobj(file.file, S3_BUCKET_NAME, s3_file_key)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO jobs (job_id, status) VALUES (%s, %s)",
            (new_job_id, "PENDING")
        )
        conn.commit()
        cur.close()
        conn.close()

        # We pass only the S3 reference not the file content itself, bypassing SQS size limits (1024 KiB) and saving queue costs.   
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps({"job_id": new_job_id, "s3_key": s3_file_key})
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process upload request: {str(e)}"
        )
    
    
    return JobCreatedResponse(
        job_id=new_job_id, 
        status="PENDING", 
        message="The file has been added to the queue for processing."
    )

# Endpoint to check the status of a job by its ID.
@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT status, result_summary, invalid_rows_s3_key, updated_at FROM jobs WHERE job_id = %s",
            (job_id,)
        )
        job = cur.fetchone()
        cur.close()
        conn.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Unpack the job status information from the database query result.
    status, result_summary, invalid_rows_s3_key, updated_at = job

    presigned_url = None
    if invalid_rows_s3_key:
        try:
            # Generate a presigned URL for the invalid rows file in S3, allowing temporary access to the file without requiring AWS credentials.
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET_NAME, 'Key': invalid_rows_s3_key},
                ExpiresIn=900  # URL expires in 15 minutes
            )
        except Exception as e:
            presigned_url = None


    # If the job is completed, we return the full details including the result summary and presigned URL for invalid rows.
    if status == "COMPLETED":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job processed successfully.",
            result_summary=result_summary,
            presigned_url=presigned_url,
            updated_at=updated_at
        )

    # If the job is failed...
    if status == "FAILED":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job processing failed. Please check the logs or upload again.",
            result_summary=None,
            presigned_url=None,
            updated_at=updated_at
        )

    # If the job hasn't been picked up by the worker yet (waiting in the SQS queue)
    if status == "PENDING":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job is pending in the queue. Processing has not started yet.",
            result_summary=None,
            presigned_url=None,
            updated_at=updated_at
        )

    # If the job was picked up by the worker and is actively being processed
    if status == "PROCESSING":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job is currently being processed by the worker.",
            result_summary=None,
            presigned_url=None,
            updated_at=updated_at
        )