"""Add screen_results table for historical stock screener.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screen_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("screen_name", sa.String(200), nullable=False),
        sa.Column("screen_version", sa.String(50), nullable=False, server_default="screen_v1"),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("matches", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("artefact_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_screen_results_user_id", "screen_results", ["user_id"])
    op.create_index("ix_screen_results_created_at", "screen_results", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_screen_results_created_at", table_name="screen_results")
    op.drop_index("ix_screen_results_user_id", table_name="screen_results")
    op.drop_table("screen_results")
