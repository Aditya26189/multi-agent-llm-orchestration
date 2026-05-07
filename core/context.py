from __future__ import annotations
import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
import uuid


class AgentID(str, Enum):
    ORCHESTRATOR = "orchestrator"
    DECOMPOSITION = "decomposition"
    RETRIEVAL = "retrieval"
    CRITIQUE = "critique"
    SYNTHESIS = "synthesis"
    COMPRESSION = "compression"
    META = "meta"


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class SubTaskType(str, Enum):
    FACTUAL_LOOKUP = "factual_lookup"
    REASONING = "reasoning"
    CODE_EXECUTION = "code_execution"
    DATA_RETRIEVAL = "data_retrieval"
    SUMMARIZATION = "summarization"
    VERIFICATION = "verification"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ToolName(str, Enum):
    WEB_SEARCH = "web_search"
    CODE_EXEC = "code_exec"
    SQL_LOOKUP = "sql_lookup"
    SELF_REFLECT = "self_reflect"


class EventType(str, Enum):
    AGENT_START = "AGENT_START"
    TOKEN = "TOKEN"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_END = "TOOL_CALL_END"
    BUDGET_UPDATE = "BUDGET_UPDATE"
    HANDOFF = "HANDOFF"
    COMPRESSION_TRIGGERED = "COMPRESSION_TRIGGERED"
    DONE = "done"
    ERROR = "error"


class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: SubTaskType
    description: str
    deps: List[str] = Field(default_factory=list)
    status: SubTaskStatus = SubTaskStatus.PENDING
    output: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str
    source_url: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    hop_number: int = Field(ge=1)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class ClaimScore(BaseModel):
    span: str
    start_char: int = 0
    end_char: int = 0
    confidence: float = Field(ge=0.0, le=1.0)
    flagged: bool = False
    flag_reason: Optional[str] = None
    scored_by: AgentID = AgentID.CRITIQUE


class ProvenanceEntry(BaseModel):
    sentence: str
    source_agent: AgentID
    source_chunk_id: Optional[str] = None


class BudgetEntry(BaseModel):
    agent_id: str
    max_tokens: int
    used_tokens: int = 0
    violations: List[str] = Field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def is_compliant(self) -> bool:
        return self.used_tokens <= self.max_tokens


class ToolCallRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    job_id: str
    agent_id: str
    tool_name: ToolName
    attempt_number: int = Field(ge=1, le=3)
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]] = None
    latency_ms: float = 0.0
    accepted: Optional[bool] = None
    error_code: Optional[str] = None
    retry_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RoutingDecision(BaseModel):
    next_agent: AgentID
    context_slice: Dict[str, Any] = Field(default_factory=dict)
    reasoning: str
    budget_allocation: Dict[str, int] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    fallback_agent: Optional[AgentID] = None
    decided_at: datetime = Field(default_factory=datetime.utcnow)


class PolicyViolation(BaseModel):
    violation_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_id: str
    violation_type: Literal[
        "budget_overflow", "direct_agent_call", "tool_retry_exceeded",
        "schema_invalid", "injection_detected",
    ]
    details: str
    tokens_over_budget: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionEventSchema(BaseModel):
    seq: int
    job_id: str
    agent_id: str
    event_type: EventType
    prompt_sent: Optional[str] = None
    output_received: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    latency_ms: float = 0.0
    token_count: int = 0
    policy_violation: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SharedContext(BaseModel):
    """
    THE ONLY inter-agent communication channel.
    Agents MUST NOT call each other directly.
    The Orchestrator mediates ALL handoffs.
    This object is the single source of truth for the entire pipeline.
    """
    model_config = {"arbitrary_types_allowed": True}

    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str
    turn: int = 0
    status: JobStatus = JobStatus.QUEUED

    # Decomposition outputs
    sub_tasks: List[SubTask] = Field(default_factory=list)
    dependency_graph: Dict[str, List[str]] = Field(default_factory=dict)

    # Retrieval outputs
    retrieved_chunks: List[Chunk] = Field(default_factory=list)
    retrieval_reasoning: str = ""

    # Critique outputs
    claim_scores: List[ClaimScore] = Field(default_factory=list)

    # Synthesis outputs
    final_answer: str = ""
    provenance_map: List[ProvenanceEntry] = Field(default_factory=list)
    contradictions_resolved: List[Dict[str, str]] = Field(default_factory=list)

    # Budget management
    budget_registry: Dict[str, BudgetEntry] = Field(default_factory=dict)

    # Tool call history
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)

    # Orchestrator routing log
    routing_decisions: List[RoutingDecision] = Field(default_factory=list)

    # Policy violations
    violations: List[PolicyViolation] = Field(default_factory=list)

    # Execution events (full trace)
    execution_events: List[ExecutionEventSchema] = Field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if "created_at" not in self.metadata:
            self.metadata["created_at"] = datetime.utcnow().isoformat()

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Chunk]:
        return next((c for c in self.retrieved_chunks if c.id == chunk_id), None)

    def get_flagged_claims(self) -> List[ClaimScore]:
        return [c for c in self.claim_scores if c.flagged]

    def count_tool_calls(self, agent_id: Optional[str] = None) -> int:
        if agent_id:
            return len([tc for tc in self.tool_calls if tc.agent_id == agent_id])
        return len(self.tool_calls)

    def has_agent_run(self, agent_id: AgentID) -> bool:
        return any(
            d.next_agent == agent_id
            for d in self.routing_decisions
            if d.confidence >= 0.4
        )

    def snapshot(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def add_event(
        self,
        agent_id: str,
        event_type: EventType,
        prompt_sent: Optional[str] = None,
        output_received: Optional[str] = None,
        latency_ms: float = 0.0,
        token_count: int = 0,
        policy_violation: Optional[str] = None,
    ) -> None:
        seq = len(self.execution_events)
        ih = hashlib.sha256((prompt_sent or "").encode()).hexdigest()[:16] if prompt_sent else None
        oh = hashlib.sha256((output_received or "").encode()).hexdigest()[:16] if output_received else None
        self.execution_events.append(ExecutionEventSchema(
            seq=seq,
            job_id=self.job_id,
            agent_id=agent_id,
            event_type=event_type,
            prompt_sent=prompt_sent,
            output_received=output_received,
            input_hash=ih,
            output_hash=oh,
            latency_ms=latency_ms,
            token_count=token_count,
            policy_violation=policy_violation,
        ))
