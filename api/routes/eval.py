import asyncio
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from eval.harness import EvaluationHarness

router = APIRouter()


@router.get(
    "/eval/latest",
    summary="Get latest eval run summary by test category and scoring dimension",
)
async def get_latest_eval(db: AsyncSession = Depends(get_db)):
    run = await db.execute(
        text("SELECT * FROM eval_runs ORDER BY triggered_at DESC LIMIT 1")
    )
    run_row = run.mappings().first()
    if not run_row:
        raise HTTPException(status_code=404, detail={
            "error_code": "EVAL_NOT_READY",
            "message": "No evaluation runs have completed yet. Run POST /eval/run first.",
        })

    results = await db.execute(
        text("""
            SELECT test_case_id, category,
                   answer_correctness, citation_accuracy, contradiction_resolution,
                   tool_efficiency, budget_compliance, critique_agreement,
                   composite_score, justifications
            FROM eval_results
            WHERE run_id = :rid
            ORDER BY test_case_id
        """),
        {"rid": str(run_row["run_id"])},
    )

    rows = [dict(r) for r in results.mappings().all()]

    # Category breakdown
    categories: dict = {"BASELINE": [], "AMBIGUOUS": [], "ADVERSARIAL": []}
    for r in rows:
        cat = r.get("category", "BASELINE")
        categories.get(cat, categories["BASELINE"]).append(r)

    category_summary = {}
    for cat, cat_rows in categories.items():
        if cat_rows:
            category_summary[cat] = {
                "count": len(cat_rows),
                "avg_composite": sum(r["composite_score"] or 0 for r in cat_rows) / len(cat_rows),
            }

    return {
        "run_id": str(run_row["run_id"]),
        "triggered_at": run_row["triggered_at"],
        "total_score": run_row["total_score"],
        "category_breakdown": category_summary,
        "results": rows,
    }


@router.post(
    "/eval/run",
    summary="Trigger re-eval on previously failed cases using latest approved prompts",
)
async def run_eval(db: AsyncSession = Depends(get_db)):
    harness = EvaluationHarness()
    asyncio.create_task(harness.run_all())
    return {"message": "Evaluation started in background."}
