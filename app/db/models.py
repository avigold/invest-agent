from __future__ import annotations

import uuid
from datetime import datetime, timezone

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    subscription: Mapped[Subscription | None] = relationship(back_populates="user", uselist=False)
    jobs: Mapped[list[Job]] = relationship(back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="subscription")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_id", "user_id"),
        Index("ix_jobs_queued_at", "queued_at"),
        Index("ix_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    command: Mapped[str] = mapped_column(String(100), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_text: Mapped[str | None] = mapped_column(Text)
    artefact_ids: Mapped[list | None] = mapped_column(JSONB)
    packet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    user: Mapped[User] = relationship(back_populates="jobs")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    requires_auth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    artefacts: Mapped[list[Artefact]] = relationship(back_populates="data_source")


class Artefact(Base):
    __tablename__ = "artefacts"
    __table_args__ = (
        UniqueConstraint("data_source_id", "content_hash", name="uq_artefact_source_hash"),
        Index("ix_artefacts_content_hash", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("data_sources.id"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    fetch_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    time_window_start: Mapped[date_type | None] = mapped_column(Date)
    time_window_end: Mapped[date_type | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    data_source: Mapped[DataSource] = relationship(back_populates="artefacts")


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    equity_index_symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    config_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    series: Mapped[list[CountrySeries]] = relationship(back_populates="country")
    scores: Mapped[list[CountryScore]] = relationship(back_populates="country")
    risks: Mapped[list[CountryRiskRegister]] = relationship(back_populates="country")


class CountrySeries(Base):
    __tablename__ = "country_series"
    __table_args__ = (
        UniqueConstraint("country_id", "series_name", name="uq_country_series_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    country_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
    series_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="annual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    country: Mapped[Country] = relationship(back_populates="series")
    points: Mapped[list[CountrySeriesPoint]] = relationship(back_populates="series")


class CountrySeriesPoint(Base):
    __tablename__ = "country_series_points"
    __table_args__ = (
        UniqueConstraint("series_id", "date", name="uq_series_point_date"),
        Index("ix_series_points_series_date", "series_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    series_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("country_series.id", ondelete="CASCADE"), nullable=False)
    artefact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artefacts.id"), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    series: Mapped[CountrySeries] = relationship(back_populates="points")


class CountryScore(Base):
    __tablename__ = "country_scores"
    __table_args__ = (
        UniqueConstraint("country_id", "as_of", "calc_version", name="uq_country_score_version"),
        Index("ix_country_scores_as_of", "as_of"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    country_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
    as_of: Mapped[date_type] = mapped_column(Date, nullable=False)
    calc_version: Mapped[str] = mapped_column(String(50), nullable=False)
    macro_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    market_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    stability_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    component_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    point_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    country: Mapped[Country] = relationship(back_populates="scores")


class CountryRiskRegister(Base):
    __tablename__ = "country_risk_register"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    country_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detected_at: Mapped[date_type] = mapped_column(Date, nullable=False)
    resolved_at: Mapped[date_type | None] = mapped_column(Date)
    artefact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("artefacts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    country: Mapped[Country] = relationship(back_populates="risks")


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    gics_code: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    scores: Mapped[list[IndustryScore]] = relationship(back_populates="industry")
    risks: Mapped[list[IndustryRiskRegister]] = relationship(back_populates="industry")


class IndustryScore(Base):
    __tablename__ = "industry_scores"
    __table_args__ = (
        UniqueConstraint("industry_id", "country_id", "as_of", "calc_version", name="uq_industry_score_version"),
        Index("ix_industry_scores_as_of", "as_of"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    industry_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("industries.id", ondelete="CASCADE"), nullable=False)
    country_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
    as_of: Mapped[date_type] = mapped_column(Date, nullable=False)
    calc_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rubric_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    component_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    point_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    industry: Mapped[Industry] = relationship(back_populates="scores")
    country: Mapped[Country] = relationship()


class IndustryRiskRegister(Base):
    __tablename__ = "industry_risk_register"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    industry_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("industries.id", ondelete="CASCADE"), nullable=False)
    country_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detected_at: Mapped[date_type] = mapped_column(Date, nullable=False)
    resolved_at: Mapped[date_type | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    industry: Mapped[Industry] = relationship(back_populates="risks")
    country: Mapped[Country] = relationship()


class DecisionPacket(Base):
    __tablename__ = "decision_packets"
    __table_args__ = (
        UniqueConstraint("packet_type", "entity_id", "as_of", "summary_version", name="uq_packet_entity_version"),
        Index("ix_packets_entity", "packet_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    packet_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    as_of: Mapped[date_type] = mapped_column(Date, nullable=False)
    summary_version: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    score_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
