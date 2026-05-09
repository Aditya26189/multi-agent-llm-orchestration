"""Add routing decisions table"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS routing_decisions (
            id          BIGSERIAL PRIMARY KEY,
            job_id      UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            turn        INT NOT NULL,
            next_agent  VARCHAR(50) NOT NULL,
            reasoning   TEXT,
            confidence  FLOAT,
            timestamp   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_routing_job ON routing_decisions(job_id)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS routing_decisions CASCADE")
