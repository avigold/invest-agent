"""m3: industry module tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- industries --
    op.create_table(
        "industries",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("gics_code", sa.String(3), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gics_code"),
    )

    # -- industry_scores --
    op.create_table(
        "industry_scores",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("industry_id", sa.Uuid(), nullable=False),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("calc_version", sa.String(50), nullable=False),
        sa.Column("rubric_score", sa.Numeric(), nullable=False),
        sa.Column("overall_score", sa.Numeric(), nullable=False),
        sa.Column("component_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("point_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["industry_id"], ["industries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("industry_id", "country_id", "as_of", "calc_version", name="uq_industry_score_version"),
    )
    op.create_index("ix_industry_scores_as_of", "industry_scores", ["as_of"])

    # -- industry_risk_register --
    op.create_table(
        "industry_risk_register",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("industry_id", sa.Uuid(), nullable=False),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("risk_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("detected_at", sa.Date(), nullable=False),
        sa.Column("resolved_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["industry_id"], ["industries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("industry_risk_register")
    op.drop_index("ix_industry_scores_as_of", table_name="industry_scores")
    op.drop_table("industry_scores")
    op.drop_table("industries")
