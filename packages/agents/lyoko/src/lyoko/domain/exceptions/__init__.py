"""Domain exceptions re-exports for LYOKO."""

from lyoko.domain.exceptions.base import LyokoError
from lyoko.domain.exceptions.incident import IncidentNotFoundError, IncidentRemediationError
from lyoko.domain.exceptions.mcp import (
    MCPAuthenticationError,
    MCPEndpointNotFoundError,
    MCPGatewayError,
    MCPGatewayUnreachableError,
)

__all__ = [
    "IncidentNotFoundError",
    "IncidentRemediationError",
    "LyokoError",
    "MCPAuthenticationError",
    "MCPEndpointNotFoundError",
    "MCPGatewayError",
    "MCPGatewayUnreachableError",
]
