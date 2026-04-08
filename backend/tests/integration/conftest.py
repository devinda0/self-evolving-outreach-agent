"""Shared fixtures for integration tests."""

import pytest

from app.db.client import close_db, connect_db, get_db
from app.db.crud import create_indexes

TEST_DB = "signal_to_action_test"


@pytest.fixture(autouse=True)
async def _setup_teardown():
    """Connect to a dedicated test database, create indexes, and clean up after.

    Also resets the module-level graph singleton so that every test gets a
    fresh MongoDBSaver checkpointer that points to the active Motor client.
    Without this reset, the cached graph retains a stale Motor client after
    close_db() is called in a previous test's teardown, causing
    "RuntimeError: Event loop is closed" on subsequent tests.
    """
    from app.core.config import settings

    # Prevent the per-test fixture in test_api_campaign.py from conflicting.
    settings.DB_NAME = TEST_DB
    await connect_db()
    await create_indexes()

    # Reset the graph so checkpointer is rebuilt with the current db handle.
    import app.api.campaign as campaign_module

    campaign_module.reset_graph()

    yield

    db = get_db()
    await db.client.drop_database(TEST_DB)
    await close_db()

    # Reset again so the next test starts clean.
    campaign_module.reset_graph()
