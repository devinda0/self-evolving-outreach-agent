import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import campaign, health, mcp, prospects, webhooks
from app.db.client import close_db, connect_db
from app.db.crud import create_indexes
from app.mcp.manager import get_mcp_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    try:
        await create_indexes()
    except Exception as exc:
        # Log but do not crash — missing indexes degrade performance, not correctness.
        # The app must still start so Railway's health check passes.
        logger.warning("Could not create indexes on startup (will retry later): %s", exc)
    # Start saved MCP servers
    mcp_manager = get_mcp_manager()
    try:
        await mcp_manager.load_from_db()
    except Exception as exc:
        logger.warning("Could not load MCP servers on startup: %s", exc)
    yield
    await mcp_manager.shutdown()
    await close_db()


app = FastAPI(
    title="Signal to Action",
    description="Self-evolving outreach agent — closed-loop multi-agent growth intelligence",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaign.router)
app.include_router(webhooks.router)
app.include_router(health.router)
app.include_router(prospects.router)
app.include_router(mcp.router)
