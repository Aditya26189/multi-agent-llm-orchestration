"""
Meta Agent — analyzes evaluation failures and proposes prompt rewrites.
Uses difflib.ndiff for auditable diffs. Persists PromptRewrite to DB.
NEVER auto-applies — status stays pending until human reviews.
"""
import difflib
import json
import time
from datetime import datetime
from typing import List, Optional
import uuid

from pydantic import BaseModel, Field

from agents.base import BaseAgent
from core.context import SharedContext, EventType
from core.budget import ContextBudgetManager

META_PROMPT = """You are the meta-agent responsible for improving pipeline prompts.

Read these evaluation failure cases:
{failure_cases_json}

The worst-performing dimension is: {worst_dimension}
The agent responsible for this dimension is: {agent_id}
The current prompt for that agent is:
---
{current_prompt}
---

Propose a rewritten version of this prompt that would fix the failures.
Be specific. Address each failure case explicitly.

Return JSON with keys:
- proposed_prompt: the new prompt text
- justification: why these changes will fix the failures
- expected_improvement: what score improvement you expect and why"""


class DiffLine(BaseModel):
    line_type: str  # "ADD" | "REMOVE" | "CONTEXT"
    content: str


class PromptRewrite(BaseModel):
    rewrite_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proposed_at: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str
    target_dimension: str
    original_prompt: str
    proposed_prompt: str
    diff_lines: List[DiffLine] = Field(default_factory=list)
    justification: str
    failure_cases: List[str] = Field(default_factory=list)
    expected_improvement: str
    status: str = "pending"
    reviewed_at: Optional[datetime] = None
    reviewer_note: Optional[str] = None
    delta_score: Optional[dict] = None

    def generate_diff(self) -> None:
        diff = list(difflib.ndiff(
            self.original_prompt.splitlines(),
            self.proposed_prompt.splitlines(),
        ))
        self.diff_lines = []
        for line in diff:
            if line.startswith("+ "):
                self.diff_lines.append(DiffLine(line_type="ADD", content=line[2:]))
            elif line.startswith("- "):
                self.diff_lines.append(DiffLine(line_type="REMOVE", content=line[2:]))
            elif line.startswith("  "):
                self.diff_lines.append(DiffLine(line_type="CONTEXT", content=line[2:]))


class MetaAgent(BaseAgent):
    async def propose_rewrite(
        self,
        failure_cases: list,
        worst_dimension: str,
        agent_id: str,
        current_prompt: str,
    ) -> PromptRewrite:
        prompt = META_PROMPT.format(
            failure_cases_json=json.dumps(failure_cases[:5], indent=2),
            worst_dimension=worst_dimension,
            agent_id=agent_id,
            current_prompt=current_prompt[:2000],
        )
        raw_json = await self.generate_json(prompt)
        data = json.loads(raw_json)

        rewrite = PromptRewrite(
            agent_id=agent_id,
            target_dimension=worst_dimension,
            original_prompt=current_prompt,
            proposed_prompt=data.get("proposed_prompt", current_prompt),
            justification=data.get("justification", ""),
            expected_improvement=data.get("expected_improvement", ""),
            failure_cases=[str(c.get("test_case_id", "")) for c in failure_cases],
        )
        rewrite.generate_diff()
        return rewrite

    async def persist_rewrite(self, rewrite: PromptRewrite) -> None:
        """Persist PromptRewrite to DB. Status stays pending — human must review."""
        from db.session import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(text("""
                INSERT INTO prompt_rewrites
                (rewrite_id, agent_id, target_dimension, original_prompt, proposed_prompt,
                 diff_json, justification, failure_cases, expected_improvement, status)
                VALUES (:rid, :aid, :td, :op, :pp, :dj::jsonb, :just, :fc::jsonb, :ei, 'pending')
                ON CONFLICT (rewrite_id) DO NOTHING
            """), {
                "rid": rewrite.rewrite_id,
                "aid": rewrite.agent_id,
                "td": rewrite.target_dimension,
                "op": rewrite.original_prompt,
                "pp": rewrite.proposed_prompt,
                "dj": json.dumps([d.model_dump() for d in rewrite.diff_lines]),
                "just": rewrite.justification,
                "fc": json.dumps(rewrite.failure_cases),
                "ei": rewrite.expected_improvement,
            })
            await db.commit()

    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub=None,
    ) -> None:
        """Run from eval results — analyze failures and propose rewrite."""
        try:
            from db.session import AsyncSessionLocal
            from sqlalchemy import text

            async with AsyncSessionLocal() as db:
                # Fetch latest eval run failures
                rows = await db.execute(text("""
                    SELECT er.test_case_id, er.category, er.answer_correctness,
                           er.citation_accuracy, er.contradiction_resolution,
                           er.tool_efficiency, er.budget_compliance, er.critique_agreement,
                           er.composite_score, er.justifications
                    FROM eval_results er
                    JOIN eval_runs ev ON er.run_id = ev.run_id
                    WHERE ev.triggered_at = (SELECT MAX(triggered_at) FROM eval_runs)
                    ORDER BY er.composite_score ASC
                    LIMIT 10
                """))
                failures = [dict(r) for r in rows.mappings().all()]

            if not failures:
                return

            # Find worst dimension
            dim_scores = {
                "answer_correctness": [],
                "citation_accuracy": [],
                "contradiction_resolution": [],
                "tool_efficiency": [],
                "budget_compliance": [],
                "critique_agreement": [],
            }
            for f in failures:
                for dim in dim_scores:
                    if f.get(dim) is not None:
                        dim_scores[dim].append(f[dim])

            worst_dim = min(
                dim_scores,
                key=lambda d: sum(dim_scores[d]) / len(dim_scores[d]) if dim_scores[d] else 1.0
            )

            # Map dimension to responsible agent
            agent_map = {
                "answer_correctness": "synthesis",
                "citation_accuracy": "retrieval",
                "contradiction_resolution": "synthesis",
                "tool_efficiency": "orchestrator",
                "budget_compliance": "orchestrator",
                "critique_agreement": "critique",
            }
            responsible_agent = agent_map.get(worst_dim, "synthesis")

            rewrite = await self.propose_rewrite(
                failure_cases=failures,
                worst_dimension=worst_dim,
                agent_id=responsible_agent,
                current_prompt=f"Current {responsible_agent} prompt (see agents/{responsible_agent}.py)",
            )
            await self.persist_rewrite(rewrite)

        except Exception as e:
            context.add_event(
                agent_id="meta",
                event_type=EventType.ERROR,
                policy_violation=f"meta_failed: {str(e)[:100]}",
            )
