"""Authentication verifier interface definitions."""

from abc import ABC, abstractmethod

from homelab_mcp.domain.models import AuthIdentity


class AuthVerifierInterface(ABC):
    @abstractmethod
    def verify(self, token: str | None) -> AuthIdentity:
        """Verify token and return authenticated identity or raise AuthenticationError."""
