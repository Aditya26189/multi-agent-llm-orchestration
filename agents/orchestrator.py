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
from core.budget import ContextBudgetManager, BudgetOverflowError
from core.streaming import RedisPublisher

MAX_TOOL_CALLS_PER_JOB = 20
MAX_TURNS = 10

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
        from google import genai
        api_key = os.environ.get("GOOGLE_API_KEY_ORCHESTRATOR") or os.environ.get("GOOGLE_API_KEY")
        self._client = genai.Client(api_key=api_key)

    async def route(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub: Optional[RedisPublisher] = None,
    ) -> RoutingDecision:
        """Single LLM call → validated RoutingDecision. Falls back to deterministic."""
        import asyncio

        # Hard limits
        if context.turn >= MAX_TURNS:
            context.violations.append(PolicyViolation(
                agent_id="orchestrator",
                violation_type="max_turns_exceeded",
                details=f"Reached MAX_TURNS={MAX_TURNS}, forcing synthesis",
            ))
            return RoutingDecision(
                next_agent=AgentID.SYNTHESIS,
                reasoning="Hard turn limit reached; forcing synthesis.",
                budget_allocation={AgentID.SYNTHESIS.value: 4096},
                confidence=0.5,
            )

        if context.count_tool_calls() >= MAX_TOOL_CALLS_PER_JOB:
            context.violations.append(PolicyViolation(
                agent_id="orchestrator",
                violation_type="tool_abuse",
                details=f"Reached MAX_TOOL_CALLS={MAX_TOOL_CALLS_PER_JOB}, forcing synthesis",
            ))
            return RoutingDecision(
                next_agent=AgentID.SYNTHESIS,
                reasoning="Tool call limit reached; forcing synthesis.",
                budget_allocation={AgentID.SYNTHESIS.value: 4096},
                confidence=0.5,
            )

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
            "sub_tasks_done": [t.id for t in context.subtasks if t.status.value == "done"],
            "sub_tasks_pending": [t.id for t in context.subtasks if t.status.value == "pending"],
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
            from google.genai import types
            config = types.GenerateContentConfig(response_mime_type="application/json")
            raw = await asyncio.to_thread(
                self._client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt,
                config=config,
            )
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
                    "id": context.turn,
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


import asyncio
from langgraph.graph import StateGraph, END

# Global refs for the synchronous node wrappers
_budget_mgr = None
_redis_pub = None
_orchestrator = None
_agents_map = None
_compression_agent = None

async def _run_agent_with_budget_check(agent_id: str, agent, context, budget_mgr, redis_pub):
    try:
        budget_mgr.assert_compliant(agent_id)
    except BudgetOverflowError:
        context.violations.append(PolicyViolation(
            agent_id=agent_id,
            violation_type="budget_overflow",
            details="Agent cannot run, budget exhausted before start.",
            tokens_over_budget=0,
        ))
        return
    await agent.run(context, budget_mgr, redis_pub)

async def decomposition_node(state: SharedContext) -> SharedContext:
    await _run_agent_with_budget_check(
        AgentID.DECOMPOSITION.value, _agents_map[AgentID.DECOMPOSITION], state, _budget_mgr, _redis_pub
    )
    return state

async def retrieval_node(state: SharedContext) -> SharedContext:
    await _run_agent_with_budget_check(
        AgentID.RETRIEVAL.value, _agents_map[AgentID.RETRIEVAL], state, _budget_mgr, _redis_pub
    )
    return state

async def critique_node(state: SharedContext) -> SharedContext:
    await _run_agent_with_budget_check(
        AgentID.CRITIQUE.value, _agents_map[AgentID.CRITIQUE], state, _budget_mgr, _redis_pub
    )
    return state

async def tool_runner_node(state: SharedContext) -> SharedContext:
    from agents.tool_runner import ToolRunnerAgent
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        agent = ToolRunnerAgent(db=db)
        await agent.run(state, _budget_mgr, _redis_pub)
    return state

async def synthesis_node(state: SharedContext) -> SharedContext:
    await _run_agent_with_budget_check(
        AgentID.SYNTHESIS.value, _agents_map[AgentID.SYNTHESIS], state, _budget_mgr, _redis_pub
    )
    return state

async def compression_node(state: SharedContext) -> SharedContext:
    result = await _compression_agent.compress(
        agent_id="compression",
        text=state.final_answer,
        target_tokens=1000,
        budget_mgr=_budget_mgr,
        context=state,
    )
    state.final_answer = result
    return state

async def orchestrator_node(state: SharedContext) -> SharedContext:
    if state.status == "done" or state.turn >= MAX_TURNS:
        return state
    decision = await _orchestrator.route(state, _budget_mgr, _redis_pub)
    state.metadata["routing_decision"] = decision
    return state



async def route_decision(state: SharedContext) -> str:
    """Use last RoutingDecision to choose the next node."""
    if state.status == "done" or state.turn >= MAX_TURNS:
        return END

    decision = state.metadata.get("routing_decision")
    if decision is None:
        decision = await _orchestrator.route(state, _budget_mgr, _redis_pub)

    # Prevent infinite loops in synthesis
    has_synthesis_run = any(
        e.agent_id == "synthesis"
        for e in state.execution_events
    )
    if decision.next_agent.value == "synthesis" and has_synthesis_run:
        state.status = "done"
        return END

    agent_to_node = {
        "decomposition": "decomposition",
        "retrieval": "retrieval",
        "critique": "critique",
        "synthesis": "synthesis",
        "compression": "compression",
        "tool_runner": "tool_runner",
        "done": END,
    }
    node = agent_to_node.get(decision.next_agent.value)
    if node is None:
        state.violations.append(PolicyViolation(
            agent_id="orchestrator",
            violation_type="invalid_routing_decision",
            details=f"LLM returned unknown agent: {decision.next_agent.value}",
        ))
        return END
    return node

def build_pipeline(orchestrator, agents_map, budget_mgr, redis_pub, compression_agent):
    """Call once per Celery task. Injects deps via module-level refs."""
    global _budget_mgr, _redis_pub, _orchestrator, _agents_map, _compression_agent
    _budget_mgr = budget_mgr
    _redis_pub = redis_pub
    _orchestrator = orchestrator
    _agents_map = agents_map
    _compression_agent = compression_agent

    graph = StateGraph(SharedContext)
    graph.add_node("orchestrator",  orchestrator_node)
    graph.add_node("decomposition", decomposition_node)
    graph.add_node("retrieval",     retrieval_node)
    graph.add_node("critique",      critique_node)
    graph.add_node("synthesis",     synthesis_node)
    graph.add_node("compression",   compression_node)
    graph.add_node("tool_runner",   tool_runner_node)

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges("orchestrator", route_decision)
    graph.add_edge("decomposition", "orchestrator")
    graph.add_edge("retrieval", "orchestrator")
    graph.add_edge("critique", "orchestrator")
    graph.add_edge("synthesis", "orchestrator")
    graph.add_edge("compression", "orchestrator")
    graph.add_edge("tool_runner", "orchestrator")

    return graph.compile()
