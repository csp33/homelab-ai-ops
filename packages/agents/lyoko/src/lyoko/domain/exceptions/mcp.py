"""Domain exceptions raised when the MCP gateway cannot be used by LYOKO."""

from lyoko.domain.exceptions.base import LyokoError


class MCPGatewayError(LyokoError):
    """Base error for any failure talking to the homelab-mcp gateway."""

    #: True when retrying cannot help because the configuration itself is wrong.
    is_configuration_error: bool = False


class MCPAuthenticationError(MCPGatewayError):
    """The gateway rejected the credentials (HTTP 401/403)."""

    is_configuration_error = True


class MCPEndpointNotFoundError(MCPGatewayError):
    """The gateway answered but the configured URL is not an MCP endpoint (HTTP 404)."""

    is_configuration_error = True


class MCPGatewayUnreachableError(MCPGatewayError):
    """The gateway could not be reached at all (DNS, connection refused, timeout)."""
