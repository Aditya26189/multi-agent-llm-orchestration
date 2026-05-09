from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)


class QueryResponse(BaseModel):
    job_id: str
    message: str = "Job submitted. Connect to SSE stream for real-time updates."


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    job_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# All valid error codes — used across all 5 endpoints
ERROR_CODES = {
    "INJECTION_DETECTED":       "Query rejected: prompt injection pattern detected.",
    "INVALID_QUERY":            "Query must be a non-empty string (max 4000 chars).",
    "JOB_NOT_FOUND":            "No job exists with the specified ID.",
    "EVAL_NOT_READY":           "No evaluation runs have completed yet.",
    "REWRITE_NOT_FOUND":        "No prompt rewrite exists with the specified ID.",
    "REWRITE_ALREADY_REVIEWED": "This rewrite has already been approved or rejected.",
    "PIPELINE_ERROR":           "Pipeline failed during execution.",
    "INTERNAL_ERROR":           "An unexpected internal error occurred.",
}


class ReviewRequest(BaseModel):
    approved: bool
    reviewer_note: Optional[str] = None
