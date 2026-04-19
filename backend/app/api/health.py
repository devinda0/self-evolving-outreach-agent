"""Health check endpoints."""

from typing import Any

from fastapi import APIRouter, Response

from app.db.client import get_db
from app.tools.unipile_client import get_unipile_connection_health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness / readiness probe with a quick DB ping."""
    try:
        db = get_db()
        await db.command("ping")
        db_status = "connected"
    except Exception:
        db_status = "unavailable"

    return {"status": "ok", "db": db_status}


@router.get("/health/unipile")
async def health_unipile(response: Response) -> dict[str, Any]:
    """Read-only Unipile probe for the configured LinkedIn account."""
    result = await get_unipile_connection_health()
    if result.get("status") != "connected":
        response.status_code = 503
    return result
