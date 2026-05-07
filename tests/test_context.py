import pytest
from core.context import SharedContext, SubTask, SubTaskType, Chunk, EventType, ClaimScore


def test_shared_context_creation():
    ctx = SharedContext(query="test query")
    assert ctx.query == "test query"
    assert ctx.turn == 0
    assert len(ctx.sub_tasks) == 0
    assert "created_at" in ctx.metadata


def test_add_event():
    ctx = SharedContext(query="test")
    ctx.add_event(agent_id="orchestrator", event_type=EventType.HANDOFF, prompt_sent="hello")
    assert len(ctx.execution_events) == 1
    assert ctx.execution_events[0].seq == 0
    assert ctx.execution_events[0].input_hash is not None


def test_add_multiple_events_have_sequential_seq():
    ctx = SharedContext(query="test")
    ctx.add_event(agent_id="orchestrator", event_type=EventType.HANDOFF)
    ctx.add_event(agent_id="decomposition", event_type=EventType.AGENT_START)
    assert ctx.execution_events[0].seq == 0
    assert ctx.execution_events[1].seq == 1


def test_get_flagged_claims():
    ctx = SharedContext(query="test")
    ctx.claim_scores = [
        ClaimScore(span="claim 1", confidence=0.9, flagged=False),
        ClaimScore(span="claim 2", confidence=0.3, flagged=True),
    ]
    flagged = ctx.get_flagged_claims()
    assert len(flagged) == 1
    assert flagged[0].span == "claim 2"


def test_count_tool_calls_no_filter():
    from core.context import ToolCallRecord, ToolName
    ctx = SharedContext(query="test")
    ctx.tool_calls = [
        ToolCallRecord(job_id=ctx.job_id, agent_id="retrieval", tool_name=ToolName.WEB_SEARCH,
                       attempt_number=1, input_data={}),
        ToolCallRecord(job_id=ctx.job_id, agent_id="critique", tool_name=ToolName.SELF_REFLECT,
                       attempt_number=1, input_data={}),
    ]
    assert ctx.count_tool_calls() == 2
    assert ctx.count_tool_calls("retrieval") == 1


def test_snapshot_returns_dict():
    ctx = SharedContext(query="test")
    snap = ctx.snapshot()
    assert isinstance(snap, dict)
    assert snap["query"] == "test"
