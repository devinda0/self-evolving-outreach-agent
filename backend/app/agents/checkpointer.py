"""MongoDB-backed checkpoint saver for LangGraph, using motor (async) and pymongo (sync)."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

logger = logging.getLogger(__name__)

CHECKPOINTS_COLLECTION = "checkpoints"
CHECKPOINT_WRITES_COLLECTION = "checkpoint_writes"


def _config_to_key(config: RunnableConfig) -> dict[str, str]:
    """Extract the thread_id and checkpoint_id from a RunnableConfig."""
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id", "")
    checkpoint_ns = configurable.get("checkpoint_ns", "")
    checkpoint_id = configurable.get("checkpoint_id")
    key = {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}
    if checkpoint_id is not None:
        key["checkpoint_id"] = checkpoint_id
    return key


def _make_config(thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> RunnableConfig:
    """Build a RunnableConfig from identifiers."""
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
        }
    }


class MongoDBSaver(BaseCheckpointSaver):
    """LangGraph checkpoint saver backed by MongoDB (async via motor)."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__()
        self.db = db

    # ------------------------------------------------------------------
    # Async implementations (primary — used by LangGraph's async runtime)
    # ------------------------------------------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        key = _config_to_key(config)
        coll = self.db[CHECKPOINTS_COLLECTION]

        if "checkpoint_id" in key:
            doc = await coll.find_one(key)
        else:
            # Fetch the latest checkpoint for this thread
            doc = await coll.find_one(
                {"thread_id": key["thread_id"], "checkpoint_ns": key["checkpoint_ns"]},
                sort=[("checkpoint_id", DESCENDING)],
            )

        if doc is None:
            return None

        checkpoint = self.serde.loads_typed((doc["type"], doc["checkpoint"]))
        metadata = self.serde.loads_typed((doc["metadata_type"], doc["metadata"]))

        cfg = _make_config(doc["thread_id"], doc["checkpoint_ns"], doc["checkpoint_id"])
        parent_config = None
        if doc.get("parent_checkpoint_id"):
            parent_config = _make_config(
                doc["thread_id"], doc["checkpoint_ns"], doc["parent_checkpoint_id"]
            )

        # Load pending writes for this checkpoint
        writes_coll = self.db[CHECKPOINT_WRITES_COLLECTION]
        pending_writes: list[tuple[str, str, Any]] = []
        cursor = writes_coll.find(
            {
                "thread_id": doc["thread_id"],
                "checkpoint_ns": doc["checkpoint_ns"],
                "checkpoint_id": doc["checkpoint_id"],
            }
        )
        async for write_doc in cursor:
            pending_writes.append(
                (
                    write_doc["task_id"],
                    write_doc["channel"],
                    self.serde.loads_typed((write_doc["type"], write_doc["value"])),
                )
            )

        return CheckpointTuple(
            config=cfg,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = configurable.get("checkpoint_id")

        type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
        metadata_type, serialized_metadata = self.serde.dumps_typed(metadata)

        doc = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "type": type_,
            "checkpoint": serialized_checkpoint,
            "metadata_type": metadata_type,
            "metadata": serialized_metadata,
        }

        coll = self.db[CHECKPOINTS_COLLECTION]
        await coll.replace_one(
            {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            },
            doc,
            upsert=True,
        )

        return _make_config(thread_id, checkpoint_ns, checkpoint_id)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id", "")

        coll = self.db[CHECKPOINT_WRITES_COLLECTION]
        for idx, (channel, value) in enumerate(writes):
            type_, serialized_value = self.serde.dumps_typed(value)
            doc = {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "task_path": task_path,
                "idx": idx,
                "channel": channel,
                "type": type_,
                "value": serialized_value,
            }
            await coll.replace_one(
                {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "idx": idx,
                },
                doc,
                upsert=True,
            )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        coll = self.db[CHECKPOINTS_COLLECTION]
        query: dict[str, Any] = {}

        if config is not None:
            configurable = config.get("configurable", {})
            query["thread_id"] = configurable.get("thread_id", "")
            query["checkpoint_ns"] = configurable.get("checkpoint_ns", "")

        if before is not None:
            before_configurable = before.get("configurable", {})
            before_id = before_configurable.get("checkpoint_id")
            if before_id:
                query["checkpoint_id"] = {"$lt": before_id}

        if filter:
            for key, value in filter.items():
                query[f"metadata.{key}"] = value

        cursor = coll.find(query).sort("checkpoint_id", DESCENDING)
        if limit is not None:
            cursor = cursor.limit(limit)

        async for doc in cursor:
            checkpoint = self.serde.loads_typed((doc["type"], doc["checkpoint"]))
            metadata = self.serde.loads_typed((doc["metadata_type"], doc["metadata"]))

            cfg = _make_config(doc["thread_id"], doc["checkpoint_ns"], doc["checkpoint_id"])
            parent_config = None
            if doc.get("parent_checkpoint_id"):
                parent_config = _make_config(
                    doc["thread_id"], doc["checkpoint_ns"], doc["parent_checkpoint_id"]
                )

            yield CheckpointTuple(
                config=cfg,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )

    # ------------------------------------------------------------------
    # Sync implementations (delegate to async via event loop)
    # ------------------------------------------------------------------

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return asyncio.get_event_loop().run_until_complete(self.aget_tuple(config))

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return asyncio.get_event_loop().run_until_complete(
            self.aput(config, checkpoint, metadata, new_versions)
        )

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        asyncio.get_event_loop().run_until_complete(
            self.aput_writes(config, writes, task_id, task_path)
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        raise NotImplementedError(
            "MongoDBSaver.list() is not supported in sync mode. Use alist() instead."
        )
