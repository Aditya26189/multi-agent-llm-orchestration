"""
test_orchestrator.py — Tests for LangGraph routing and deterministic fallback.

Tests the Orchestrator's routing logic without making real LLM calls
by patching the Gemini model with AsyncMock.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.context import SharedContext, AgentID, JobStatus, RoutingDecision
from core.budget import ContextBudgetManager
from agents.orchestrator import Orchestrator, MAX_TURNS


def _make_context(**kwargs) -> SharedContext:
    return SharedContext(query="test query", **kwargs)


def _make_budget(ctx: SharedContext) -> ContextBudgetManager:
    return ContextBudgetManager(ctx, redis_pub=None)


# ─── Deterministic Fallback ────────────────────────────────────────────────

def test_fallback_empty_context_routes_decomposition():
    orch = Orchestrator.__new__(Orchestrator)  # skip __init__ (no API key needed)
    ctx = _make_context()
    decision = orch._deterministic_fallback(ctx, "test")
    assert decision.next_agent == AgentID.DECOMPOSITION
    assert decision.confidence == 0.5
    assert "FALLBACK" in decision.reasoning


def test_fallback_after_decomposition_routes_retrieval():
    orch = Orchestrator.__new__(Orchestrator)
    ctx = _make_context()
    # Simulate decomposition having run
    ctx.routing_decisions.append(RoutingDecision(
        next_agent=AgentID.DECOMPOSITION,
        reasoning="decomp done",
        confidence=0.9,
    ))
    decision = orch._deterministic_fallback(ctx, "test")
    assert decision.next_agent == AgentID.RETRIEVAL


def test_fallback_after_retrieval_routes_critique():
    orch = Orchestrator.__new__(Orchestrator)
    ctx = _make_context()
    ctx.routing_decisions.append(RoutingDecision(
        next_agent=AgentID.DECOMPOSITION, reasoning="d", confidence=0.9,
    ))
    ctx.routing_decisions.append(RoutingDecision(
        next_agent=AgentID.RETRIEVAL, reasoning="r", confidence=0.9,
    ))
    decision = orch._deterministic_fallback(ctx, "test")
    assert decision.next_agent == AgentID.CRITIQUE


def test_fallback_after_critique_routes_synthesis():
    orch = Orchestrator.__new__(Orchestrator)
    ctx = _make_context()
    for agent in [AgentID.DECOMPOSITION, AgentID.RETRIEVAL, AgentID.CRITIQUE]:
        ctx.routing_decisions.append(RoutingDecision(
            next_agent=agent, reasoning="x", confidence=0.9,
        ))
    decision = orch._deterministic_fallback(ctx, "test")
    assert decision.next_agent == AgentID.SYNTHESIS


# ─── MAX_TURNS Hard Limit ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_returns_fallback_at_max_turns():
    orch = Orchestrator.__new__(Orchestrator)
    orch._model = MagicMock()
    ctx = _make_context()
    ctx.turn = MAX_TURNS  # At limit
    budget = _make_budget(ctx)
    budget.declare_budget("orchestrator", 2048)

    decision = await orch.route(ctx, budget, redis_pub=None)
    assert decision.next_agent == AgentID.SYNTHESIS
    assert any(v.violation_type == "max_turns_exceeded" for v in ctx.violations)


# ─── Tool Call Hard Limit ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_returns_fallback_at_tool_limit():
    from core.context import ToolCallRecord, ToolName
    orch = Orchestrator.__new__(Orchestrator)
    orch._model = MagicMock()
    ctx = _make_context()
    budget = _make_budget(ctx)
    budget.declare_budget("orchestrator", 2048)

    # Fill tool_calls to MAX limit
    for i in range(20):
        ctx.tool_calls.append(ToolCallRecord(
            job_id=ctx.job_id, agent_id="retrieval",
            tool_name=ToolName.WEB_SEARCH, attempt_number=1,
            input_data={"query": f"q{i}"},
        ))

    decision = await orch.route(ctx, budget, redis_pub=None)
    assert decision.next_agent == AgentID.SYNTHESIS
    assert any(v.violation_type == "tool_abuse" for v in ctx.violations)


# ─── LLM Path (mocked) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_uses_llm_response_when_valid(monkeypatch):
    import asyncio
    import agents.orchestrator as orch_module

    orch = Orchestrator.__new__(Orchestrator)
    orch._client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "next_agent": "retrieval",
        "reasoning": "decomp done, need retrieval",
        "confidence": 0.9,
    })
    orch._model = MagicMock()

    ctx = _make_context(status=JobStatus.RUNNING)
    budget = _make_budget(ctx)
    budget.declare_budget("orchestrator", 2048)

    async def fake_to_thread(fn, *args, **kwargs):
        return mock_response

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    decision = await orch.route(ctx, budget, redis_pub=None)
    assert decision.next_agent == AgentID.RETRIEVAL
    assert decision.confidence == pytest.approx(0.9)
    assert len(ctx.routing_decisions) == 1


@pytest.mark.asyncio
async def test_route_falls_back_on_invalid_agent_name(monkeypatch):
    import asyncio

    orch = Orchestrator.__new__(Orchestrator)
    orch._client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "next_agent": "INVALID_AGENT_NAME",
        "reasoning": "test",
        "confidence": 0.5,
    })
    orch._model = MagicMock()

    ctx = _make_context(status=JobStatus.RUNNING)
    budget = _make_budget(ctx)
    budget.declare_budget("orchestrator", 2048)

    async def fake_to_thread(fn, *args, **kwargs):
        return mock_response

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    decision = await orch.route(ctx, budget, redis_pub=None)
    # Should not crash — falls back to valid agent
    assert decision.next_agent in list(AgentID)
