"""Idempotent bulk insert path for canonical events.

Every adapter — scheduled, webhook, fixture — funnels into `insert_events()`.
Dedupe is enforced at the DB layer via the UNIQUE (source, external_id, payload_hash)
constraint and `ON CONFLICT DO NOTHING`. The function returns the number of rows
*actually* inserted, so callers can log and surface ingest growth.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from parcelpulse.adapters.base import CanonicalEvent
from parcelpulse.db import SessionLocal

_INSERT_SQL = text("""
    INSERT INTO events
        (source, external_id, payload_hash, event_type, payload, geometry, occurred_at)
    SELECT
        row.source,
        row.external_id,
        decode(row.payload_hash_hex, 'hex'),
        row.event_type,
        row.payload,
        CASE
            WHEN row.geometry IS NOT NULL
            THEN ST_SetSRID(ST_GeomFromGeoJSON(row.geometry), 4326)
        END,
        row.occurred_at
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS row(
        source           TEXT,
        external_id      TEXT,
        payload_hash_hex TEXT,
        event_type       TEXT,
        payload          JSONB,
        geometry         TEXT,
        occurred_at      TIMESTAMPTZ
    )
    ON CONFLICT (source, external_id, payload_hash) DO NOTHING
    RETURNING event_id
""")


async def insert_events(events: Sequence[CanonicalEvent]) -> int:
    if not events:
        return 0
    rows = [
        {
            "source": e.source,
            "external_id": e.external_id,
            "payload_hash_hex": e.payload_hash().hex(),
            "event_type": e.event_type,
            "payload": e.payload,
            "geometry": json.dumps(e.geometry) if e.geometry else None,
            "occurred_at": e.occurred_at.isoformat(),
        }
        for e in events
    ]
    async with SessionLocal() as session:
        result = await session.execute(_INSERT_SQL, {"rows": json.dumps(rows)})
        await session.commit()
        return len(result.fetchall())
