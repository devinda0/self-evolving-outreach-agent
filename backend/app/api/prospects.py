"""Prospect and segment API — CSV import, prospect discovery, retrieval, segment selection, manual management."""

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

from app.agents.prospect_discovery import (
    deduplicate_prospects,
    discover_prospects_via_research,
    load_prospects_from_csv_with_mapping,
)
from app.agents.segment_agent import (
    build_prospect_card,
    derive_segments,
    load_prospects_from_csv_bytes,
    score_prospects,
)
from app.db.crud import (
    get_prospect_cards,
    get_segments,
    load_campaign_state,
    save_campaign_state,
    save_prospect_cards,
    save_segments,
)
from app.models.prospect import Segment

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prospects"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SelectSegmentRequest(BaseModel):
    segment_id: str


class DiscoverProspectsRequest(BaseModel):
    num_prospects: int = 10


class CsvImportOptions(BaseModel):
    column_mapping: dict[str, str] | None = None


class AddProspectRequest(BaseModel):
    name: str
    email: str | None = None
    title: str | None = None
    company: str | None = None
    linkedin_url: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        if len(v) > 200:
            raise ValueError("Name must be 200 characters or fewer")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.lower()


class RemoveProspectsRequest(BaseModel):
    prospect_ids: list[str]


class SelectProspectsRequest(BaseModel):
    prospect_ids: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/campaign/{session_id}/prospects/import")
async def import_prospects(session_id: str, file: UploadFile) -> dict[str, Any]:
    """Accept a CSV file upload with auto column mapping, score prospects, and persist them.

    The CSV should have columns mappable to: name, email, linkedin_url, title, company.
    Auto-detects common column name variations.
    """
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Use enhanced CSV import with auto column mapping
    raw_prospects = await load_prospects_from_csv_with_mapping(csv_bytes)
    if not raw_prospects:
        # Fall back to legacy parser
        raw_prospects = await load_prospects_from_csv_bytes(csv_bytes)
    if not raw_prospects:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    # Derive segments if none exist yet
    segments_data = await get_segments(session_id)
    if not segments_data:
        segments = await derive_segments(
            briefing_summary=state.get("briefing_summary"),
            research_findings=state.get("research_findings", []),
            product_name=state.get("product_name", "Unknown Product"),
        )
        for seg in segments:
            seg.session_id = session_id
        await save_segments(session_id, [s.model_dump() for s in segments])
        segments_data = [s.model_dump() for s in segments]

    # Merge with existing prospects and deduplicate
    existing_cards = await get_prospect_cards(session_id)
    all_prospects = existing_cards + raw_prospects
    deduped = deduplicate_prospects(all_prospects)

    # Score prospects
    segments_obj = [Segment(**s) for s in segments_data]
    top_findings = state.get("research_findings", [])[:5]
    scored = await score_prospects(
        deduped, segments_obj, top_findings,
        target_market=state.get("target_market", ""),
    )
    cards = [build_prospect_card(p) for p in scored]

    # Persist
    await save_prospect_cards(session_id, scored)

    # Update campaign state
    state["prospect_cards"] = cards
    state["segment_candidates"] = segments_data
    await save_campaign_state(session_id, state)

    logger.info("Imported %d prospects for session %s", len(cards), session_id)
    return {"imported": len(cards), "prospect_cards": cards}


@router.post("/campaign/{session_id}/prospects/discover")
async def discover_prospects(
    session_id: str,
    req: DiscoverProspectsRequest | None = None,
) -> dict[str, Any]:
    """Discover prospects using research findings for the session.

    Uses the research agent's findings to generate targeted search queries,
    find real prospects, and score them against the campaign's segments.
    """
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    research_findings = state.get("research_findings", [])
    if not research_findings:
        raise HTTPException(
            status_code=400,
            detail="No research findings available. Run research first.",
        )

    num_prospects = req.num_prospects if req else 10

    # Discover prospects
    discovered = await discover_prospects_via_research(
        product_name=state.get("product_name", "Unknown Product"),
        target_market=state.get("target_market", ""),
        research_findings=research_findings,
        num_prospects=num_prospects,
    )

    if not discovered:
        raise HTTPException(status_code=500, detail="Prospect discovery returned no results")

    # Merge with existing and deduplicate
    existing_cards = await get_prospect_cards(session_id)
    all_prospects = existing_cards + discovered
    deduped = deduplicate_prospects(all_prospects)

    # Derive segments if needed
    segments_data = await get_segments(session_id)
    if not segments_data:
        segments = await derive_segments(
            briefing_summary=state.get("briefing_summary"),
            research_findings=research_findings,
            product_name=state.get("product_name", "Unknown Product"),
        )
        for seg in segments:
            seg.session_id = session_id
        await save_segments(session_id, [s.model_dump() for s in segments])
        segments_data = [s.model_dump() for s in segments]

    # Score all prospects
    segments_obj = [Segment(**s) for s in segments_data]
    top_findings = research_findings[:5]
    scored = await score_prospects(
        deduped, segments_obj, top_findings,
        target_market=state.get("target_market", ""),
    )
    cards = [build_prospect_card(p) for p in scored]

    # Persist
    await save_prospect_cards(session_id, scored)
    state["prospect_cards"] = cards
    await save_campaign_state(session_id, state)

    logger.info(
        "Discovered %d new prospects, %d total after dedup for session %s",
        len(discovered), len(cards), session_id,
    )
    return {
        "discovered": len(discovered),
        "total": len(cards),
        "prospect_cards": cards,
    }


@router.get("/campaign/{session_id}/prospects")
async def get_prospects(session_id: str) -> dict[str, Any]:
    """Return all scored prospect cards for a session."""
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    cards = await get_prospect_cards(session_id)
    return {"prospect_cards": cards}


@router.post("/campaign/{session_id}/segments/select")
async def select_segment(session_id: str, req: SelectSegmentRequest) -> dict[str, Any]:
    """Set the selected_segment_id in the campaign state."""
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate segment exists
    segments = await get_segments(session_id)
    segment_ids = {s["id"] for s in segments}
    if req.segment_id not in segment_ids:
        raise HTTPException(status_code=400, detail="Segment not found")

    state["selected_segment_id"] = req.segment_id
    await save_campaign_state(session_id, state)

    logger.info("Selected segment %s for session %s", req.segment_id, session_id)
    return {"selected_segment_id": req.segment_id}


@router.post("/campaign/{session_id}/prospects/add")
async def add_prospect(session_id: str, req: AddProspectRequest) -> dict[str, Any]:
    """Add a single prospect manually to the session's prospect list."""
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    existing_cards = await get_prospect_cards(session_id)

    prospect_id = f"prospect-{uuid.uuid4().hex[:8]}"
    new_prospect: dict[str, Any] = {
        "id": prospect_id,
        "name": req.name,
        "email": req.email,
        "linkedin_url": req.linkedin_url,
        "title": req.title or "",
        "company": req.company or "",
        "fit_score": 0.75,
        "urgency_score": 0.60,
        "angle_recommendation": "value-proposition",
        "channel_recommendation": "email" if req.email else "linkedin",
        "personalization_fields": {},
        "source": "manual",
        "discovery_query": None,
        "role_seniority": None,
        "company_fit": None,
        "signal_recency": None,
    }

    # Deduplicate
    all_prospects = existing_cards + [new_prospect]
    deduped = deduplicate_prospects(all_prospects)

    await save_prospect_cards(session_id, deduped)

    # Update state with the new cards
    cards = [build_prospect_card(p) for p in deduped]
    state["prospect_cards"] = cards
    await save_campaign_state(session_id, state)

    logger.info("Added prospect %s for session %s", req.name, session_id)
    return {"prospect": build_prospect_card(new_prospect), "total": len(cards)}


@router.post("/campaign/{session_id}/prospects/remove")
async def remove_prospects(session_id: str, req: RemoveProspectsRequest) -> dict[str, Any]:
    """Remove prospects by ID from the session's prospect list."""
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    existing_cards = await get_prospect_cards(session_id)
    ids_to_remove = set(req.prospect_ids)

    updated = [c for c in existing_cards if c.get("id") not in ids_to_remove]
    removed_count = len(existing_cards) - len(updated)

    await save_prospect_cards(session_id, updated)

    # Update state
    cards = [build_prospect_card(p) for p in updated]
    state["prospect_cards"] = cards
    # Also remove from selected IDs
    selected = state.get("selected_prospect_ids", [])
    state["selected_prospect_ids"] = [s for s in selected if s not in ids_to_remove]
    await save_campaign_state(session_id, state)

    logger.info("Removed %d prospects for session %s", removed_count, session_id)
    return {"removed": removed_count, "remaining": len(cards)}


@router.post("/campaign/{session_id}/prospects/select")
async def select_prospects(session_id: str, req: SelectProspectsRequest) -> dict[str, Any]:
    """Set the selected prospect IDs for the session."""
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate all IDs exist in the prospect list
    existing_cards = await get_prospect_cards(session_id)
    valid_ids = {c.get("id") for c in existing_cards}
    invalid = [pid for pid in req.prospect_ids if pid not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown prospect IDs: {invalid}",
        )

    state["selected_prospect_ids"] = req.prospect_ids
    await save_campaign_state(session_id, state)

    logger.info(
        "Selected %d prospects for session %s", len(req.prospect_ids), session_id
    )
    return {"selected_ids": req.prospect_ids, "count": len(req.prospect_ids)}
