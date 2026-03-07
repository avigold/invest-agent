"""Add prediction_models and prediction_scores tables.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("fold_metrics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("aggregate_metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("feature_importance", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("backtest_results", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("model_blob", sa.LargeBinary(), nullable=True),
        sa.Column("platt_a", sa.Float(), nullable=False, server_default="0"),
        sa.Column("platt_b", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_prediction_models_user_id", "prediction_models", ["user_id"])
    op.create_index("ix_prediction_models_created_at", "prediction_models", ["created_at"])

    op.create_table(
        "prediction_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("confidence_tier", sa.String(20), nullable=False),
        sa.Column("kelly_fraction", sa.Float(), nullable=False, server_default="0"),
        sa.Column("suggested_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("contributing_features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("feature_values", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["model_id"], ["prediction_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_prediction_scores_model_id", "prediction_scores", ["model_id"])
    op.create_index("ix_prediction_scores_user_id", "prediction_scores", ["user_id"])


def downgrade() -> None:
    op.drop_table("prediction_scores")
    op.drop_table("prediction_models")
