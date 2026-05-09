from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db

router = APIRouter()


@router.get(
    "/jobs/{job_id}/trace",
    summary="Get full execution trace for a completed job",
)
async def get_trace(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Returns the complete execution trace: all agent decisions, tool calls,
    and handoffs in chronological order for the given job_id.
    """
    job_row = await db.execute(
        text("SELECT job_id, query, status, created_at FROM jobs WHERE job_id = :jid"),
        {"jid": job_id},
    )
    job = job_row.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail={
            "error_code": "JOB_NOT_FOUND",
            "message": f"No job exists with ID: {job_id}",
            "job_id": job_id,
        })

    events = await db.execute(
        text("""
            SELECT seq, agent_id, event_type, input_hash, output_hash,
                   latency_ms, token_count, policy_violation, timestamp
            FROM execution_events
            WHERE job_id = :jid
            ORDER BY seq ASC
        """),
        {"jid": job_id},
    )

    tool_calls = await db.execute(
        text("""
            SELECT tool_name, agent_id, attempt_number, input_json, output_json,
                   latency_ms, accepted, error_code, retry_reason, timestamp
            FROM tool_calls
            WHERE job_id = :jid
            ORDER BY timestamp ASC
        """),
        {"jid": job_id},
    )

    return {
        "job": dict(job),
        "execution_trace": [dict(r) for r in events.mappings().all()],
        "tool_calls": [dict(r) for r in tool_calls.mappings().all()],
    }
