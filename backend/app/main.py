from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.client import close_db, connect_db
from app.db.crud import create_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await create_indexes()
    yield
    await close_db()


app = FastAPI(
    title="Signal to Action",
    description="Self-evolving outreach agent — closed-loop multi-agent growth intelligence",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
