"""Async CRUD operations for all MongoDB collections."""

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.db.client import get_db
from app.db.collections import (
    CAMPAIGN_SESSIONS,
    CONTENT_VARIANTS,
    DEPLOYMENT_RECORDS,
    FEEDBACK_EVENTS,
    QUARANTINE,
    RESEARCH_FINDINGS,
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


# ---------------------------------------------------------------------------
# Research findings
# ---------------------------------------------------------------------------

async def save_research_finding(finding: dict[str, Any]) -> None:
    """Insert a single research finding."""
    db = get_db()
    await db[RESEARCH_FINDINGS].insert_one(finding)


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
    doc = await db[DEPLOYMENT_RECORDS].find_one(
        {"provider_message_id": provider_message_id}
    )
    if doc is not None:
        doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Feedback events
# ---------------------------------------------------------------------------

async def save_feedback_event(event: dict[str, Any]) -> None:
    """Insert a normalized feedback event."""
    db = get_db()
    await db[FEEDBACK_EVENTS].insert_one(event)


async def save_quarantine_event(event: dict[str, Any]) -> None:
    """Insert an unmatched/quarantined event."""
    db = get_db()
    await db[QUARANTINE].insert_one(event)


# ---------------------------------------------------------------------------
# Tool cache
# ---------------------------------------------------------------------------

async def cache_tool_result(key: str, value: Any, ttl_seconds: int) -> None:
    """Upsert a cached tool result with a TTL-based expiry."""
    db = get_db()
    expires_at = datetime.fromtimestamp(
        _now().timestamp() + ttl_seconds, tz=timezone.utc
    )
    await db[TOOL_CACHE].find_one_and_update(
        {"key": key},
        {"$set": {"key": key, "value": value, "expires_at": expires_at}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def get_cached_tool_result(key: str) -> Any | None:
    """Return a cached value if it exists and hasn't expired. Returns None otherwise."""
    db = get_db()
    doc = await db[TOOL_CACHE].find_one(
        {"key": key, "expires_at": {"$gt": _now()}}
    )
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
    await db[DEPLOYMENT_RECORDS].create_index("provider_message_id")
    await db[FEEDBACK_EVENTS].create_index("dedupe_key", unique=True)
    await db[TOOL_CACHE].create_index("expires_at", expireAfterSeconds=0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)
