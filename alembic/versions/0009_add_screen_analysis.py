"""Add analysis column to screen_results for AI pattern analysis.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("screen_results", sa.Column("analysis", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("screen_results", "analysis")
