"""Add signal_changes table for tracking classification flips.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.create_table(
        "signal_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("system", sa.String(20), nullable=False),
        sa.Column("old_classification", sa.String(10), nullable=False),
        sa.Column("new_classification", sa.String(10), nullable=False),
        sa.Column("old_score", sa.Float(), nullable=False),
        sa.Column("new_score", sa.Float(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_signal_changes_detected_at", "signal_changes", ["detected_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_signal_changes_detected_at", table_name="signal_changes")
    op.drop_table("signal_changes")
