"""Async MongoDB connection management using motor."""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

client: AsyncIOMotorClient | None = None
db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    """Open the MongoDB connection and select the application database."""
    global client, db
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DB_NAME]


async def close_db() -> None:
    """Close the MongoDB connection."""
    global client, db
    if client is not None:
        client.close()
    client = None
    db = None


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database handle. Raises if not connected."""
    if db is None:
        raise RuntimeError("Database not connected. Call connect_db() first.")
    return db
