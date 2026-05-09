import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from api.routes.schemas import ReviewRequest
from db.models import PromptVersion
from eval.harness import EvaluationHarness

router = APIRouter()


@router.post(
    "/rewrites/{rewrite_id}/review",
    summary="Approve or reject a pending prompt rewrite proposal",
)
async def review_rewrite(
    rewrite_id: str,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        text("SELECT * FROM prompt_rewrites WHERE rewrite_id = :rid"),
        {"rid": rewrite_id},
    )
    rewrite = row.mappings().first()

    if not rewrite:
        raise HTTPException(status_code=404, detail={
            "error_code": "REWRITE_NOT_FOUND",
            "message": f"No prompt rewrite with ID: {rewrite_id}",
        })

    if rewrite["status"] != "pending":
        raise HTTPException(status_code=409, detail={
            "error_code": "REWRITE_ALREADY_REVIEWED",
            "message": f"Rewrite {rewrite_id} already has status: {rewrite['status']}",
        })

    new_status = "approved" if body.approved else "rejected"

    await db.execute(
        text("""
            UPDATE prompt_rewrites
            SET status = :s, reviewed_at = :t, reviewer_note = :n
            WHERE rewrite_id = :rid
        """),
        {
            "s": new_status,
            "t": datetime.utcnow(),
            "n": body.reviewer_note,
            "rid": rewrite_id,
        },
    )

    if body.approved:
        new_version = PromptVersion(
            agent_id=rewrite["agent_id"],
            prompt_text=rewrite["proposed_prompt"],
            is_active=True,
        )
        db.add(new_version)
        await db.flush()
        await db.execute(
            update(PromptVersion)
            .where(PromptVersion.agent_id == rewrite["agent_id"])
            .where(PromptVersion.version_id != new_version.version_id)
            .values(is_active=False)
        )

        failed_cases_raw = rewrite.get("failure_cases")
        if isinstance(failed_cases_raw, str):
            failed_cases = json.loads(failed_cases_raw or "[]")
        elif isinstance(failed_cases_raw, list):
            failed_cases = failed_cases_raw
        else:
            failed_cases = []
        if failed_cases:
            asyncio.create_task(
                run_targeted_eval_and_update_delta(
                    failed_cases=failed_cases,
                    rewrite_id=rewrite_id,
                    session=db,
                )
            )

    await db.commit()

    return {
        "rewrite_id": rewrite_id,
        "new_status": new_status,
        "message": f"Rewrite {'approved' if body.approved else 'rejected'}. "
                   + ("Run POST /eval/run to test the improved prompt." if body.approved else ""),
    }


async def run_targeted_eval_and_update_delta(
    failed_cases: list,
    rewrite_id: str,
    session: AsyncSession,
) -> None:
    harness = EvaluationHarness()
    result = await harness.run_all(failed_case_ids=failed_cases)
    results = result.get("results", [])
    new_score = (
        sum(r.get("composite_score", 0.0) for r in results) / len(results)
        if results else 0.0
    )

    prior_run = await session.execute(
        text("SELECT run_id FROM eval_runs ORDER BY triggered_at DESC LIMIT 1")
    )
    run_row = prior_run.mappings().first()
    old_score = 0.0
    if run_row:
        old_rows = await session.execute(
            text("""
                SELECT composite_score FROM eval_results
                WHERE run_id = :rid AND test_case_id = ANY(:ids)
            """),
            {"rid": str(run_row["run_id"]), "ids": failed_cases},
        )
        old_scores = [r["composite_score"] or 0.0 for r in old_rows.mappings().all()]
        if old_scores:
            old_score = sum(old_scores) / len(old_scores)

    delta = new_score - old_score
    await session.execute(
        text("""
            UPDATE prompt_rewrites
            SET delta_score = :delta
            WHERE rewrite_id = :rid
        """),
        {"delta": delta, "rid": rewrite_id},
    )
    await session.commit()
