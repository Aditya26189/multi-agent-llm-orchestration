import os
import uuid
from fastapi import APIRouter, Request, HTTPException
from api.routes.schemas import QueryRequest
from eval.adversarial import detect_injection
from worker.tasks import run_agent_pipeline

# SAFE SSE IMPORT — tries fastapi.sse first, falls back to sse-starlette
try:
    from fastapi.sse import EventSourceResponse
except ImportError:
    from sse_starlette.sse import EventSourceResponse

from core.streaming import sse_event_generator

router = APIRouter()
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


@router.post(
    "/query",
    summary="Submit query and receive real-time SSE stream",
    response_description="Server-Sent Events stream with agent activity",
)
async def submit_query(request: Request, body: QueryRequest):
    """
    Submit a query to the multi-agent pipeline.

    Events emitted: TOKEN, AGENT_START, TOOL_CALL_START, TOOL_CALL_END,
                    BUDGET_UPDATE, HANDOFF, COMPRESSION_TRIGGERED, done, error
    """
    # Injection detection BEFORE routing to orchestrator
    injection = detect_injection(body.query)
    if injection.is_injection:
        raise HTTPException(status_code=400, detail={
            "code": "INJECTION_DETECTED",
            "message": f"Query rejected: detected pattern '{injection.detected_pattern}'",
        })

    job_id = str(uuid.uuid4())

    # Submit to Celery
    run_agent_pipeline.apply_async(
        args=[body.query, job_id],
        task_id=job_id,
        queue="heavy_tasks",
    )

    async def event_gen():
        async for event in sse_event_generator(job_id, REDIS_URL, request):
            yield event

    # ping=15 handles keepalive
    return EventSourceResponse(event_gen(), ping=15)
