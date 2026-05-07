"""
Orchestrator — routes to next agent via Gemini structured output.
Falls back to deterministic state machine on any LLM failure.
Routing decisions are logged with full reasoning.
"""
import json
import time
from typing import Optional

from core.context import (
    AgentID, SharedContext, RoutingDecision, PolicyViolation, EventType
)
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher

MAX_TOOL_CALLS_PER_JOB = 20
MAX_TURNS = 12

ORCHESTRATOR_SYSTEM = """You are the master orchestrator of a multi-agent LLM pipeline.
Decide which agent to invoke next based on the current pipeline state.

AVAILABLE AGENTS:
- decomposition: Breaks query into typed sub-tasks with dependency graph
- retrieval: Multi-hop RAG (min 2 hops). Requires decomposition to be done first.
- critique: Reviews ALL prior agent outputs. Requires retrieval to be done.
- synthesis: Merges outputs, resolves contradictions. Requires critique to be done.
- compression: Trigger only when an agent is near or over its token budget.

ROUTING LOGIC (follow unless strong reason to deviate):
1. turn=0 → decomposition
2. decomposition done, retrieval NOT done → retrieval
3. retrieval done, critique NOT done → critique
4. critique done, synthesis NOT done → synthesis
5. synthesis done → mark pipeline DONE

DEVIATIONS: allowed only with explicit reasoning. Example: skip retrieval for
a purely computational query. You MUST explain deviations in your reasoning field.

BUDGET RULE: If any agent is at >80% token budget, route to compression first."""

ORCHESTRATOR_USER_TEMPLATE = """Current pipeline state:
{state_json}

Return JSON with keys: next_agent (string), reasoning (string), confidence (float 0-1).
next_agent must be one of: decomposition, retrieval, critique, synthesis, compression, meta"""


class Orchestrator:
    def __init__(self):
        import os
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self._model = genai.GenerativeModel(
            "gemini-2.0-flash",
            generation_config={"response_mime_type": "application/json"},
        )

    async def route(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub: Optional[RedisPublisher] = None,
    ) -> RoutingDecision:
        """Single LLM call → validated RoutingDecision. Falls back to deterministic."""
        import asyncio

        # Hard limits
        if context.count_tool_calls() >= MAX_TOOL_CALLS_PER_JOB:
            context.violations.append(PolicyViolation(
                agent_id="orchestrator",
                violation_type="budget_overflow",
                details=f"MAX_TOOL_CALLS ({MAX_TOOL_CALLS_PER_JOB}) reached",
            ))
            return self._deterministic_fallback(context, "tool_limit_reached")

        if context.turn >= MAX_TURNS:
            return self._deterministic_fallback(context, "max_turns_reached")

        # Build concise state summary
        budget_warnings = [
            f"{k}: {v.used_tokens}/{v.max_tokens} ({v.used_tokens/v.max_tokens*100:.0f}%)"
            for k, v in budget_mgr.get_registry().items()
            if v.used_tokens > v.max_tokens * 0.8
        ]

        state = {
            "job_id": context.job_id,
            "query": context.query[:200],
            "turn": context.turn,
            "sub_tasks_done": [t.id for t in context.sub_tasks if t.status.value == "done"],
            "sub_tasks_pending": [t.id for t in context.sub_tasks if t.status.value == "pending"],
            "chunks_retrieved": len(context.retrieved_chunks),
            "claims_flagged": len(context.get_flagged_claims()),
            "final_answer_length": len(context.final_answer),
            "total_tool_calls": context.count_tool_calls(),
            "budget_warnings": budget_warnings,
            "agents_routed_to": [d.next_agent.value for d in context.routing_decisions],
            "violations": len(context.violations),
        }

        state_text = json.dumps(state, indent=2)
        prompt = f"{ORCHESTRATOR_SYSTEM}\n\n{ORCHESTRATOR_USER_TEMPLATE.format(state_json=state_text)}"

        budget_mgr.declare_budget("orchestrator", 2048)
        await budget_mgr.consume("orchestrator", prompt)

        start = time.monotonic()
        try:
            raw = await asyncio.to_thread(self._model.generate_content, prompt)
            raw_text = raw.text if hasattr(raw, "text") else "{}"
            data = json.loads(raw_text)
            latency = (time.monotonic() - start) * 1000

            next_agent_str = data.get("next_agent", "decomposition")
            # Validate agent name
            try:
                next_agent = AgentID(next_agent_str)
            except ValueError:
                next_agent = self._deterministic_fallback(context, f"invalid agent: {next_agent_str}").next_agent

            decision = RoutingDecision(
                next_agent=next_agent,
                reasoning=data.get("reasoning", "LLM routing decision"),
                confidence=float(data.get("confidence", 0.8)),
                budget_allocation={next_agent.value: 4096},
            )

            context.routing_decisions.append(decision)
            context.add_event(
                agent_id="orchestrator",
                event_type=EventType.HANDOFF,
                prompt_sent=prompt[:500],
                output_received=json.dumps(decision.model_dump(mode="json")),
                latency_ms=latency,
                token_count=budget_mgr.count_tokens(prompt),
            )

            if redis_pub:
                await redis_pub.publish(context.job_id, {
                    "event_type": "HANDOFF",
                    "next_agent": decision.next_agent.value,
                    "reasoning": decision.reasoning,
                    "confidence": decision.confidence,
                    "turn": context.turn,
                })

            context.turn += 1
            return decision

        except Exception as e:
            decision = self._deterministic_fallback(context, str(e)[:100])
            context.routing_decisions.append(decision)
            context.turn += 1
            return decision

    def _deterministic_fallback(self, context: SharedContext, reason: str) -> RoutingDecision:
        """State-machine fallback when LLM routing call fails."""
        has_run = context.has_agent_run

        if not has_run(AgentID.DECOMPOSITION):
            next_a = AgentID.DECOMPOSITION
        elif not has_run(AgentID.RETRIEVAL):
            next_a = AgentID.RETRIEVAL
        elif not has_run(AgentID.CRITIQUE):
            next_a = AgentID.CRITIQUE
        else:
            next_a = AgentID.SYNTHESIS

        return RoutingDecision(
            next_agent=next_a,
            reasoning=f"FALLBACK (reason={reason}): deterministic state machine.",
            budget_allocation={next_a.value: 4096},
            confidence=0.5,
        )
