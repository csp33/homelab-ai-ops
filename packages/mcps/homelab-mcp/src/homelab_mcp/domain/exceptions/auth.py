"""Authentication domain exceptions."""

from homelab_mcp.domain.exceptions.base import GatewayError


class AuthenticationError(GatewayError):
    """Raised when authentication or token verification fails."""
