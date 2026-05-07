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


ERROR_CODES = {
    "JOB_NOT_FOUND":            "No job with the specified ID exists.",
    "EVAL_NOT_READY":           "No evaluation runs completed yet.",
    "REWRITE_ALREADY_REVIEWED": "This rewrite has already been reviewed.",
    "REWRITE_NOT_FOUND":        "No rewrite with this ID exists.",
    "INVALID_QUERY":            "Query must be a non-empty string.",
    "BUDGET_EXCEEDED":          "Agent exceeded context token budget.",
    "TOOL_ALL_RETRIES_FAILED":  "Tool failed after maximum retry attempts.",
    "INJECTION_DETECTED":       "Query rejected due to prompt injection pattern.",
}


class ReviewRequest(BaseModel):
    approved: bool
    reviewer_note: Optional[str] = None
