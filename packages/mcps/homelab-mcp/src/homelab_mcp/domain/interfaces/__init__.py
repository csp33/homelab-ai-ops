"""Domain interfaces re-exports."""

from homelab_mcp.domain.interfaces.auth import AuthVerifierInterface
from homelab_mcp.domain.interfaces.upstream import UpstreamMCPInterface

__all__ = [
    "AuthVerifierInterface",
    "UpstreamMCPInterface",
]
