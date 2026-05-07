import pytest
from core.tools import tool_web_search, tool_code_exec, handle_tool_failure, ToolAction
from core.context import SharedContext


@pytest.mark.asyncio
async def test_web_search_empty_query():
    result = await tool_web_search(query="")
    assert not result.success
    assert result.error_code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_web_search_whitespace_query():
    result = await tool_web_search(query="   ")
    assert not result.success
    assert result.error_code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_web_search_success():
    result = await tool_web_search(query="Paris capital France")
    assert result.success
    assert "results" in result.data
    assert len(result.data["results"]) > 0


@pytest.mark.asyncio
async def test_web_search_returns_latency():
    result = await tool_web_search(query="test query")
    assert result.latency_ms > 0


@pytest.mark.asyncio
async def test_code_exec_success():
    result = await tool_code_exec(code="print(2 + 2)")
    assert result.success
    assert result.data["stdout"] == "4"
    assert result.data["exit_code"] == 0


@pytest.mark.asyncio
async def test_code_exec_blocked_pattern():
    result = await tool_code_exec(code="import os; os.system('ls')")
    assert not result.success
    assert result.error_code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_code_exec_runtime_error():
    result = await tool_code_exec(code="1/0")
    assert not result.success
    assert result.error_code == "EXEC_ERROR"


@pytest.mark.asyncio
async def test_code_exec_empty_code():
    result = await tool_code_exec(code="")
    assert not result.success
    assert result.error_code == "INVALID_INPUT"


def test_handle_tool_failure_timeout_retries():
    from unittest.mock import MagicMock
    ctx = SharedContext(query="test")
    result = MagicMock(error_code="TIMEOUT", success=False)
    action = handle_tool_failure(result, "web_search", 1, ctx)
    assert action == ToolAction.RETRY_SAME


def test_handle_tool_failure_timeout_exhausted():
    from unittest.mock import MagicMock
    ctx = SharedContext(query="test")
    result = MagicMock(error_code="TIMEOUT", success=False)
    action = handle_tool_failure(result, "web_search", 2, ctx)
    assert action == ToolAction.ABORT


def test_handle_tool_failure_no_results_reformulates():
    from unittest.mock import MagicMock
    ctx = SharedContext(query="test")
    result = MagicMock(error_code="NO_RESULTS", success=False)
    action = handle_tool_failure(result, "web_search", 1, ctx)
    assert action == ToolAction.RETRY_REFORMULATE


def test_handle_tool_failure_invalid_logs_violation():
    from unittest.mock import MagicMock
    ctx = SharedContext(query="test")
    result = MagicMock(error_code="INVALID_INPUT", success=False, error_message="bad input")
    action = handle_tool_failure(result, "web_search", 1, ctx)
    assert action == ToolAction.SKIP_LOG_VIOLATION
    assert len(ctx.violations) == 1
    assert ctx.violations[0].violation_type == "schema_invalid"


def test_handle_tool_failure_exec_error_fallback():
    from unittest.mock import MagicMock
    ctx = SharedContext(query="test")
    result = MagicMock(error_code="EXEC_ERROR", success=False)
    action = handle_tool_failure(result, "code_exec", 1, ctx)
    assert action == ToolAction.FALLBACK_TOOL
