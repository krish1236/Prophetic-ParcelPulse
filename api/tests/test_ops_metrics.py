"""Tests for /admin/ops/metrics + token gating."""

import httpx

from parcelpulse.settings import settings


async def test_metrics_returns_sources_and_aggregates(http_client: httpx.AsyncClient):
    r = await http_client.get("/admin/ops/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "sources" in body and len(body["sources"]) > 0
    assert "ingest_by_day" in body
    assert "cost_by_day" in body
    assert body["cost_cap_usd"] == settings.daily_llm_cost_cap_usd
    assert "cost_today_usd" in body


async def test_metrics_ingest_by_day_groups_per_source(
    http_client: httpx.AsyncClient,
):
    # Confirm shape: each row is {day, source, events}
    r = await http_client.get("/admin/ops/metrics")
    rows = r.json()["ingest_by_day"]
    for row in rows:
        assert set(row.keys()) == {"day", "source", "events"}
        assert isinstance(row["events"], int) and row["events"] > 0


async def test_metrics_token_gate_when_configured(
    http_client: httpx.AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "ops_token", "SECRET")
    # Without header → 401
    r = await http_client.get("/admin/ops/metrics")
    assert r.status_code == 401
    # With wrong header → 401
    r = await http_client.get(
        "/admin/ops/metrics", headers={"x-ops-token": "wrong"}
    )
    assert r.status_code == 401
    # With correct header → 200
    r = await http_client.get(
        "/admin/ops/metrics", headers={"x-ops-token": "SECRET"}
    )
    assert r.status_code == 200


async def test_metrics_no_gate_when_token_unset(http_client: httpx.AsyncClient):
    # ops_token is "" by default; /admin/ops/* should be open in dev.
    r = await http_client.get("/admin/ops/metrics")
    assert r.status_code == 200
