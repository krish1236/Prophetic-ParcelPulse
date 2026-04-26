"""Single source of truth for the set of registered source adapters.

Both the scheduler (which schedules pulls) and the /health endpoint (which
reports per-source ingestion lag) consult this list so they can never drift.
"""

from parcelpulse.adapters.base import SourceAdapter
from parcelpulse.adapters.fema_nfhl import FemaNfhlAdapter
from parcelpulse.adapters.fixture_zoning import FixtureZoningAdapter
from parcelpulse.adapters.multco_permits import MultcoPermitsAdapter


def all_adapters() -> list[SourceAdapter]:
    return [MultcoPermitsAdapter(), FemaNfhlAdapter(), FixtureZoningAdapter()]
