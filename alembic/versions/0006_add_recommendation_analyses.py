"""Add recommendation_analyses table for caching AI-generated analyses.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_analyses",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("score_hash", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("analysis_version", sa.String(50), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("content", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "score_hash", "prompt_hash", name="uq_rec_analysis_ticker_hashes"),
    )
    op.create_index("ix_rec_analysis_ticker", "recommendation_analyses", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_rec_analysis_ticker", table_name="recommendation_analyses")
    op.drop_table("recommendation_analyses")
