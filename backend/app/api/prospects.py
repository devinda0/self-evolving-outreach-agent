"""Prospect and segment API — CSV import, prospect retrieval, segment selection."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prospects"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SelectSegmentRequest(BaseModel):
    segment_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/campaign/{session_id}/prospects/import")
async def import_prospects(session_id: str, file: UploadFile) -> dict[str, Any]:
    """Accept a CSV file upload, score prospects, and persist them.

    The CSV must have columns: name, email, linkedin_url, title, company.
    """
    state = await load_campaign_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    raw_prospects = await load_prospects_from_csv_bytes(csv_bytes)
    if not raw_prospects:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    # Derive segments if none exist yet
    segments_data = await get_segments(session_id)
    if not segments_data:
        from app.models.prospect import Segment

        segments = await derive_segments(
            briefing_summary=state.get("briefing_summary"),
            research_findings=state.get("research_findings", []),
            product_name=state.get("product_name", "Unknown Product"),
        )
        for seg in segments:
            seg.session_id = session_id
        await save_segments(session_id, [s.model_dump() for s in segments])
        segments_data = [s.model_dump() for s in segments]

    # Score prospects
    from app.models.prospect import Segment as SegmentModel

    segments_obj = [SegmentModel(**s) for s in segments_data]
    top_findings = state.get("research_findings", [])[:5]
    scored = await score_prospects(raw_prospects, segments_obj, top_findings)
    cards = [build_prospect_card(p) for p in scored]

    # Persist
    await save_prospect_cards(session_id, scored)

    # Update campaign state
    state["prospect_cards"] = cards
    state["segment_candidates"] = segments_data
    await save_campaign_state(session_id, state)

    logger.info("Imported %d prospects for session %s", len(cards), session_id)
    return {"imported": len(cards), "prospect_cards": cards}


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
