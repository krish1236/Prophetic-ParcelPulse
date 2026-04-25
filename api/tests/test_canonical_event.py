from datetime import UTC, datetime

from parcelpulse.adapters.base import CanonicalEvent


def _event(payload: dict) -> CanonicalEvent:
    return CanonicalEvent(
        source="test_source",
        external_id="abc123",
        event_type="test.event",
        payload=payload,
        geometry=None,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_payload_hash_is_deterministic():
    a = _event({"x": 1, "y": 2}).payload_hash()
    b = _event({"x": 1, "y": 2}).payload_hash()
    assert a == b
    assert len(a) == 32  # sha256


def test_payload_hash_is_invariant_under_key_order():
    a = _event({"x": 1, "y": 2}).payload_hash()
    b = _event({"y": 2, "x": 1}).payload_hash()
    assert a == b


def test_payload_hash_changes_when_payload_changes():
    a = _event({"x": 1, "y": 2}).payload_hash()
    b = _event({"x": 1, "y": 3}).payload_hash()
    assert a != b


def test_canonical_event_rejects_extra_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CanonicalEvent(
            source="s",
            external_id="x",
            event_type="t",
            payload={},
            geometry=None,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            unexpected_field="boom",  # type: ignore[call-arg]
        )
