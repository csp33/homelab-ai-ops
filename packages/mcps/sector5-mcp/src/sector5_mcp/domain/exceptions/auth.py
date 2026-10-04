"""Authentication domain exceptions."""

from sector5_mcp.domain.exceptions.base import GatewayError


class AuthenticationError(GatewayError):
    """Raised when authentication or token verification fails."""
