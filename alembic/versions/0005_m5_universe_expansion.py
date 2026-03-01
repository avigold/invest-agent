"""m5: make company cik nullable for international companies

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make cik nullable for international companies (no SEC CIK)
    op.alter_column("companies", "cik", existing_type=sa.String(10), nullable=True)

    # Drop the full unique constraint on cik
    op.drop_constraint("companies_cik_key", "companies", type_="unique")

    # Add partial unique index: cik must be unique when not null (US companies)
    op.execute(
        "CREATE UNIQUE INDEX uq_companies_cik_not_null ON companies (cik) WHERE cik IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_companies_cik_not_null")

    # Delete any rows with null cik before restoring NOT NULL
    op.execute("DELETE FROM companies WHERE cik IS NULL")

    op.create_unique_constraint("companies_cik_key", "companies", ["cik"])
    op.alter_column("companies", "cik", existing_type=sa.String(10), nullable=False)
