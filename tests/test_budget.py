import pytest
from core.budget import ContextBudgetManager, BudgetOverflowError
from core.context import SharedContext


@pytest.mark.asyncio
async def test_declare_and_consume():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("test_agent", 1000)
    await mgr.consume("test_agent", 200)  # 200 tokens (integer)
    assert mgr.check_remaining("test_agent") == 800


@pytest.mark.asyncio
async def test_consume_text_uses_heuristic():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("test_agent", 10000)
    text = "hello world"  # 11 chars → 11 // 4 = 2 tokens
    await mgr.consume("test_agent", text)
    used = ctx.budget_registry["test_agent"].used_tokens
    assert used == max(1, len(text) // 4)


@pytest.mark.asyncio
async def test_overflow_raises_not_truncates():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("test_agent", 100)
    await mgr.consume("test_agent", 101)  # over budget
    with pytest.raises(BudgetOverflowError):
        mgr.assert_compliant("test_agent")


@pytest.mark.asyncio
async def test_policy_violation_logged_on_overflow():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("test_agent", 10)
    await mgr.consume("test_agent", 20)
    try:
        mgr.assert_compliant("test_agent")
    except BudgetOverflowError:
        pass
    assert len(ctx.violations) == 1
    assert ctx.violations[0].violation_type == "budget_overflow"


@pytest.mark.asyncio
async def test_undeclared_agent_raises_keyerror():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    with pytest.raises(KeyError):
        await mgr.consume("ghost_agent", 100)


def test_count_tokens_heuristic():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("a", 10000)
    text = "a" * 400  # 400 chars → 100 tokens
    count = mgr.count_tokens(text)
    assert count == 100


def test_preflight_check():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("a", 100)
    assert mgr.preflight_check("a", "a" * 400) is True    # 100 tokens fits exactly
    assert mgr.preflight_check("a", "a" * 404) is False   # 101 tokens does not fit


def test_get_registry_returns_copy():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("a", 500)
    registry = mgr.get_registry()
    assert "a" in registry
    assert registry["a"].max_tokens == 500
