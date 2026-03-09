"""Add nickname and is_active columns to prediction_models.

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prediction_models",
        sa.Column("nickname", sa.String(100), nullable=True),
    )
    op.add_column(
        "prediction_models",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Partial unique index: only one active model per user
    op.create_index(
        "ix_prediction_models_user_active",
        "prediction_models",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_prediction_models_user_active", table_name="prediction_models")
    op.drop_column("prediction_models", "is_active")
    op.drop_column("prediction_models", "nickname")
