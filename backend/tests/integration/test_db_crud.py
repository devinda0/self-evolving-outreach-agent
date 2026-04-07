"""Integration tests for the MongoDB CRUD layer.

These tests require a running MongoDB instance (local Docker or Atlas).
Run with: pytest -m integration
"""

import pytest

from app.db.client import close_db, connect_db, get_db
from app.db.crud import (
    cache_tool_result,
    create_indexes,
    get_cached_tool_result,
    get_deployment_by_provider_message_id,
    get_top_findings,
    get_variants_for_session,
    load_campaign_state,
    save_campaign_state,
    save_content_variant,
    save_deployment_record,
    save_feedback_event,
    save_quarantine_event,
    save_research_finding,
)

TEST_DB = "signal_to_action_test"


@pytest.fixture(autouse=True)
async def _setup_teardown():
    """Connect to a dedicated test database, run indexes, and drop it after each test."""
    from app.core.config import settings

    settings.DB_NAME = TEST_DB
    await connect_db()
    await create_indexes()
    yield
    db = get_db()
    await db.client.drop_database(TEST_DB)
    await close_db()


# ---------------------------------------------------------------------------
# Campaign state round-trip
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_campaign_state_round_trip():
    state = {
        "session_id": "sess-int-001",
        "product_name": "TestProd",
        "product_description": "A test product",
        "target_market": "Developers",
        "cycle_number": 1,
        "session_complete": False,
        "research_findings": [],
        "error_messages": [],
    }

    await save_campaign_state("sess-int-001", state)
    loaded = await load_campaign_state("sess-int-001")

    assert loaded is not None
    assert loaded["session_id"] == "sess-int-001"
    assert loaded["product_name"] == "TestProd"
    assert loaded["cycle_number"] == 1


@pytest.mark.integration
async def test_campaign_state_upsert():
    state = {"session_id": "sess-int-002", "product_name": "V1", "cycle_number": 1}
    await save_campaign_state("sess-int-002", state)

    state["product_name"] = "V2"
    state["cycle_number"] = 2
    await save_campaign_state("sess-int-002", state)

    loaded = await load_campaign_state("sess-int-002")
    assert loaded is not None
    assert loaded["product_name"] == "V2"
    assert loaded["cycle_number"] == 2


@pytest.mark.integration
async def test_load_nonexistent_session():
    loaded = await load_campaign_state("does-not-exist")
    assert loaded is None


# ---------------------------------------------------------------------------
# Research findings
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_save_and_get_top_findings():
    findings = [
        {"session_id": "sess-rf", "confidence": 0.9, "claim": "High conf"},
        {"session_id": "sess-rf", "confidence": 0.3, "claim": "Low conf"},
        {"session_id": "sess-rf", "confidence": 0.7, "claim": "Mid conf"},
    ]
    for f in findings:
        await save_research_finding(f)

    top = await get_top_findings("sess-rf", k=2)
    assert len(top) == 2
    assert top[0]["confidence"] == 0.9
    assert top[1]["confidence"] == 0.7


@pytest.mark.integration
async def test_get_top_findings_with_min_confidence():
    findings = [
        {"session_id": "sess-rf2", "confidence": 0.8, "claim": "Above"},
        {"session_id": "sess-rf2", "confidence": 0.2, "claim": "Below"},
    ]
    for f in findings:
        await save_research_finding(f)

    top = await get_top_findings("sess-rf2", k=10, min_confidence=0.5)
    assert len(top) == 1
    assert top[0]["claim"] == "Above"


# ---------------------------------------------------------------------------
# Content variants
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_save_and_get_variants():
    variant = {"session_id": "sess-cv", "variant_id": "v1", "body": "Hello"}
    await save_content_variant(variant)

    variants = await get_variants_for_session("sess-cv")
    assert len(variants) == 1
    assert variants[0]["body"] == "Hello"


# ---------------------------------------------------------------------------
# Deployment records
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_save_and_lookup_deployment_record():
    record = {
        "session_id": "sess-dr",
        "variant_id": "v1",
        "provider_message_id": "pm-123",
        "channel": "email",
    }
    await save_deployment_record(record)

    found = await get_deployment_by_provider_message_id("pm-123")
    assert found is not None
    assert found["variant_id"] == "v1"

    not_found = await get_deployment_by_provider_message_id("pm-999")
    assert not_found is None


# ---------------------------------------------------------------------------
# Feedback and quarantine
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_save_feedback_event():
    event = {
        "session_id": "sess-fb",
        "event_type": "open",
        "dedupe_key": "dk-001",
    }
    await save_feedback_event(event)
    # Verify via direct query (no read function defined — just ensure no error)
    db = get_db()
    doc = await db["feedback_events"].find_one({"dedupe_key": "dk-001"})
    assert doc is not None


@pytest.mark.integration
async def test_save_quarantine_event():
    event = {"reason": "unmatched", "raw_payload": {"foo": "bar"}}
    await save_quarantine_event(event)
    db = get_db()
    doc = await db["quarantine_events"].find_one({"reason": "unmatched"})
    assert doc is not None


# ---------------------------------------------------------------------------
# Tool cache
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_cache_tool_result_and_retrieve():
    await cache_tool_result("search:acme", {"results": [1, 2, 3]}, ttl_seconds=3600)
    cached = await get_cached_tool_result("search:acme")
    assert cached == {"results": [1, 2, 3]}


@pytest.mark.integration
async def test_cache_miss_returns_none():
    result = await get_cached_tool_result("nonexistent-key")
    assert result is None


@pytest.mark.integration
async def test_cache_upsert_overwrites():
    await cache_tool_result("key-x", "old", ttl_seconds=3600)
    await cache_tool_result("key-x", "new", ttl_seconds=3600)
    cached = await get_cached_tool_result("key-x")
    assert cached == "new"
