from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from api.routes.schemas import ReviewRequest

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
            "code": "REWRITE_NOT_FOUND",
            "message": f"No rewrite with ID {rewrite_id}",
        })

    if rewrite["status"] != "PENDING":
        raise HTTPException(status_code=409, detail={
            "code": "REWRITE_ALREADY_REVIEWED",
            "message": f"Rewrite already has status: {rewrite['status']}",
        })

    new_status = "APPROVED" if body.approved else "REJECTED"

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
    await db.commit()

    return {
        "rewrite_id": rewrite_id,
        "new_status": new_status,
        "message": f"Rewrite {'approved' if body.approved else 'rejected'}. "
                   + ("Run POST /eval/run to test the improved prompt." if body.approved else ""),
    }
