"""spatial and perf indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25 16:53:35.291259

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('alerts_axis', 'alerts', ['watchlist_id', 'axis', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('alerts_feed', 'alerts', ['watchlist_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('alerts_materiality', 'alerts', ['watchlist_id', sa.literal_column('materiality_score DESC')], unique=False)
    op.create_index('events_geom_gist', 'events', ['geometry'], unique=False, postgresql_using='gist')
    op.create_index('events_ingested_at_brin', 'events', ['ingested_at'], unique=False, postgresql_using='brin')
    op.create_index('events_source_type', 'events', ['source', 'event_type'], unique=False)
    op.create_index('parcels_centroid_gist', 'parcels', ['centroid'], unique=False, postgresql_using='gist')
    op.create_index('parcels_geom_gist', 'parcels', ['geom'], unique=False, postgresql_using='gist')


def downgrade() -> None:
    op.drop_index('parcels_geom_gist', table_name='parcels', postgresql_using='gist')
    op.drop_index('parcels_centroid_gist', table_name='parcels', postgresql_using='gist')
    op.drop_index('events_source_type', table_name='events')
    op.drop_index('events_ingested_at_brin', table_name='events', postgresql_using='brin')
    op.drop_index('events_geom_gist', table_name='events', postgresql_using='gist')
    op.drop_index('alerts_materiality', table_name='alerts')
    op.drop_index('alerts_feed', table_name='alerts')
    op.drop_index('alerts_axis', table_name='alerts')
