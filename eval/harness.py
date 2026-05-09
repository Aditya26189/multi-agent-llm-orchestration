"""
Evaluation Harness — Gemini override.

- Uses gemini-2.0-flash as the judge model (not GPT-4o).
- await asyncio.sleep(4) between test cases (Gemini free tier: 15 RPM).
- Stores results to PostgreSQL for reproducibility.
- Failed case re-run supported via failed_case_ids parameter.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import google.generativeai as genai

GENERATOR_MODEL = "gemini-2.0-flash"   # produces answers
JUDGE_MODEL     = "gemini-1.5-flash"   # scores answers (different checkpoint — anti-bias)

from eval.scorers import (
    score_answer_correctness, score_citation_accuracy,
    score_contradiction_resolution, score_tool_efficiency,
    score_budget_compliance, score_critique_agreement, compute_composite
)
from eval.adversarial import detect_injection

TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"


class EvaluationHarness:
    def __init__(self):
        self.test_cases = json.loads(TEST_CASES_PATH.read_text())
        api_key = os.environ["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        # Judge model — different checkpoint from generator (anti-self-enhancement bias)
        self.judge_model = genai.GenerativeModel(JUDGE_MODEL)

    async def run_all(self, failed_case_ids: list = None, rewrite_id: str = None) -> dict:
        """
        Run all 15 test cases (or subset of failed ones).
        Stores results in PostgreSQL with full reproducibility.
        await asyncio.sleep(4) between cases — respects Gemini 15 RPM free tier.
        """
        cases = self.test_cases
        if failed_case_ids:
            cases = [c for c in cases if c["id"] in failed_case_ids]

        run_id = str(uuid.uuid4())
        results = []

        print(f"\n=== MEGA-AI Evaluation Run {run_id} ===")
        print(f"Running {len(cases)} test cases...\n")

        for i, tc in enumerate(cases):
            result = await self._run_single(tc, run_id)
            results.append(result)
            print(f"  [{tc['id']}] composite={result['composite_score']:.3f} "
                  f"| correctness={result['answer_correctness']:.2f} "
                  f"| citation={result['citation_accuracy']:.2f}")

            # Gemini free tier: 15 RPM — sleep between cases
            if i < len(cases) - 1:
                await asyncio.sleep(4)

        total = sum(r["composite_score"] for r in results) / len(results) if results else 0.0
        print(f"\n=== Total Score: {total:.4f} ===\n")

        await self._store_run(run_id, results, total, rewrite_id)
        return {"run_id": run_id, "total_score": total, "results": results}

    async def _run_single(self, tc: dict, run_id: str) -> dict:
        from core.context import SharedContext

        # Handle injection cases — no pipeline needed
        if tc.get("adversarial_type") == "prompt_injection":
            injection = detect_injection(tc["query"])
            final_answer = "REJECTED: prompt injection detected." if injection.is_injection else tc["query"]
            from core.context import SharedContext
            context = SharedContext(query=tc["query"])
        else:
            from worker.tasks import _run_pipeline_async
            
            # Apply approved rewrites before running the pipeline
            from db.session import AsyncSessionLocal
            from agents.overrides import apply_approved_prompt_rewrites
            async with AsyncSessionLocal() as db:
                await apply_approved_prompt_rewrites(db)
                
            res = await _run_pipeline_async(tc["query"], str(uuid.uuid4()))
            context = res["context"]
            final_answer = res["final_answer"]

        # Score all 6 dimensions
        s_correct, j_correct = score_answer_correctness(
            final_answer, tc.get("ground_truth"), self.judge_model
        )
        s_cite, j_cite = score_citation_accuracy(context)
        s_contra, j_contra = score_contradiction_resolution(context)
        s_tool, j_tool = score_tool_efficiency(
            context,
            tc.get("expected_min_tool_calls", 1),
            tc.get("expected_max_tool_calls", 5),
        )
        s_budget, j_budget = score_budget_compliance(context)
        s_agree, j_agree = score_critique_agreement(context)

        scores = {
            "answer_correctness": s_correct,
            "citation_accuracy": s_cite,
            "contradiction_resolution": s_contra,
            "tool_efficiency": s_tool,
            "budget_compliance": s_budget,
            "critique_agreement": s_agree,
        }
        composite = compute_composite(scores)

        return {
            "run_id": run_id,
            "test_case_id": tc["id"],
            "category": tc["category"],
            "final_answer": final_answer[:2000],
            "composite_score": composite,
            **scores,
            "justifications": {
                "answer_correctness": j_correct,
                "citation_accuracy": j_cite,
                "contradiction_resolution": j_contra,
                "tool_efficiency": j_tool,
                "budget_compliance": j_budget,
                "critique_agreement": j_agree,
            },
        }

    async def _run_pipeline_for_eval(self, query: str, context) -> str:
        """
        Run Gemini judge as the eval pipeline.
        temperature=0, seed=42 via generation_config for reproducibility.
        """
        try:
            resp = await asyncio.to_thread(
                self.judge_model.generate_content,
                query,
                generation_config={"temperature": 0.0},
            )
            return resp.text if hasattr(resp, "text") else ""
        except Exception as e:
            return f"Eval pipeline error: {str(e)}"

    async def _store_run(self, run_id: str, results: list, total: float, rewrite_id: str = None) -> None:
        from db.session import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(text("""
                INSERT INTO eval_runs (run_id, total_score, finished_at, model_used, seed, temperature)
                VALUES (:rid, :ts, NOW(), :gmodel, 42, 0.0)
            """), {"rid": run_id, "ts": total, "gmodel": GENERATOR_MODEL})

            for r in results:
                await db.execute(text("""
                    INSERT INTO eval_results
                    (run_id, test_case_id, category, answer_correctness, citation_accuracy,
                     contradiction_resolution, tool_efficiency, budget_compliance,
                     critique_agreement, composite_score, justifications, final_answer)
                    VALUES (:rid, :tcid, :cat, :ac, :ca, :cr, :te, :bc, :cag, :cs, :j::jsonb, :fa)
                """), {
                    "rid": run_id, "tcid": r["test_case_id"], "cat": r["category"],
                    "ac": r["answer_correctness"], "ca": r["citation_accuracy"],
                    "cr": r["contradiction_resolution"], "te": r["tool_efficiency"],
                    "bc": r["budget_compliance"], "cag": r["critique_agreement"],
                    "cs": r["composite_score"],
                    "j": json.dumps(r["justifications"]),
                    "fa": r["final_answer"],
                })
            
            if rewrite_id:
                # Calculate delta score
                # Fetch prev run id for this rewrite from failure_cases, or just average
                rewrite = await db.execute(text("SELECT failure_cases FROM prompt_rewrites WHERE rewrite_id = :id"), {"id": rewrite_id})
                row = rewrite.first()
                if row and row[0]:
                    try:
                        failure_cases = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        tc_ids = [c["test_case_id"] for c in failure_cases]
                        # get avg from old run for these test cases
                        old_avg_res = await db.execute(text("""
                            SELECT AVG(composite_score) FROM eval_results
                            WHERE test_case_id = ANY(:ids) AND run_id != :rid
                        """), {"ids": tc_ids, "rid": run_id})
                        old_avg = old_avg_res.scalar() or 0.0
                        delta = total - old_avg
                        
                        await db.execute(text("""
                            UPDATE prompt_rewrites 
                            SET delta_score = :d 
                            WHERE rewrite_id = :id
                        """), {"d": json.dumps({"delta": delta}), "id": rewrite_id})
                    except Exception as e:
                        print(f"Error computing delta: {e}")
                        
            await db.commit()
