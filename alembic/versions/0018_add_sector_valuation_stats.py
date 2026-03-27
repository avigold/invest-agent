"""Add sector_valuation_stats table for precomputed sector percentiles.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.create_table(
        "sector_valuation_stats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gics_code", sa.String(2), nullable=False),
        sa.Column("sector_name", sa.String(100), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("calc_version", sa.String(50), nullable=False),
        sa.Column("company_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metrics",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gics_code", "as_of", "calc_version",
            name="uq_sector_valuation_version",
        ),
    )
    op.create_index(
        "ix_sector_valuation_as_of", "sector_valuation_stats", ["as_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_sector_valuation_as_of", table_name="sector_valuation_stats")
    op.drop_table("sector_valuation_stats")
