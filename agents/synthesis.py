"""
Synthesis Agent — resolves flagged claims as RESOLVE / REMOVE / HEDGE.
Updates final_answer, provenance_map, contradictions_resolved.
"""
import json
import time
from typing import List

from agents.base import BaseAgent
from core.context import SharedContext, ProvenanceEntry, AgentID, EventType
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher

SYNTHESIS_PROMPT = """You are a synthesis agent. Your job is to produce a final, accurate answer
by resolving all flagged claims from the critique agent.

ORIGINAL DRAFT ANSWER:
{draft_answer}

FLAGGED CLAIMS (must be addressed):
{flagged_claims}

RETRIEVED SOURCE CHUNKS:
{chunks}

For each flagged claim, you MUST:
- RESOLVE: replace with accurate info from sources
- REMOVE: delete if unsupported and not needed
- HEDGE: add uncertainty language ("may", "possibly", "evidence suggests") if contested

In your final answer:
- Cite sources as [CHUNK:chunk_id] for chunk-backed sentences
- Use [REASONING] for deductions from your own analysis
- Never repeat a flagged claim verbatim without hedging or removal
- Document what you did to each flagged claim in a JSON block at the end

Final Answer:
<write the resolved answer here>

Resolution Log (JSON):
{{"resolutions": [{{"original": "...", "resolution_type": "RESOLVE|REMOVE|HEDGE", "new_text": "...", "claim_score_id": "..."}}]}}"""


class SynthesisAgent(BaseAgent):
    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub=None,
    ) -> None:
        budget_mgr.declare_budget("synthesis", 4096)

        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "AGENT_START", "agent_id": "synthesis"
            })

        flagged = [(i, c) for i, c in enumerate(context.claim_scores) if c.flagged]
        flagged_text = "\n".join(
            f"- [id={i}] [{c.confidence:.2f}] '{c.span[:100]}': {c.flag_reason or 'flagged'}"
            for i, c in flagged
        ) or "No flagged claims."

        chunks_text = "\n\n".join(
            f"[CHUNK:{c.id}]: {c.text[:300]}"
            for c in context.retrieved_chunks[:6]
        )

        prompt = SYNTHESIS_PROMPT.format(
            draft_answer=context.final_answer[:1500],
            flagged_claims=flagged_text,
            chunks=chunks_text,
        )

        await budget_mgr.consume("synthesis", prompt)
        budget_mgr.assert_compliant("synthesis")

        start = time.monotonic()
        full_response = await self.stream_response(prompt, context, redis_pub, "synthesis")
        latency = (time.monotonic() - start) * 1000

        # Parse resolution log from response
        final_answer = full_response
        resolutions = []
        if "Resolution Log (JSON):" in full_response:
            parts = full_response.split("Resolution Log (JSON):", 1)
            final_answer = parts[0].replace("Final Answer:", "").strip()
            try:
                res_data = json.loads(parts[1].strip())
                resolutions = res_data.get("resolutions", [])
            except Exception:
                pass
        elif "Final Answer:" in full_response:
            final_answer = full_response.split("Final Answer:", 1)[1].strip()

        context.final_answer = final_answer
        resolved_entries = []
        for item in resolutions:
            resolved_entries.append({
                "original": item.get("original", ""),
                "resolution_type": item.get("resolution_type", ""),
                "new_text": item.get("new_text", ""),
                "claim_score_id": item.get("claim_score_id", ""),
            })

        if not resolved_entries and flagged:
            for idx, claim in flagged:
                resolved_entries.append({
                    "original": claim.span,
                    "resolution_type": "HEDGE",
                    "new_text": claim.span,
                    "claim_score_id": str(idx),
                })

        context.contradictions_resolved = resolved_entries

        # Update provenance map with synthesis sentences
        valid_ids = {c.id for c in context.retrieved_chunks}
        new_provenance = list(context.provenance_map)
        for line in final_answer.splitlines():
            line = line.strip()
            if line.startswith("[CHUNK:"):
                end = line.find("]")
                if end > 0:
                    chunk_id = line[7:end]
                    sentence = line[end+1:].strip()
                    new_provenance.append(ProvenanceEntry(
                        sentence=sentence,
                        source_agent=AgentID.SYNTHESIS,
                        source_chunk_id=chunk_id if chunk_id in valid_ids else None,
                    ))
            elif line.startswith("[REASONING]"):
                new_provenance.append(ProvenanceEntry(
                    sentence=line[11:].strip(),
                    source_agent=AgentID.SYNTHESIS,
                    source_chunk_id=None,
                ))

        context.provenance_map = new_provenance

        await budget_mgr.consume("synthesis", full_response)
        context.add_event(
            agent_id="synthesis",
            event_type=EventType.AGENT_START,
            prompt_sent=prompt[:500],
            output_received=final_answer[:500],
            latency_ms=latency,
            token_count=budget_mgr.count_tokens(prompt),
        )
