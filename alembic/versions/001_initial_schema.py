"""Initial schema with pgvector(768) and all eval tables."""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # Document chunks for RAG — 768-dim for Gemini text-embedding-004
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            content TEXT NOT NULL,
            embedding vector(768),
            source_url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Core job tracking
    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            query       TEXT NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','running','done','failed')),
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
            attempt_number INT NOT NULL DEFAULT 1
                          CHECK (attempt_number BETWEEN 1 AND 3),
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
            composite_score         FLOAT GENERATED ALWAYS AS (
                COALESCE(answer_correctness,0)       * 0.30 +
                COALESCE(citation_accuracy,0)        * 0.15 +
                COALESCE(contradiction_resolution,0) * 0.20 +
                COALESCE(tool_efficiency,0)          * 0.15 +
                COALESCE(budget_compliance,0)        * 0.10 +
                COALESCE(critique_agreement,0)       * 0.10
            ) STORED,
            justifications          JSONB,
            prompt_sent_json        JSONB,
            tool_calls_json         JSONB,
            final_answer            TEXT,
            timestamp               TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_case ON eval_results(test_case_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_results_run_case ON eval_results(run_id, test_case_id)")

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
            status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','approved','rejected')),
            reviewed_at     TIMESTAMPTZ,
            reviewer_note   TEXT,
            delta_score     JSONB
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_rewrites_status ON prompt_rewrites(status)")

    # chunk_relations: Vector Graph RAG traversal
    op.execute("""
        CREATE TABLE IF NOT EXISTS chunk_relations (
            source_chunk_id UUID REFERENCES document_chunks(id) ON DELETE CASCADE,
            target_chunk_id UUID REFERENCES document_chunks(id) ON DELETE CASCADE,
            relation_type   VARCHAR(50),
            PRIMARY KEY (source_chunk_id, target_chunk_id)
        )
    """)

    # GIN on tool_calls input_json
    op.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_json ON tool_calls USING GIN (input_json)")

    # Policy violations audit
    op.execute("""
        CREATE TABLE IF NOT EXISTS policy_violations (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            job_id          UUID REFERENCES jobs(job_id),
            agent_id        VARCHAR(50),
            violation_type  VARCHAR(50),
            details         TEXT,
            tokens_over_budget INT,
            timestamp       TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # prompt_versions — tracks active prompt per agent (Section 4 schema)
    op.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            version_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            agent_id    VARCHAR(50),
            prompt_text TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            is_active   BOOLEAN DEFAULT TRUE
        )
    """)


def downgrade() -> None:
    for table in ["policy_violations", "chunk_relations", "prompt_rewrites", "eval_results", "eval_runs",
                  "tool_calls", "execution_events", "jobs", "document_chunks"]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
