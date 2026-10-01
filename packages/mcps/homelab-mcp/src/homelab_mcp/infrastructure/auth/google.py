"""Google OAuth2 and token verification infrastructure adapter."""

import logging

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from homelab_mcp.config import settings
from homelab_mcp.domain.exceptions import AuthenticationError
from homelab_mcp.domain.interfaces import AuthVerifierInterface
from homelab_mcp.domain.models import AuthIdentity

logger = logging.getLogger("homelab_mcp.auth_adapter")


class GoogleJWTVerifier(JWTVerifier):
    """FastMCP JWTVerifier validating Google ID tokens and restricting by allowed emails."""

    def __init__(
        self,
        allowed_emails: list[str] | None = None,
        jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs",
        issuer: str = "https://accounts.google.com",
        **kwargs,
    ):
        super().__init__(jwks_uri=jwks_uri, issuer=issuer, **kwargs)
        self.allowed_emails = set(allowed_emails or [])

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = await super().load_access_token(token)
        if not access_token:
            return None

        if self.allowed_emails:
            email = access_token.claims.get("email")
            if not email or email not in self.allowed_emails:
                logger.warning(
                    f"Google ID token rejected: email '{email}' is not in allowed_google_emails."
                )
                return None

        return access_token


class GoogleAuthVerifier(AuthVerifierInterface):
    def verify(self, token: str | None) -> AuthIdentity:
        if not settings.auth_enabled:
            return AuthIdentity(authenticated=True, user="anonymous", auth_type="disabled")

        if not token:
            raise AuthenticationError("Authentication required: No token provided.")

        # 1. Internal static service token check
        if settings.service_token and token == settings.service_token:
            return AuthIdentity(
                authenticated=True, user="service-account", auth_type="service_token"
            )

        # 2. Google OAuth2 ID token verification
        try:
            request = google_requests.Request()
            id_info = id_token.verify_oauth2_token(
                token,
                request,
                audience=settings.google_client_id if settings.google_client_id else None,
            )

            email = id_info.get("email")
            if not email:
                raise AuthenticationError("Invalid Google token: email claim missing.")

            if settings.allowed_google_emails and email not in settings.allowed_google_emails:
                raise AuthenticationError(
                    f"Access denied: Google user '{email}' is not in the allowed emails list."
                )

            return AuthIdentity(
                authenticated=True,
                user=email,
                auth_type="google_oauth",
                name=id_info.get("name"),
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            logger.warning(f"Google token verification failed: {exc}")
            raise AuthenticationError(f"Authentication failed: {exc}") from exc
