"""Unit tests for UniFi subtool expansion and schema extraction."""

from unittest.mock import AsyncMock, patch

import pytest
from sector5_mcp.domain.models.upstream import ToolDefinition, ToolResult, UpstreamType
from sector5_mcp.infrastructure.upstream.unifi import (
    UnifiUpstreamClient,
    _extract_parameters,
)


def test_extract_parameters_reads_nested_schema_input():
    sub_tool = {
        "name": "unifi_list_clients",
        "schema": {
            "input": {
                "type": "object",
                "properties": {"search": {"type": "string"}},
                "required": ["search"],
            }
        },
    }

    assert _extract_parameters(sub_tool) == {
        "type": "object",
        "properties": {"search": {"type": "string"}},
        "required": ["search"],
    }


def test_extract_parameters_prefers_flat_parameters():
    flat = {"type": "object", "properties": {"limit": {"type": "integer"}}}
    assert _extract_parameters({"parameters": flat}) == flat


def test_extract_parameters_reads_legacy_input_schema_key():
    legacy = {"type": "object", "properties": {"mac": {"type": "string"}}}
    assert _extract_parameters({"schema": {"input_schema": legacy}}) == legacy


def test_extract_parameters_returns_empty_for_unknown_shape():
    assert _extract_parameters({}) == {}
    assert _extract_parameters({"schema": {"output": {}}}) == {}


@pytest.mark.asyncio
async def test_list_tools_expands_subtools_with_schemas():
    client = UnifiUpstreamClient(command="unifi", upstream_type=UpstreamType.UNIFI)
    root = ToolDefinition(
        name="unifi_tool_index",
        description="Index",
        parameters={},
        upstream_type=UpstreamType.UNIFI,
    )
    index_payload = {
        "tools": [
            {
                "name": "unifi_list_clients",
                "description": "Returns connected clients",
                "schema": {
                    "input": {
                        "type": "object",
                        "properties": {"search": {"type": "string"}},
                    }
                },
            }
        ]
    }

    with (
        patch(
            "sector5_mcp.infrastructure.upstream.client.ProcessUpstreamClient.list_tools",
            AsyncMock(return_value=[root]),
        ),
        patch.object(
            client,
            "call_tool",
            AsyncMock(return_value=ToolResult(status="success", content=index_payload)),
        ) as mock_call,
    ):
        tools = await client.list_tools()

    by_name = {t.name: t for t in tools}
    assert "unifi_list_clients" in by_name
    assert by_name["unifi_list_clients"].parameters["properties"]["search"] == {"type": "string"}
    mock_call.assert_awaited_once_with("unifi_tool_index", {"include_schemas": True})
