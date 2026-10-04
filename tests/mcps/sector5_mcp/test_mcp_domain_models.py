"""Unit tests for sector5-mcp domain models."""

from sector5_mcp.domain.models.auth import AuthIdentity
from sector5_mcp.domain.models.guardrail import GuardrailPolicy
from sector5_mcp.domain.models.upstream import (
    ToolDefinition,
    ToolResult,
    UpstreamType,
)
from sector5_mcp.infrastructure.mcp.formatting import tool_index


def test_auth_identity_model():
    ident = AuthIdentity(authenticated=True, user="admin@cspaez.org", auth_type="google_oauth")
    assert ident.authenticated is True
    assert ident.user == "admin@cspaez.org"


def test_tool_definition_model():
    tool = ToolDefinition(
        name="ha_get_state",
        description="Fetch entity state",
        parameters={"type": "object"},
        upstream_type=UpstreamType.HOME_ASSISTANT,
    )
    assert tool.name == "ha_get_state"
    assert tool.upstream_type == "homeassistant"


def test_tool_definition_read_only_hint_is_tri_state():
    assert ToolDefinition(name="x", description="d").read_only is None
    assert (
        ToolDefinition(name="x", description="d", annotations={"readOnlyHint": True}).read_only
        is True
    )
    assert (
        ToolDefinition(name="x", description="d", annotations={"readOnlyHint": False}).read_only
        is False
    )
    # Snake-case key is accepted too, so a dict-shaped upstream annotation still works.
    assert (
        ToolDefinition(name="x", description="d", annotations={"read_only_hint": True}).read_only
        is True
    )


def test_tool_index_surfaces_read_only_hint_only_when_declared():
    declared = ToolDefinition(name="q", description="Query", annotations={"readOnlyHint": True})
    silent = ToolDefinition(name="w", description="Write")

    entries = {e["name"]: e for e in tool_index([declared, silent])}

    assert entries["q"]["read_only_hint"] is True
    assert "read_only_hint" not in entries["w"]


def test_tool_result_model():
    res = ToolResult(status="success", content={"temp": 21.5})
    assert res.status == "success"
    assert res.is_error is False


def test_guardrail_policy_defaults():
    policy = GuardrailPolicy()
    assert "*" in policy.allowed_tools
    assert "kube-system" in policy.blocked_namespaces
    assert any(r"\brm\b" in p for p in policy.blocked_exec_patterns)
    assert "*" in policy.allowed_github_repos
    assert policy.blocked_github_repos == []


def test_upstream_type_github():
    assert UpstreamType.GITHUB == "github"
    assert UpstreamType.GITHUB.value == "github"
