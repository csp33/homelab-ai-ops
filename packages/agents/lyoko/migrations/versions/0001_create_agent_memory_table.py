"""create agent memory table with pgvector

Revision ID: 0001
Revises:
Create Date: 2026-10-02 21:00:00.000000

"""

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Defensively attempt to enable pgvector extension if permissions permit
    # Note: On CNPG homelab clusters, admin/Ansible provisioned this, so ignore if non-superuser.
    with contextlib.suppress(Exception):
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Create agent_memory table
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("service_name", sa.String(length=128), nullable=False),
        sa.Column("alert_name", sa.String(length=128), nullable=True),
        sa.Column("incident_pattern", sa.Text(), nullable=False),
        sa.Column("operator_feedback", sa.Text(), nullable=False),
        sa.Column("action_rule", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 3. Create indexes for fast metadata lookup
    op.create_index(
        "idx_agent_memory_service",
        "agent_memory",
        ["namespace", "service_name"],
        unique=False,
    )
    op.create_index(
        "idx_agent_memory_alert",
        "agent_memory",
        ["alert_name"],
        unique=False,
    )

    # 4. Attempt to create HNSW index on embeddings
    with contextlib.suppress(Exception):
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding "
            "ON agent_memory USING hnsw (embedding vector_cosine_ops);"
        )


def downgrade() -> None:
    op.drop_index("idx_agent_memory_alert", table_name="agent_memory")
    op.drop_index("idx_agent_memory_service", table_name="agent_memory")
    op.drop_table("agent_memory")
