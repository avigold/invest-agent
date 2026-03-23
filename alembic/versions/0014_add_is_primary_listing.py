"""Add is_primary_listing to companies for ISIN-based deduplication.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("is_primary_listing", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_companies_is_primary_listing", "companies", ["is_primary_listing"])


def downgrade() -> None:
    op.drop_index("ix_companies_is_primary_listing", table_name="companies")
    op.drop_column("companies", "is_primary_listing")
