"""Add listing metadata columns to companies table.

Adds is_adr, exchange_short, isin, and market_cap_usd for ADR filtering
and issuer-level deduplication (PRD 9.8).

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("is_adr", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("exchange_short", sa.String(20), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("isin", sa.String(12), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("market_cap_usd", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("companies", "market_cap_usd")
    op.drop_column("companies", "isin")
    op.drop_column("companies", "exchange_short")
    op.drop_column("companies", "is_adr")
