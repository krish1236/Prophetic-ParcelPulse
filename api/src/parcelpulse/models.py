from datetime import datetime
from decimal import Decimal
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811  alias avoids clash with stdlib uuid.UUID
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    geometry = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_sig: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", "payload_hash", name="events_dedup_key"
        ),
        Index("events_geom_gist", "geometry", postgresql_using="gist"),
        Index("events_ingested_at_brin", "ingested_at", postgresql_using="brin"),
        Index("events_source_type", "source", "event_type"),
    )


class Parcel(Base):
    __tablename__ = "parcels"

    parcel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    county_fips: Mapped[str] = mapped_column(Text, nullable=False)
    apn: Mapped[str] = mapped_column(Text, nullable=False)
    geom = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    centroid = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_event_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.event_id"), nullable=True
    )
    last_projected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("county_fips", "apn", name="parcels_county_apn_key"),
        Index("parcels_geom_gist", "geom", postgresql_using="gist"),
        Index("parcels_centroid_gist", "centroid", postgresql_using="gist"),
    )


class Watchlist(Base):
    __tablename__ = "watchlists"

    watchlist_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    deal_thesis: Mapped[str] = mapped_column(Text, nullable=False)
    thesis_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WatchedParcel(Base):
    __tablename__ = "watched_parcels"

    watchlist_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("watchlists.watchlist_id", ondelete="CASCADE"),
        primary_key=True,
    )
    parcel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("parcels.parcel_id"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Alert(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    watchlist_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("watchlists.watchlist_id"), nullable=False
    )
    parcel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("parcels.parcel_id"), nullable=False
    )
    triggering_event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.event_id"), nullable=False
    )
    axis: Mapped[str] = mapped_column(Text, nullable=False)
    materiality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    decision_trace: Mapped[dict] = mapped_column(JSONB, nullable=False)
    classifier_tier: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "materiality_score BETWEEN 0 AND 100",
            name="alerts_materiality_score_range",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 1", name="alerts_confidence_range"
        ),
        UniqueConstraint(
            "watchlist_id", "dedupe_key", name="alerts_watchlist_dedupe_key"
        ),
        Index("alerts_feed", "watchlist_id", text("created_at DESC")),
        Index("alerts_axis", "watchlist_id", "axis", text("created_at DESC")),
        Index(
            "alerts_materiality",
            "watchlist_id",
            text("materiality_score DESC"),
        ),
    )


class ClassifierCache(Base):
    __tablename__ = "classifier_cache"

    cache_key: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReplayRun(Base):
    __tablename__ = "replay_runs"

    run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    watchlist_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("watchlists.watchlist_id"), nullable=False
    )
    from_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_hit_pct: Mapped[float] = mapped_column(Float, nullable=False)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
