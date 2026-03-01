"""m4: company module tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- companies --
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("gics_code", sa.String(3), nullable=False, server_default=""),
        sa.Column("country_iso2", sa.String(2), nullable=False, server_default="US"),
        sa.Column("config_version", sa.String(50), nullable=False, server_default="v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
        sa.UniqueConstraint("cik"),
    )

    # -- company_series --
    op.create_table(
        "company_series",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("series_name", sa.String(100), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("indicator_code", sa.String(100), nullable=False, server_default=""),
        sa.Column("unit", sa.String(50), nullable=False, server_default=""),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="annual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "series_name", name="uq_company_series_name"),
    )

    # -- company_series_points --
    op.create_table(
        "company_series_points",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("artefact_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["series_id"], ["company_series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artefact_id"], ["artefacts.id"]),
        sa.UniqueConstraint("series_id", "date", name="uq_company_series_point_date"),
    )
    op.create_index("ix_company_series_points_series_date", "company_series_points", ["series_id", "date"])

    # -- company_scores --
    op.create_table(
        "company_scores",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("calc_version", sa.String(50), nullable=False),
        sa.Column("fundamental_score", sa.Numeric(), nullable=False),
        sa.Column("market_score", sa.Numeric(), nullable=False),
        sa.Column("industry_context_score", sa.Numeric(), nullable=False),
        sa.Column("overall_score", sa.Numeric(), nullable=False),
        sa.Column("component_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("point_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "as_of", "calc_version", name="uq_company_score_version"),
    )
    op.create_index("ix_company_scores_as_of", "company_scores", ["as_of"])

    # -- company_risk_register --
    op.create_table(
        "company_risk_register",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("risk_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("detected_at", sa.Date(), nullable=False),
        sa.Column("resolved_at", sa.Date(), nullable=True),
        sa.Column("artefact_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artefact_id"], ["artefacts.id"]),
    )


def downgrade() -> None:
    op.drop_table("company_risk_register")
    op.drop_index("ix_company_scores_as_of", table_name="company_scores")
    op.drop_table("company_scores")
    op.drop_index("ix_company_series_points_series_date", table_name="company_series_points")
    op.drop_table("company_series_points")
    op.drop_table("company_series")
    op.drop_table("companies")
