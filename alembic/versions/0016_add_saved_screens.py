"""Add saved_screens table for persisting screener configurations.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.create_table(
        "saved_screens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filters", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("sort_by", sa.String(50), nullable=True),
        sa.Column("sort_desc", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("columns", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_saved_screens_user_id", "saved_screens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_screens_user_id", table_name="saved_screens")
    op.drop_table("saved_screens")
