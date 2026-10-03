"""Unit tests for homelab-mcp domain models."""

from homelab_mcp.domain.models.auth import AuthIdentity
from homelab_mcp.domain.models.guardrail import GuardrailPolicy
from homelab_mcp.domain.models.upstream import (
    ToolDefinition,
    ToolResult,
    UpstreamType,
)


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
