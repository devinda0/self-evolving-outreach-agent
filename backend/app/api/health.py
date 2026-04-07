"""Health check endpoint."""

from fastapi import APIRouter

from app.db.client import get_db

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
