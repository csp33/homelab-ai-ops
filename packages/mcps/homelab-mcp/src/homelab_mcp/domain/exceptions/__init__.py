"""Domain exceptions re-exports."""

from homelab_mcp.domain.exceptions.auth import AuthenticationError
from homelab_mcp.domain.exceptions.base import GatewayError
from homelab_mcp.domain.exceptions.guardrail import GuardrailViolationError
from homelab_mcp.domain.exceptions.tool import ToolNotFoundError
from homelab_mcp.domain.exceptions.upstream import UpstreamUnavailableError

__all__ = [
    "AuthenticationError",
    "GatewayError",
    "GuardrailViolationError",
    "ToolNotFoundError",
    "UpstreamUnavailableError",
]
