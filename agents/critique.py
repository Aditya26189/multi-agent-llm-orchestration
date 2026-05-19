"""
Critique Agent — per-span ClaimScore with confidence scoring.
Reviews ALL prior agent outputs and assigns ClaimScore per text span.
"""
import json
import time
from typing import List

from agents.base import BaseAgent
from core.context import SharedContext, ClaimScore, AgentID, EventType
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher

CRITIQUE_PROMPT = """You are a rigorous fact-checking critique agent.

Review the outputs of ALL agents in this pipeline:

DECOMPOSITION OUTPUT (sub-tasks):
{subtasks_json}

RETRIEVAL CITATIONS:
{retrieval_answer}

DRAFT ANSWER (pre-synthesis):
{draft_answer}

SOURCE CHUNKS (ground truth):
{chunks}

STEP 0 — FALSE PREMISE DETECTION (run this before anything else):
Examine the ORIGINAL QUERY for embedded factual premises.
For each premise you can verify against the source chunks:
- If the premise is demonstrably FALSE: create a ClaimScore with
    span=<the false premise text>,
    confidence=0.0,
    flagged=True,
    flag_reason='false_premise: <the query assumes X>, but [CHUNK:id] states: <correct fact>'
- The system MUST NOT answer the original question while accepting a false premise.
Examples of false premises to catch:
    'Einstein won the Nobel Prize for relativity' → FALSE
    'The US annexed Canada in 2024' → FALSE
    'Mars has confirmed liquid water' → CONTESTED/FALSE

Critique ALL THREE sections above. For each problematic text span:
- Extract the EXACT span
- Assign confidence 0.0-1.0 (1.0 = fully supported)
- Set flagged=true if confidence < 0.6
- Provide flag_reason citing specific evidence. Format exactly as:
    'contradicts [CHUNK:uuid] which states: "<exact quote from chunk>"'
    or for false premises:
    'false_premise: the query assumes X, but [CHUNK:uuid] states: "<correct fact>"'
    DO NOT write vague reasons like 'this seems uncertain' or 'unverified claim'.

DO NOT flag without positive evidence. DO NOT evaluate holistically.

Return JSON with key "claim_scores" as an array. Each item must have:
- span: exact text span (string)
- confidence: float 0.0-1.0
- flagged: boolean
- flag_reason: string (empty if not flagged)"""


class CritiqueAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_id="critique")
    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub=None,
    ) -> None:
        budget_mgr.declare_budget("critique", 4096)

        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "AGENT_START", "agent_id": "critique"
            })

        chunks_text = "\n\n".join(
            f"[CHUNK:{c.id}]: {c.text[:300]}"
            for c in context.retrieved_chunks[:8]
        )
        prompt = CRITIQUE_PROMPT.format(
            subtasks_json=json.dumps([t.model_dump(mode="json") for t in context.subtasks], indent=2),
            retrieval_answer=context.retrieval_reasoning[:800],
            draft_answer=context.final_answer[:800],
            chunks=chunks_text,
        )

        await budget_mgr.consume("critique", prompt)
        budget_mgr.assert_compliant("critique")

        start = time.monotonic()
        try:
            raw_json = await self.generate_json(prompt)
            data = json.loads(raw_json)
            latency = (time.monotonic() - start) * 1000

            claim_scores = []
            for item in data.get("claim_scores", []):
                try:
                    cs = ClaimScore(
                        span=str(item.get("span", ""))[:200],
                        confidence=max(0.0, min(1.0, float(item.get("confidence", 1.0)))),
                        flagged=bool(item.get("flagged", False)),
                        flag_reason=str(item.get("flag_reason", "")) or None,
                        scored_by=AgentID.CRITIQUE,
                    )
                    claim_scores.append(cs)
                except Exception:
                    continue

            context.claim_scores = claim_scores
            await budget_mgr.consume("critique", raw_json)

            context.add_event(
                agent_id="critique",
                event_type=EventType.AGENT_START,
                prompt_sent=prompt[:500],
                output_received=raw_json[:500],
                latency_ms=latency,
                token_count=budget_mgr.count_tokens(prompt),
            )

        except Exception as e:
            # If critique fails, add no claims so synthesis proceeds unblocked
            context.claim_scores = []
            context.add_event(
                agent_id="critique",
                event_type=EventType.ERROR,
                policy_violation=f"critique_failed: {str(e)[:100]}",
            )
