"""Add country and sector columns to prediction_scores.

Revision ID: 0011
Revises: da0a16e54359
Create Date: 2026-03-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "da0a16e54359"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("prediction_scores", sa.Column("country", sa.String(10), nullable=True))
    op.add_column("prediction_scores", sa.Column("sector", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("prediction_scores", "sector")
    op.drop_column("prediction_scores", "country")
