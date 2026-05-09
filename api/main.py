import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from api.routes import query, trace, eval as eval_router, rewrites
from api.routes.schemas import ErrorResponse
from core.logging_config import configure_logging

configure_logging()

app = FastAPI(
    title="MEGA-AI",
    description="Production Multi-Agent LLM Orchestration System",
    version="1.0.0",
)

# Register routes — EXACTLY 5 endpoints (plus /health for ops)
app.include_router(query.router, tags=["pipeline"])
app.include_router(trace.router, tags=["observability"])
app.include_router(eval_router.router, tags=["evaluation"])
app.include_router(rewrites.router, tags=["self-improvement"])


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Support both dict detail (structured) and string detail
    if isinstance(exc.detail, dict):
        error_code = exc.detail.get("error_code", "INTERNAL_ERROR")
        message = exc.detail.get("message", str(exc.detail))
        job_id = exc.detail.get("job_id", None)
    else:
        error_code = "INTERNAL_ERROR"
        message = str(exc.detail)
        job_id = None

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=error_code,
            message=message,
            job_id=job_id,
        ).model_dump(mode="json"),
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="INTERNAL_ERROR",
            message=f"Unexpected error: {type(exc).__name__}",
        ).model_dump(mode="json"),
    )


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
