"""init

Revision ID: 0001
Revises: 
Create Date: 2026-04-25 16:45:41.814746

"""
from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table('classifier_cache',
    sa.Column('cache_key', sa.LargeBinary(), nullable=False),
    sa.Column('tier', sa.Text(), nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('cache_key')
    )
    op.create_table('events',
    sa.Column('event_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=False),
    sa.Column('payload_hash', sa.LargeBinary(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('geometry', geoalchemy2.types.Geometry(srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_sig', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('event_id'),
    sa.UniqueConstraint('source', 'external_id', 'payload_hash', name='events_dedup_key')
    )
    op.create_table('watchlists',
    sa.Column('watchlist_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('deal_thesis', sa.Text(), nullable=False),
    sa.Column('thesis_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('watchlist_id')
    )
    op.create_table('parcels',
    sa.Column('parcel_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('county_fips', sa.Text(), nullable=False),
    sa.Column('apn', sa.Text(), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('centroid', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('attrs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('last_event_id', sa.UUID(), nullable=True),
    sa.Column('last_projected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['last_event_id'], ['events.event_id'], ),
    sa.PrimaryKeyConstraint('parcel_id'),
    sa.UniqueConstraint('county_fips', 'apn', name='parcels_county_apn_key')
    )
    op.create_table('replay_runs',
    sa.Column('run_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('watchlist_id', sa.UUID(), nullable=False),
    sa.Column('from_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('to_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('alert_count', sa.Integer(), nullable=False),
    sa.Column('cache_hit_pct', sa.Float(), nullable=False),
    sa.Column('ran_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['watchlist_id'], ['watchlists.watchlist_id'], ),
    sa.PrimaryKeyConstraint('run_id')
    )
    op.create_table('alerts',
    sa.Column('alert_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('watchlist_id', sa.UUID(), nullable=False),
    sa.Column('parcel_id', sa.UUID(), nullable=False),
    sa.Column('triggering_event_id', sa.UUID(), nullable=False),
    sa.Column('axis', sa.Text(), nullable=False),
    sa.Column('materiality_score', sa.Integer(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('decision_trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('classifier_tier', sa.Text(), nullable=False),
    sa.Column('dedupe_key', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='alerts_confidence_range'),
    sa.CheckConstraint('materiality_score BETWEEN 0 AND 100', name='alerts_materiality_score_range'),
    sa.ForeignKeyConstraint(['parcel_id'], ['parcels.parcel_id'], ),
    sa.ForeignKeyConstraint(['triggering_event_id'], ['events.event_id'], ),
    sa.ForeignKeyConstraint(['watchlist_id'], ['watchlists.watchlist_id'], ),
    sa.PrimaryKeyConstraint('alert_id'),
    sa.UniqueConstraint('watchlist_id', 'dedupe_key', name='alerts_watchlist_dedupe_key')
    )
    op.create_table('watched_parcels',
    sa.Column('watchlist_id', sa.UUID(), nullable=False),
    sa.Column('parcel_id', sa.UUID(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['parcel_id'], ['parcels.parcel_id'], ),
    sa.ForeignKeyConstraint(['watchlist_id'], ['watchlists.watchlist_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('watchlist_id', 'parcel_id')
    )


def downgrade() -> None:
    op.drop_table('watched_parcels')
    op.drop_table('alerts')
    op.drop_table('replay_runs')
    op.drop_table('parcels')
    op.drop_table('watchlists')
    op.drop_table('events')
    op.drop_table('classifier_cache')
    # Extensions intentionally left in place — they may be in use by other schemas.
