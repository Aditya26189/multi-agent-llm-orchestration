# ═══════════════════════════════════════════════════════════════════════════════
# MEGA-AI: MASTER AI AGENT BUILD PROMPT
# Version: FINAL (all 7 bugs fixed, all gaps filled)
# Feed this entire file to Claude Code / Cursor / Aider / any AI coding agent
# ═══════════════════════════════════════════════════════════════════════════════

## YOUR IDENTITY AND TASK

You are an expert Python backend engineer. Your task is to build a complete,
production-grade, containerized multi-agent LLM orchestration system called
MEGA-AI. Every file, every line of code, every config must match this spec
EXACTLY. Do not improvise. Do not skip steps. Do not simplify.

Read this entire prompt before writing a single line of code.

## ABSOLUTE RULES — NEVER VIOLATE THESE

1. NEVER hardcode any credential, API key, password, or secret anywhere.
   ALL config comes from environment variables only.
2. NEVER use `threading.Lock()` — this is an async system. Use `asyncio.Lock()`.
3. NEVER silently truncate context. If budget overflow: raise `BudgetOverflowError`,
   log a `PolicyViolation`, then trigger compression. Never truncate silently.
4. NEVER let agents call each other directly. ALL communication goes through
   `SharedContext`. The orchestrator mediates ALL handoffs.
5. NEVER use a hardcoded agent sequence like `[decomp, retrieval, critique, synth]`.
   The orchestrator's LLM routing decision MUST drive the pipeline loop.
6. NEVER use `cl100k_base` tiktoken encoding. Use `o200k_base` (correct for GPT-4o).
7. NEVER import `from fastapi.sse import ...` without a try/except fallback to
   `from sse_starlette.sse import ...` — the native FastAPI SSE path is uncertain.
8. ALL tool failure handling logic must be in Python code (enums, if/elif blocks).
   NONE of it may live only in prompt strings.
9. ALL eval scoring functions must produce BOTH a float score AND a justification
   string. Never a score without a justification.
10. Every commit must be a conventional commit. No mega-commits.

═══════════════════════════════════════════════════════════════════════════════
## PHASE 0: GIT AND PROJECT SCAFFOLD
═══════════════════════════════════════════════════════════════════════════════

Run these commands first:

```bash
mkdir mega-ai && cd mega-ai
git init
git checkout -b main
```

Create `.gitignore`:
```
.env
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
*.egg-info/
dist/
.coverage
htmlcov/
```

Create `Makefile`:
```makefile
.PHONY: up down seed test eval logs

up:
	docker compose up --build --wait

down:
	docker compose down -v

seed:
	docker compose exec api python scripts/seed_kb.py

test:
	docker compose exec api pytest tests/ -v --tb=short

eval:
	docker compose exec api python -c "import asyncio; from eval.harness import EvaluationHarness; asyncio.run(EvaluationHarness().run_all())"

logs:
	docker compose logs -f --tail=100
```

Commit: `chore(init): scaffold repo with Makefile, .gitignore, env config`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 1: ENVIRONMENT AND DOCKER
═══════════════════════════════════════════════════════════════════════════════

### FILE: `.env.example`
```bash
# Copy to .env and fill in real values. Never commit .env.
OPENAI_API_KEY=sk-your-openai-key-here

# PostgreSQL
POSTGRES_USER=mega_ai_user
POSTGRES_PASSWORD=changeme_before_deploy
POSTGRES_DB=mega_ai
# IMPORTANT: python-dotenv does not expand ${VAR} inside values.
# Copy this line and manually substitute your values:
DATABASE_URL=postgresql+asyncpg://mega_ai_user:changeme_before_deploy@db/mega_ai

# Redis
REDIS_URL=redis://redis:6379/0

# App
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### FILE: `docker-compose.yml`
```yaml
version: "3.8"

services:
  db:
    image: ankane/pgvector:v0.8.2
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped
    networks:
      - internal

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped
    networks:
      - internal

  api:
    build:
      context: .
      dockerfile: api/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - ENVIRONMENT=${ENVIRONMENT:-development}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - internal
    deploy:
      resources:
        limits:
          memory: 1G

  worker:
    build:
      context: .
      dockerfile: worker/Dockerfile
    command: celery -A worker.celery_app worker --loglevel=info -Q heavy_tasks --concurrency=4
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - internal
    deploy:
      resources:
        limits:
          memory: 2G

  logquery:
    build:
      context: .
      dockerfile: logquery/Dockerfile
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - internal

volumes:
  postgres_data:

networks:
  internal:
    driver: bridge
```

### FILE: `api/Dockerfile`
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN alembic upgrade head || true

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
```

### FILE: `worker/Dockerfile`
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "-Q", "heavy_tasks", "--concurrency=4"]
```

### FILE: `logquery/Dockerfile`
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install flask asyncpg psycopg2-binary

COPY logquery/ .

CMD ["python", "app.py"]
```

### FILE: `requirements.txt`
```
# Core
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
pydantic-settings>=2.3.0

# SSE — use sse-starlette as the safe, verified choice
sse-starlette>=1.8.0

# Database
sqlalchemy[asyncio]>=2.0.30
asyncpg>=0.29.0
alembic>=1.13.1
psycopg2-binary>=2.9.9

# Redis / Celery
redis>=5.0.4
celery>=5.4.0

# LLM
openai>=1.30.0
instructor>=1.3.0
tiktoken>=0.7.0

# Logging
structlog>=24.2.0

# Utilities
python-dotenv>=1.0.1
httpx>=0.27.0

# Testing
pytest>=8.2.0
pytest-asyncio>=0.23.7
respx>=0.21.0
```

Commit: `chore(docker): complete docker-compose with 5 services, health checks, no hardcoded creds`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 2: DATABASE SCHEMA
═══════════════════════════════════════════════════════════════════════════════

### FILE: `alembic.ini`
Standard alembic init. Set `sqlalchemy.url` to read from env:
```ini
[alembic]
script_location = alembic
sqlalchemy.url = %(DATABASE_URL)s
```

### FILE: `alembic/env.py`
```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from db.models import Base
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### FILE: `alembic/versions/001_initial_schema.py`
```python
"""Initial schema with pgvector and all eval tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # Document chunks for RAG
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            content TEXT NOT NULL,
            embedding vector(1536),
            source_url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
    """)

    # Core job tracking
    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            query       TEXT NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'queued',
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            total_tokens_used INT DEFAULT 0,
            total_cost_usd    FLOAT DEFAULT 0.0,
            model_used  VARCHAR(50)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")

    # Full execution trace — queryable per job, in sequence order
    op.execute("""
        CREATE TABLE IF NOT EXISTS execution_events (
            id          BIGSERIAL PRIMARY KEY,
            job_id      UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            seq         INT NOT NULL,
            agent_id    VARCHAR(50) NOT NULL,
            event_type  VARCHAR(50) NOT NULL,
            prompt_sent TEXT,
            output_received TEXT,
            input_hash  VARCHAR(16),
            output_hash VARCHAR(16),
            latency_ms  FLOAT DEFAULT 0.0,
            token_count INT DEFAULT 0,
            policy_violation TEXT,
            timestamp   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_job_seq ON execution_events(job_id, seq)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_agent ON execution_events(agent_id)")

    # Tool call log — all attempts including retries
    op.execute("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id          BIGSERIAL PRIMARY KEY,
            job_id      UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            agent_id    VARCHAR(50) NOT NULL,
            tool_name   VARCHAR(50) NOT NULL,
            attempt_number INT NOT NULL DEFAULT 1,
            input_json  JSONB,
            output_json JSONB,
            latency_ms  FLOAT DEFAULT 0.0,
            accepted    BOOL,
            error_code  VARCHAR(50),
            retry_reason TEXT,
            timestamp   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_job ON tool_calls(job_id)")

    # Eval runs — one row per full evaluation run
    op.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            run_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            triggered_at    TIMESTAMPTZ DEFAULT NOW(),
            finished_at     TIMESTAMPTZ,
            prompt_versions JSONB,
            total_score     FLOAT,
            category_breakdown JSONB,
            model_used      VARCHAR(50),
            seed            INT DEFAULT 42,
            temperature     FLOAT DEFAULT 0.0,
            notes           TEXT
        )
    """)

    # Eval results — one row per test case per eval run
    op.execute("""
        CREATE TABLE IF NOT EXISTS eval_results (
            id                      BIGSERIAL PRIMARY KEY,
            run_id                  UUID NOT NULL REFERENCES eval_runs(run_id) ON DELETE CASCADE,
            test_case_id            VARCHAR(20) NOT NULL,
            category                VARCHAR(20) NOT NULL,
            answer_correctness      FLOAT,
            citation_accuracy       FLOAT,
            contradiction_resolution FLOAT,
            tool_efficiency         FLOAT,
            budget_compliance       FLOAT,
            critique_agreement      FLOAT,
            composite_score         FLOAT,
            justifications          JSONB,
            prompt_sent_json        JSONB,
            tool_calls_json         JSONB,
            final_answer            TEXT,
            timestamp               TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_case ON eval_results(test_case_id)")

    # Prompt rewrites — self-improving loop
    op.execute("""
        CREATE TABLE IF NOT EXISTS prompt_rewrites (
            rewrite_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            proposed_at     TIMESTAMPTZ DEFAULT NOW(),
            agent_id        VARCHAR(50) NOT NULL,
            target_dimension VARCHAR(50) NOT NULL,
            original_prompt TEXT NOT NULL,
            proposed_prompt TEXT NOT NULL,
            diff_json       JSONB,
            justification   TEXT NOT NULL,
            failure_cases   JSONB,
            expected_improvement TEXT,
            status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            reviewed_at     TIMESTAMPTZ,
            reviewer_note   TEXT,
            delta_score     JSONB
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_rewrites_status ON prompt_rewrites(status)")

def downgrade() -> None:
    for table in ["prompt_rewrites", "eval_results", "eval_runs",
                  "tool_calls", "execution_events", "jobs", "document_chunks"]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
```

### FILE: `db/session.py`
```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

### FILE: `db/models.py`
```python
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
```

Commit: `feat(db): full PostgreSQL schema with pgvector, eval tables, prompt_rewrites, alembic migration`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 3: CORE — SHARED CONTEXT (THE MOST IMPORTANT FILE)
═══════════════════════════════════════════════════════════════════════════════

### FILE: `core/context.py`
Write this file EXACTLY as specified. Do not add fields. Do not remove fields.

```python
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
```

Commit: `feat(core): SharedContext Pydantic V2 schema with all sub-models and helper methods`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 4: CONTEXT BUDGET MANAGER
═══════════════════════════════════════════════════════════════════════════════

### FILE: `core/budget.py`

CRITICAL RULES FOR THIS FILE:
- Use `asyncio.Lock()` NOT `threading.Lock()`
- Use `o200k_base` encoding NOT `cl100k_base`
- The `consume()` method MUST be async (needs to await redis publish)
- `assert_compliant()` MUST raise `BudgetOverflowError` and log `PolicyViolation`
- NEVER silently truncate

```python
import asyncio
from typing import Dict, Optional, TYPE_CHECKING
import tiktoken
from core.context import BudgetEntry, PolicyViolation, SharedContext

if TYPE_CHECKING:
    from core.streaming import RedisPublisher


class BudgetOverflowError(Exception):
    def __init__(self, agent_id: str, budget: int, used: int):
        self.agent_id = agent_id
        self.budget = budget
        self.used = used
        super().__init__(
            f"Agent '{agent_id}' exceeded budget: {used}/{budget} tokens. "
            "PolicyViolation logged. Trigger compression before proceeding."
        )


class ContextBudgetManager:
    """
    Async-safe token budget manager.
    Tracks token usage per agent. Emits BUDGET_UPDATE SSE events on every consume().
    Raises BudgetOverflowError on overflow — NEVER silently truncates.
    """

    DEFAULT_BUDGETS: Dict[str, int] = {
        "orchestrator":  2048,
        "decomposition": 3072,
        "retrieval":     6144,
        "critique":      4096,
        "synthesis":     4096,
        "compression":   8192,
        "meta":          4096,
    }

    def __init__(
        self,
        context: SharedContext,
        redis_pub: Optional["RedisPublisher"] = None,
    ) -> None:
        self._context = context
        self._redis_pub = redis_pub
        self._lock = asyncio.Lock()
        # MUST use o200k_base — this is the GPT-4o tokenizer
        self._enc = tiktoken.get_encoding("o200k_base")

    def declare_budget(self, agent_id: str, max_tokens: int) -> None:
        """Synchronous — call before any async operations."""
        self._context.budget_registry[agent_id] = BudgetEntry(
            agent_id=agent_id,
            max_tokens=max_tokens,
            used_tokens=0,
        )

    def check_remaining(self, agent_id: str) -> int:
        entry = self._context.budget_registry.get(agent_id)
        if entry is None:
            raise KeyError(f"Agent '{agent_id}' has not called declare_budget().")
        return entry.remaining

    async def consume(self, agent_id: str, text_or_tokens: "str | int") -> None:
        """Async — await this. Emits BUDGET_UPDATE via Redis after every call."""
        async with self._lock:
            entry = self._context.budget_registry.get(agent_id)
            if entry is None:
                raise KeyError(f"Agent '{agent_id}' must call declare_budget() first.")

            tokens = (
                len(self._enc.encode(text_or_tokens))
                if isinstance(text_or_tokens, str)
                else text_or_tokens
            )
            entry.used_tokens += tokens

            if entry.used_tokens > entry.max_tokens * 0.8:
                entry.violations.append(
                    f"WARNING: {entry.used_tokens}/{entry.max_tokens} tokens "
                    f"({entry.used_tokens / entry.max_tokens * 100:.0f}%)"
                )

        # Emit budget update outside lock to avoid deadlock
        if self._redis_pub:
            await self._redis_pub.publish(self._context.job_id, {
                "event_type": "BUDGET_UPDATE",
                "agent_id": agent_id,
                "used_tokens": entry.used_tokens,
                "max_tokens": entry.max_tokens,
                "remaining_tokens": entry.remaining,
                "pct_used": round(entry.used_tokens / entry.max_tokens * 100, 1),
            })

    def assert_compliant(self, agent_id: str) -> None:
        """
        Call BEFORE executing an agent with its assembled context.
        Raises BudgetOverflowError if over budget.
        NEVER silently truncates — that is a policy violation.
        """
        entry = self._context.budget_registry.get(agent_id)
        if entry is None:
            return

        if not entry.is_compliant:
            violation = PolicyViolation(
                agent_id=agent_id,
                violation_type="budget_overflow",
                details=f"Used {entry.used_tokens} of {entry.max_tokens} tokens",
                tokens_over_budget=entry.used_tokens - entry.max_tokens,
            )
            self._context.violations.append(violation)
            self._context.add_event(
                agent_id=agent_id,
                event_type="error",
                policy_violation=f"budget_overflow: {entry.used_tokens}/{entry.max_tokens}",
            )
            raise BudgetOverflowError(agent_id, entry.max_tokens, entry.used_tokens)

    def count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def preflight_check(self, agent_id: str, text: str) -> bool:
        """Returns True if adding text would NOT overflow budget."""
        tokens = self.count_tokens(text)
        return tokens <= self.check_remaining(agent_id)

    def get_registry(self) -> Dict[str, BudgetEntry]:
        return dict(self._context.budget_registry)

    def serialize(self) -> dict:
        return {k: v.model_dump() for k, v in self.get_registry().items()}
```

Commit: `feat(core): ContextBudgetManager with asyncio.Lock, o200k_base encoding, BUDGET_UPDATE SSE emission`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 5: STRUCTURED LOGGING
═══════════════════════════════════════════════════════════════════════════════

### FILE: `core/logging_config.py`
```python
import hashlib
import structlog
import logging
import os


def add_hashes(logger, method_name, event_dict):
    """Add SHA-256 truncated hashes for input/output if present."""
    for field in ("prompt_sent", "output_received", "input", "output"):
        val = event_dict.get(field)
        if val and isinstance(val, str):
            event_dict[f"{field}_hash"] = hashlib.sha256(val.encode()).hexdigest()[:16]
    return event_dict


def configure_logging():
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            add_hashes,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
```

Commit: `feat(core): structlog with SHA-256 hash processor, queryable JSON logs`