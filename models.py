from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class CSVSummary(BaseModel):
    valid: int
    underage: int
    invalid_value: int

class InvalidRow(BaseModel):
    row_number: int
    reason: str

class CSVProcessingResponse(BaseModel):
    summary: CSVSummary
    invalid_rows: list[InvalidRow]

class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    message: str

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    result_summary: Optional[CSVSummary] = None
    presigned_url: Optional[str] = None
    updated_at: Optional[datetime] = None
    