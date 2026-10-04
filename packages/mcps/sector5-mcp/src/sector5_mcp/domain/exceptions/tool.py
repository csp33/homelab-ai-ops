"""Tool routing and discovery domain exceptions."""

from sector5_mcp.domain.exceptions.base import GatewayError


class ToolNotFoundError(GatewayError):
    """Raised when a requested tool does not exist on any upstream."""
