"""m2: country module tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- data_sources --
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("requires_auth", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # -- artefacts --
    op.create_table(
        "artefacts",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("fetch_params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("time_window_start", sa.Date(), nullable=True),
        sa.Column("time_window_end", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_uri", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.UniqueConstraint("data_source_id", "content_hash", name="uq_artefact_source_hash"),
    )
    op.create_index("ix_artefacts_content_hash", "artefacts", ["content_hash"])

    # -- countries --
    op.create_table(
        "countries",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("iso2", sa.String(2), nullable=False),
        sa.Column("iso3", sa.String(3), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("equity_index_symbol", sa.String(20), nullable=False, server_default=""),
        sa.Column("config_version", sa.String(50), nullable=False, server_default="v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("iso2"),
        sa.UniqueConstraint("iso3"),
    )

    # -- country_series --
    op.create_table(
        "country_series",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("series_name", sa.String(100), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("indicator_code", sa.String(100), nullable=False, server_default=""),
        sa.Column("unit", sa.String(50), nullable=False, server_default=""),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="annual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("country_id", "series_name", name="uq_country_series_name"),
    )

    # -- country_series_points --
    op.create_table(
        "country_series_points",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("artefact_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["series_id"], ["country_series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artefact_id"], ["artefacts.id"]),
        sa.UniqueConstraint("series_id", "date", name="uq_series_point_date"),
    )
    op.create_index("ix_series_points_series_date", "country_series_points", ["series_id", "date"])

    # -- country_scores --
    op.create_table(
        "country_scores",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("calc_version", sa.String(50), nullable=False),
        sa.Column("macro_score", sa.Numeric(), nullable=False),
        sa.Column("market_score", sa.Numeric(), nullable=False),
        sa.Column("stability_score", sa.Numeric(), nullable=False),
        sa.Column("overall_score", sa.Numeric(), nullable=False),
        sa.Column("component_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("point_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("country_id", "as_of", "calc_version", name="uq_country_score_version"),
    )
    op.create_index("ix_country_scores_as_of", "country_scores", ["as_of"])

    # -- country_risk_register --
    op.create_table(
        "country_risk_register",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("risk_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("detected_at", sa.Date(), nullable=False),
        sa.Column("resolved_at", sa.Date(), nullable=True),
        sa.Column("artefact_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artefact_id"], ["artefacts.id"]),
    )

    # -- decision_packets --
    op.create_table(
        "decision_packets",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("packet_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("summary_version", sa.String(50), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("score_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("packet_type", "entity_id", "as_of", "summary_version", name="uq_packet_entity_version"),
    )
    op.create_index("ix_packets_entity", "decision_packets", ["packet_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_packets_entity", table_name="decision_packets")
    op.drop_table("decision_packets")
    op.drop_table("country_risk_register")
    op.drop_index("ix_country_scores_as_of", table_name="country_scores")
    op.drop_table("country_scores")
    op.drop_index("ix_series_points_series_date", table_name="country_series_points")
    op.drop_table("country_series_points")
    op.drop_table("country_series")
    op.drop_table("countries")
    op.drop_index("ix_artefacts_content_hash", table_name="artefacts")
    op.drop_table("artefacts")
    op.drop_table("data_sources")
