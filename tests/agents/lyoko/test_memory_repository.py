"""Tests for PostgresMemoryRepository and Memory Domain Models."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.domain.models.memory import FeedbackRequest, MemoryEntry, MemoryQueryResult
from lyoko.infrastructure.db.memory_repository import PostgresMemoryRepository


def _create_mock_pool(mock_cur):
    """Helper to mock psycopg3 async connection and pool."""
    mock_cur_ctx = MagicMock()
    mock_cur_ctx.__aenter__ = AsyncMock(return_value=mock_cur)
    mock_cur_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cur_ctx)

    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn_ctx)
    return mock_pool


def test_memory_domain_models():
    """Verify memory domain model creation and validation."""
    req = FeedbackRequest(
        namespace="monitoring",
        service_name="influxdb",
        alert_name="PodCrashLooping",
        incident_pattern="OOMKilled exit code 137 on startup",
        operator_feedback="Do not increase memory limit, check WAL compaction",
        action_rule="Check WAL compaction logs before restarting",
    )
    assert req.namespace == "monitoring"
    assert req.service_name == "influxdb"
    assert req.alert_name == "PodCrashLooping"

    entry = MemoryEntry(
        id=1,
        namespace=req.namespace,
        service_name=req.service_name,
        alert_name=req.alert_name,
        incident_pattern=req.incident_pattern,
        operator_feedback=req.operator_feedback,
        action_rule=req.action_rule,
        created_at=datetime.now(UTC),
    )
    assert entry.id == 1

    query_res = MemoryQueryResult(memory=entry, similarity=0.92)
    assert query_res.similarity == 0.92
    assert query_res.memory.service_name == "influxdb"


@pytest.mark.asyncio
async def test_save_memory():
    """Verify save_memory executes correct SQL INSERT."""
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 42})
    mock_pool = _create_mock_pool(mock_cur)

    repo = PostgresMemoryRepository(mock_pool)
    entry = MemoryEntry(
        namespace="default",
        service_name="frontend",
        alert_name="OOMKilled",
        incident_pattern="OOMKilled",
        operator_feedback="Scale to 2 replicas instead of bumping memory",
    )

    mem_id = await repo.save_memory(entry, embedding=[0.1, 0.2, 0.3])
    assert mem_id == 42
    assert mock_cur.execute.called
    query_str = mock_cur.execute.call_args[0][0]
    assert "INSERT INTO agent_memory" in query_str


@pytest.mark.asyncio
async def test_search_memories():
    """Verify search_memories returns formatted MemoryQueryResult list."""
    mock_cur = AsyncMock()
    mock_cur.fetchall = AsyncMock(
        return_value=[
            {
                "id": 1,
                "namespace": "monitoring",
                "service_name": "influxdb",
                "alert_name": "OOM",
                "incident_pattern": "OOMKilled exit code 137",
                "operator_feedback": "Do not bump RAM",
                "action_rule": "Truncate WAL",
                "created_at": datetime.now(UTC),
                "similarity": 0.89,
            }
        ]
    )
    mock_pool = _create_mock_pool(mock_cur)

    repo = PostgresMemoryRepository(mock_pool)
    results = await repo.search_memories(
        query_embedding=[0.1] * 1536,
        namespace="monitoring",
        service_name="influxdb",
    )

    assert len(results) == 1
    assert results[0].similarity == 0.89
    assert results[0].memory.service_name == "influxdb"
    assert results[0].memory.operator_feedback == "Do not bump RAM"
    query_str = mock_cur.execute.call_args[0][0]
    assert "AND (1 - (embedding <=> %s::vector)) >= %s" in query_str


@pytest.mark.asyncio
async def test_search_memories_with_min_similarity():
    """Verify search_memories passes min_similarity parameter to query."""
    mock_cur = AsyncMock()
    mock_cur.fetchall = AsyncMock(return_value=[])
    mock_pool = _create_mock_pool(mock_cur)

    repo = PostgresMemoryRepository(mock_pool)
    await repo.search_memories(
        query_embedding=[0.1] * 1536,
        min_similarity=0.2,
    )

    assert mock_cur.execute.called
    params = mock_cur.execute.call_args[0][1]
    assert 0.2 in params


@pytest.mark.asyncio
async def test_list_recent_memories():
    """Verify list_recent_memories returns memories list."""
    mock_cur = AsyncMock()
    mock_cur.fetchall = AsyncMock(
        return_value=[
            {
                "id": 10,
                "namespace": "default",
                "service_name": "web",
                "alert_name": None,
                "incident_pattern": "CrashLoop",
                "operator_feedback": "Check DB credentials",
                "action_rule": None,
                "created_at": datetime.now(UTC),
            }
        ]
    )
    mock_pool = _create_mock_pool(mock_cur)

    repo = PostgresMemoryRepository(mock_pool)
    memories = await repo.list_recent_memories(limit=10)

    assert len(memories) == 1
    assert memories[0].id == 10
    assert memories[0].service_name == "web"


@pytest.mark.asyncio
async def test_delete_memory_found():
    """Verify delete_memory returns True when row is deleted."""
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 42})
    mock_pool = _create_mock_pool(mock_cur)

    repo = PostgresMemoryRepository(mock_pool)
    result = await repo.delete_memory(42)

    assert result is True
    assert mock_cur.execute.called
    query_str = mock_cur.execute.call_args[0][0]
    assert "DELETE FROM agent_memory" in query_str
    assert mock_cur.execute.call_args[0][1] == (42,)


@pytest.mark.asyncio
async def test_delete_memory_not_found():
    """Verify delete_memory returns False when no row matches."""
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value=None)
    mock_pool = _create_mock_pool(mock_cur)

    repo = PostgresMemoryRepository(mock_pool)
    result = await repo.delete_memory(999)

    assert result is False
    assert mock_cur.execute.called
