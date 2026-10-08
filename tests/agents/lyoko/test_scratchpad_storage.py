"""Tests for ScratchpadFileStorage adapter."""

from pathlib import Path

import pytest
from lyoko.infrastructure.storage.scratchpad_file_storage import ScratchpadFileStorage


@pytest.mark.asyncio
async def test_store_and_read_output(tmp_path: Path):
    storage = ScratchpadFileStorage(base_dir=tmp_path)
    content = "line 1\nline 2\nline 3\n" * 100

    ref = await storage.store_output(
        tool_name="k8s_get_pod_logs",
        raw_output=content,
        session_id="session-123",
    )

    assert ref.reference_id.startswith("scratch_")
    assert ref.tool_name == "k8s_get_pod_logs"
    assert ref.line_count == 300
    assert ref.size_bytes > 0
    assert Path(ref.file_path).exists()

    read_back = await storage.read_output(ref.reference_id)
    assert read_back == content


@pytest.mark.asyncio
async def test_read_nonexistent_returns_none(tmp_path: Path):
    storage = ScratchpadFileStorage(base_dir=tmp_path)
    result = await storage.read_output("nonexistent_id")
    assert result is None
