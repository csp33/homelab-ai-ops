"""Domain exceptions for Argo CD operations."""

from homelab_mcp.domain.exceptions.base import GatewayError


class ArgoCDError(GatewayError):
    """Base error for Argo CD operations."""


class ArgoCDAppNotFoundError(ArgoCDError):
    """Raised when an Argo CD application is not found."""


class ArgoCDOperationError(ArgoCDError):
    """Raised when an Argo CD operation fails."""
