from sqlalchemy import Column, String, Float, Integer, Boolean, Text, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import uuid


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query = Column(Text, nullable=False)
    status = Column(String(20), default="queued")
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    completed_at = Column(TIMESTAMPTZ, nullable=True)
    total_tokens_used = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    model_used = Column(String(50), nullable=True)


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), nullable=False)
    seq = Column(Integer, nullable=False)
    agent_id = Column(String(50), nullable=False)
    event_type = Column(String(50), nullable=False)
    prompt_sent = Column(Text, nullable=True)
    output_received = Column(Text, nullable=True)
    input_hash = Column(String(16), nullable=True)
    output_hash = Column(String(16), nullable=True)
    latency_ms = Column(Float, default=0.0)
    token_count = Column(Integer, default=0)
    policy_violation = Column(Text, nullable=True)
    timestamp = Column(TIMESTAMPTZ, default=datetime.utcnow)


class PromptRewrite(Base):
    __tablename__ = "prompt_rewrites"
    rewrite_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposed_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    agent_id = Column(String(50), nullable=False)
    target_dimension = Column(String(50), nullable=False)
    original_prompt = Column(Text, nullable=False)
    proposed_prompt = Column(Text, nullable=False)
    diff_json = Column(JSONB, nullable=True)
    justification = Column(Text, nullable=False)
    failure_cases = Column(JSONB, nullable=True)
    expected_improvement = Column(Text, nullable=True)
    status = Column(String(20), default="PENDING")
    reviewed_at = Column(TIMESTAMPTZ, nullable=True)
    reviewer_note = Column(Text, nullable=True)
    delta_score = Column(JSONB, nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    triggered_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    finished_at = Column(TIMESTAMPTZ, nullable=True)
    prompt_versions = Column(JSONB, nullable=True)
    total_score = Column(Float, nullable=True)
    category_breakdown = Column(JSONB, nullable=True)
    model_used = Column(String(50), nullable=True)
    seed = Column(Integer, default=42)
    temperature = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)


class EvalResult(Base):
    __tablename__ = "eval_results"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), nullable=False)
    test_case_id = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False)
    answer_correctness = Column(Float, nullable=True)
    citation_accuracy = Column(Float, nullable=True)
    contradiction_resolution = Column(Float, nullable=True)
    tool_efficiency = Column(Float, nullable=True)
    budget_compliance = Column(Float, nullable=True)
    critique_agreement = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)
    justifications = Column(JSONB, nullable=True)
    prompt_sent_json = Column(JSONB, nullable=True)
    tool_calls_json = Column(JSONB, nullable=True)
    final_answer = Column(Text, nullable=True)
    timestamp = Column(TIMESTAMPTZ, default=datetime.utcnow)
