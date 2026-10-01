"""Upstream MCP server domain exceptions."""

from homelab_mcp.domain.exceptions.base import GatewayError


class UpstreamUnavailableError(GatewayError):
    """Raised when an upstream MCP server cannot be reached."""
