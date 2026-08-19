import os
import uuid
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import boto3
from botocore.config import Config

from app.core.database import get_db_cursor, init_db
from app.core.models import (
    JobCreatedResponse,
    JobStatusResponse
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient

# Standard practice to load environment variables from a .env file
load_dotenv()

# The lifespan context manager executes initialization routines before accepting ingress traffic
# and teardown logic upon container shutdown. Running init_db() ensures DDL assertions succeed 
# prior to handling HTTP requests, preventing startup race conditions.
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

# Initialize the FastAPI application instance with the lifecycle handler
app = FastAPI(title="Async Job Platform API", lifespan=lifespan)

# Allow Cross-Origin Resource Sharing (CORS) for the decoupled frontend origin
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

# Target S3 bucket name for raw CSV file ingestion
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
if S3_BUCKET_NAME is None:
    raise ValueError("S3_BUCKET_NAME environment variable is not set. Please set it in your .env file or environment.")

# Target SQS queue URL for asynchronous job messaging
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
if SQS_QUEUE_URL is None:
    raise ValueError("SQS_QUEUE_URL environment variable is not set. Please set it in your .env file or environment.")

# Explicit S3 client configuration enforcing SigV4 and virtual-hosted bucket addressing
s3_config = Config(
    region_name=os.getenv("AWS_DEFAULT_REGION", "eu-central-1"),
    signature_version='s3v4',
    s3={
        'addressing_style': 'virtual'
    }
)

s3_client: S3Client = boto3.client('s3', config=s3_config)
sqs_client: SQSClient = boto3.client('sqs')


# Standard health check endpoint required by AWS ALB target groups
@app.get("/health")
def health_check():
    return {"status": "ok"}


# Ingestion endpoint receiving raw CSV files, streaming to S3, and dispatching an SQS job event.
# Implements the Producer role within the asynchronous decoupled processing topology.
@app.post("/upload", response_model=JobCreatedResponse)
async def upload_csv(file: UploadFile):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    new_job_id = str(uuid.uuid4())
    s3_file_key = f"{new_job_id}.csv"
    
    try:
        # Stream file directly to S3 without buffering entire payload into container memory
        s3_client.upload_fileobj(file.file, S3_BUCKET_NAME, s3_file_key)

        # Utilize the managed context manager to persist initial PENDING state.
        # Guarantees automatic commit/rollback and prevents PostgreSQL connection leakage.
        with get_db_cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (job_id, status) VALUES (%s, %s)",
                (new_job_id, "PENDING")
            )

        # Pass only the S3 reference metadata to SQS, bypassing payload size limits (1 MiB)
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


# Polling endpoint querying execution state and returning time-limited presigned URLs upon completion
@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    try:
        # Query current job record within a safe connection context
        with get_db_cursor() as cur:
            cur.execute(
                "SELECT status, result_summary, invalid_rows_s3_key, updated_at FROM jobs WHERE job_id = %s",
                (job_id,)
            )
            job = cur.fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    status, result_summary, invalid_rows_s3_key, updated_at = job

    presigned_url = None
    if invalid_rows_s3_key:
        try:
            # Generate a secure, time-limited presigned URL allowing the client direct read access to S3
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET_NAME, 'Key': invalid_rows_s3_key},
                ExpiresIn=900  # Token valid for 15 minutes
            )
        except Exception:
            presigned_url = None

    if status == "COMPLETED":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job processed successfully.",
            result_summary=result_summary,
            presigned_url=presigned_url,
            updated_at=updated_at
        )

    if status == "FAILED":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job processing failed. Please check the logs or upload again.",
            result_summary=None,
            presigned_url=None,
            updated_at=updated_at
        )

    if status == "PENDING":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job is pending in the queue. Processing has not started yet.",
            result_summary=None,
            presigned_url=None,
            updated_at=updated_at
        )

    if status == "PROCESSING":
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            message="Job is currently being processed by the worker.",
            result_summary=None,
            presigned_url=None,
            updated_at=updated_at
        )