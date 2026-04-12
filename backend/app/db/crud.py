"""Async CRUD operations for all MongoDB collections."""

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.db.client import get_db
from app.db.collections import (
    CAMPAIGN_SESSIONS,
    CONTENT_VARIANTS,
    CYCLE_RECORDS,
    DEAD_LETTER_QUEUE,
    DEPLOYMENT_RECORDS,
    FEEDBACK_EVENTS,
    INTELLIGENCE_ENTRIES,
    MCP_SERVERS,
    PROSPECT_CARDS,
    QUARANTINE,
    RESEARCH_FINDINGS,
    SEGMENTS,
    TOOL_CACHE,
)

# ---------------------------------------------------------------------------
# Campaign sessions
# ---------------------------------------------------------------------------


async def save_campaign_state(session_id: str, state: dict[str, Any]) -> None:
    """Upsert the full campaign state for a session."""
    db = get_db()
    await db[CAMPAIGN_SESSIONS].find_one_and_update(
        {"session_id": session_id},
        {"$set": {**state, "session_id": session_id, "updated_at": _now()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def load_campaign_state(session_id: str) -> dict[str, Any] | None:
    """Load the campaign state for a session. Returns None if not found."""
    db = get_db()
    doc = await db[CAMPAIGN_SESSIONS].find_one({"session_id": session_id})
    if doc is not None:
        doc.pop("_id", None)
    return doc


async def list_campaigns(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent campaigns with summary fields, ordered by updated_at desc."""
    db = get_db()
    cursor = (
        db[CAMPAIGN_SESSIONS]
        .find(
            {},
            {
                "_id": 0,
                "session_id": 1,
                "product_name": 1,
                "target_market": 1,
                "current_intent": 1,
                "cycle_number": 1,
                "updated_at": 1,
            },
        )
        .sort("updated_at", DESCENDING)
        .limit(limit)
    )
    results = []
    async for doc in cursor:
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Research findings
# ---------------------------------------------------------------------------


async def save_research_finding(finding: dict[str, Any]) -> None:
    """Insert a single research finding.

    Uses a shallow copy to prevent ``insert_one`` from mutating the caller's
    dict with a BSON ``_id`` field.
    """
    db = get_db()
    await db[RESEARCH_FINDINGS].insert_one({**finding})


async def get_top_findings(
    session_id: str,
    k: int = 5,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """Return the top-k findings for a session, sorted by confidence descending."""
    db = get_db()
    cursor = (
        db[RESEARCH_FINDINGS]
        .find({"session_id": session_id, "confidence": {"$gte": min_confidence}})
        .sort("confidence", DESCENDING)
        .limit(k)
    )
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


async def update_finding_confidence(finding_id: str, delta: float) -> None:
    """Increment the confidence score for a finding by delta, clamped to [0.0, 1.0]."""
    db = get_db()
    # Use $min/$max after $inc to clamp the result within [0.0, 1.0]
    await db[RESEARCH_FINDINGS].find_one_and_update(
        {"id": finding_id},
        [
            {
                "$set": {
                    "confidence": {
                        "$min": [
                            1.0,
                            {"$max": [0.0, {"$add": ["$confidence", delta]}]},
                        ]
                    }
                }
            }
        ],
    )


# ---------------------------------------------------------------------------
# Content variants
# ---------------------------------------------------------------------------


async def save_content_variant(variant: dict[str, Any]) -> None:
    """Insert a single content variant."""
    db = get_db()
    await db[CONTENT_VARIANTS].insert_one(variant)


async def get_variants_for_session(session_id: str) -> list[dict[str, Any]]:
    """Return all content variants for a session."""
    db = get_db()
    cursor = db[CONTENT_VARIANTS].find({"session_id": session_id})
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Deployment records
# ---------------------------------------------------------------------------


async def save_deployment_record(record: dict[str, Any]) -> None:
    """Insert a single deployment record."""
    db = get_db()
    await db[DEPLOYMENT_RECORDS].insert_one(record)


async def get_deployment_by_provider_message_id(
    provider_message_id: str,
) -> dict[str, Any] | None:
    """Look up a deployment record by its provider-assigned message ID (for webhook correlation)."""
    db = get_db()
    doc = await db[DEPLOYMENT_RECORDS].find_one({"provider_message_id": provider_message_id})
    if doc is not None:
        doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Feedback events
# ---------------------------------------------------------------------------


async def save_feedback_event(event: dict[str, Any]) -> None:
    """Insert a normalized feedback event."""
    db = get_db()
    await db[FEEDBACK_EVENTS].insert_one({**event})


async def get_feedback_event_by_dedupe_key(dedupe_key: str) -> dict[str, Any] | None:
    """Look up a feedback event by its deduplication key."""
    db = get_db()
    doc = await db[FEEDBACK_EVENTS].find_one({"dedupe_key": dedupe_key})
    if doc is not None:
        doc.pop("_id", None)
    return doc


async def get_feedback_events_for_session(session_id: str) -> list[dict[str, Any]]:
    """Return all normalized feedback events for a session, ordered by received_at."""
    db = get_db()
    cursor = db[FEEDBACK_EVENTS].find({"session_id": session_id}).sort("received_at", ASCENDING)
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


async def save_quarantine_event(event: dict[str, Any]) -> None:
    """Insert an unmatched/quarantined event."""
    db = get_db()
    await db[QUARANTINE].insert_one({**event})


async def get_quarantine_events_for_session(session_id: str) -> list[dict[str, Any]]:
    """Return all quarantined events for a session, ordered by received_at ascending."""
    db = get_db()
    cursor = db[QUARANTINE].find({"session_id": session_id}).sort("received_at", ASCENDING)
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Dead-letter queue
# ---------------------------------------------------------------------------


async def save_dlq_event(event: dict[str, Any]) -> None:
    """Insert a failed webhook event into the dead-letter queue."""
    db = get_db()
    await db[DEAD_LETTER_QUEUE].insert_one({**event})


async def get_dlq_events(
    status: str = "pending",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return DLQ events filtered by status, ordered by created_at ascending."""
    db = get_db()
    cursor = (
        db[DEAD_LETTER_QUEUE]
        .find({"status": status})
        .sort("created_at", ASCENDING)
        .limit(limit)
    )
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


async def update_dlq_event(
    dedupe_key: str,
    update: dict[str, Any],
) -> None:
    """Update a DLQ event by dedupe_key (e.g. increment retry_count, set status)."""
    db = get_db()
    await db[DEAD_LETTER_QUEUE].update_one(
        {"dedupe_key": dedupe_key},
        {"$set": update},
    )


# ---------------------------------------------------------------------------
# Engagement dashboard queries
# ---------------------------------------------------------------------------


async def get_deployment_records_for_session(session_id: str) -> list[dict[str, Any]]:
    """Return all deployment records for a session."""
    db = get_db()
    cursor = db[DEPLOYMENT_RECORDS].find({"session_id": session_id}).sort("sent_at", ASCENDING)
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Intelligence entries
# ---------------------------------------------------------------------------


async def save_intelligence_entry(entry: dict[str, Any]) -> None:
    """Insert a learning delta / intelligence entry."""
    db = get_db()
    await db[INTELLIGENCE_ENTRIES].insert_one({**entry})


async def get_intelligence_entries(session_id: str) -> list[dict[str, Any]]:
    """Return all intelligence entries for a session, ordered by cycle_number."""
    db = get_db()
    cursor = (
        db[INTELLIGENCE_ENTRIES].find({"session_id": session_id}).sort("cycle_number", ASCENDING)
    )
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


async def save_segments(session_id: str, segments: list[dict[str, Any]]) -> None:
    """Replace all segments for a session."""
    db = get_db()
    await db[SEGMENTS].delete_many({"session_id": session_id})
    if segments:
        for seg in segments:
            seg["session_id"] = session_id
        await db[SEGMENTS].insert_many(segments)


async def get_segments(session_id: str) -> list[dict[str, Any]]:
    """Return all segments for a session."""
    db = get_db()
    cursor = db[SEGMENTS].find({"session_id": session_id})
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Prospect cards
# ---------------------------------------------------------------------------


async def save_prospect_cards(session_id: str, cards: list[dict[str, Any]]) -> None:
    """Replace all prospect cards for a session."""
    db = get_db()
    await db[PROSPECT_CARDS].delete_many({"session_id": session_id})
    if cards:
        for card in cards:
            card["session_id"] = session_id
        await db[PROSPECT_CARDS].insert_many(cards)


async def get_prospect_cards(session_id: str) -> list[dict[str, Any]]:
    """Return all scored prospect cards for a session, sorted by combined score desc."""
    db = get_db()
    cursor = (
        db[PROSPECT_CARDS]
        .find({"session_id": session_id})
        .sort([("fit_score", DESCENDING), ("urgency_score", DESCENDING)])
    )
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# Tool cache
# ---------------------------------------------------------------------------


async def cache_tool_result(key: str, value: Any, ttl_seconds: int) -> None:
    """Upsert a cached tool result with a TTL-based expiry."""
    db = get_db()
    expires_at = datetime.fromtimestamp(_now().timestamp() + ttl_seconds, tz=timezone.utc)
    await db[TOOL_CACHE].find_one_and_update(
        {"key": key},
        {"$set": {"key": key, "value": value, "expires_at": expires_at}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def get_cached_tool_result(key: str) -> Any | None:
    """Return a cached value if it exists and hasn't expired. Returns None otherwise."""
    db = get_db()
    doc = await db[TOOL_CACHE].find_one({"key": key, "expires_at": {"$gt": _now()}})
    if doc is not None:
        return doc.get("value")
    return None


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


async def create_indexes() -> None:
    """Create required indexes. Safe to call repeatedly — MongoDB is idempotent for this."""
    db = get_db()
    await db[CAMPAIGN_SESSIONS].create_index("session_id", unique=True)
    await db[RESEARCH_FINDINGS].create_index(
        [("session_id", ASCENDING), ("confidence", DESCENDING)]
    )
    await db[RESEARCH_FINDINGS].create_index("id")
    await db[DEPLOYMENT_RECORDS].create_index("provider_message_id")
    await db[FEEDBACK_EVENTS].create_index("dedupe_key", unique=True)
    await db[TOOL_CACHE].create_index("expires_at", expireAfterSeconds=0)
    await db[SEGMENTS].create_index("session_id")
    await db[PROSPECT_CARDS].create_index([("session_id", ASCENDING), ("fit_score", DESCENDING)])
    await db[INTELLIGENCE_ENTRIES].create_index(
        [("session_id", ASCENDING), ("cycle_number", ASCENDING)]
    )
    await db[QUARANTINE].create_index([("session_id", ASCENDING), ("received_at", ASCENDING)])
    await db[MCP_SERVERS].create_index("server_id", unique=True)
    await db[CYCLE_RECORDS].create_index(
        [("session_id", ASCENDING), ("cycle_number", ASCENDING)], unique=True
    )


# ---------------------------------------------------------------------------
# Cycle records
# ---------------------------------------------------------------------------


async def save_cycle_record(record: dict[str, Any]) -> None:
    """Insert a cycle snapshot. One record per session+cycle_number."""
    db = get_db()
    await db[CYCLE_RECORDS].find_one_and_update(
        {"session_id": record["session_id"], "cycle_number": record["cycle_number"]},
        {"$set": record},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def get_cycle_records(session_id: str) -> list[dict[str, Any]]:
    """Return all cycle records for a session, ordered by cycle_number ascending."""
    db = get_db()
    cursor = (
        db[CYCLE_RECORDS]
        .find({"session_id": session_id})
        .sort("cycle_number", ASCENDING)
    )
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


async def get_latest_cycle_record(session_id: str) -> dict[str, Any] | None:
    """Return the most recent cycle record for a session."""
    db = get_db()
    doc = await db[CYCLE_RECORDS].find_one(
        {"session_id": session_id},
        sort=[("cycle_number", DESCENDING)],
    )
    if doc is not None:
        doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------


async def save_mcp_server(config: dict[str, Any]) -> None:
    """Upsert an MCP server configuration."""
    db = get_db()
    await db[MCP_SERVERS].find_one_and_update(
        {"server_id": config["server_id"]},
        {"$set": {**config, "updated_at": _now()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def load_mcp_server(server_id: str) -> dict[str, Any] | None:
    """Load a single MCP server configuration."""
    db = get_db()
    doc = await db[MCP_SERVERS].find_one({"server_id": server_id})
    if doc is not None:
        doc.pop("_id", None)
    return doc


async def list_mcp_servers() -> list[dict[str, Any]]:
    """Return all saved MCP server configurations."""
    db = get_db()
    cursor = db[MCP_SERVERS].find({}).sort("created_at", DESCENDING)
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


async def delete_mcp_server(server_id: str) -> bool:
    """Delete an MCP server configuration. Returns True if a doc was deleted."""
    db = get_db()
    result = await db[MCP_SERVERS].delete_one({"server_id": server_id})
    return result.deleted_count > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)
