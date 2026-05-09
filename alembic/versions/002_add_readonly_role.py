"""
Create read-only user for SQL lookup tool.
"""
from alembic import op

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Read-only role for NL-to-SQL tool
    op.execute("CREATE ROLE mega_readonly")
    op.execute("GRANT CONNECT ON DATABASE megaai TO mega_readonly")
    op.execute("GRANT USAGE ON SCHEMA public TO mega_readonly")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO mega_readonly")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mega_readonly")

def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM mega_readonly")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM mega_readonly")
    op.execute("REVOKE USAGE ON SCHEMA public FROM mega_readonly")
    op.execute("REVOKE CONNECT ON DATABASE mega_ai FROM mega_readonly")
    op.execute("DROP ROLE IF EXISTS mega_readonly")
