import pytest
import tiktoken
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
async def test_consume_text_uses_tokenizer():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("test_agent", 10000)
    text = "hello world"
    enc = tiktoken.get_encoding("o200k_base")
    expected = max(1, len(enc.encode(text)))
    await mgr.consume("test_agent", text)
    used = ctx.budget_registry["test_agent"].used_tokens
    assert used == expected


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


def test_count_tokens_uses_tokenizer():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("a", 10000)
    text = "a" * 400
    enc = tiktoken.get_encoding("o200k_base")
    expected = max(1, len(enc.encode(text)))
    count = mgr.count_tokens(text)
    assert count == expected


def test_preflight_check():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    enc = tiktoken.get_encoding("o200k_base")
    text_ok = "a" * 400
    tokens_ok = max(1, len(enc.encode(text_ok)))
    mgr.declare_budget("a", tokens_ok)
    assert mgr.preflight_check("a", text_ok) is True

    text_over = text_ok + "a"
    tokens_over = max(1, len(enc.encode(text_over)))
    while tokens_over <= tokens_ok:
        text_over += "a"
        tokens_over = max(1, len(enc.encode(text_over)))
    assert mgr.preflight_check("a", text_over) is False


def test_get_registry_returns_copy():
    ctx = SharedContext(query="test")
    mgr = ContextBudgetManager(ctx)
    mgr.declare_budget("a", 500)
    registry = mgr.get_registry()
    assert "a" in registry
    assert registry["a"].max_tokens == 500
