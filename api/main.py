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
    detail = exc.detail if isinstance(exc.detail, dict) else {
        "code": "UNKNOWN_ERROR", "message": str(exc.detail)
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=detail.get("code", "UNKNOWN_ERROR"),
            message=detail.get("message", str(exc.detail)),
            job_id=detail.get("job_id"),
        ).model_dump(mode="json"),
    )


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
