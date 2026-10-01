"""Unit tests for authentication verification in homelab-mcp."""

from unittest.mock import patch

import pytest
from homelab_mcp.domain.exceptions import AuthenticationError
from homelab_mcp.infrastructure.auth.google import GoogleAuthVerifier


def test_auth_disabled_returns_anonymous():
    verifier = GoogleAuthVerifier()
    with patch("homelab_mcp.infrastructure.auth.google.settings.auth_enabled", False):
        res = verifier.verify(None)
        assert res.authenticated is True
        assert res.user == "anonymous"
        assert res.auth_type == "disabled"


def test_auth_enabled_missing_token_raises_error():
    verifier = GoogleAuthVerifier()
    with patch("homelab_mcp.infrastructure.auth.google.settings.auth_enabled", True):
        with pytest.raises(AuthenticationError) as exc:
            verifier.verify(None)
        assert "Authentication required" in str(exc.value)


def test_auth_valid_service_token():
    verifier = GoogleAuthVerifier()
    with (
        patch("homelab_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch(
            "homelab_mcp.infrastructure.auth.google.settings.service_token", "super-secret-token"
        ),
    ):
        res = verifier.verify("super-secret-token")
        assert res.authenticated is True
        assert res.user == "service-account"
        assert res.auth_type == "service_token"


def test_auth_invalid_service_token_fails():
    verifier = GoogleAuthVerifier()
    with (
        patch("homelab_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch(
            "homelab_mcp.infrastructure.auth.google.settings.service_token", "super-secret-token"
        ),
        patch("homelab_mcp.infrastructure.auth.google.settings.google_client_id", ""),
        pytest.raises(AuthenticationError),
    ):
        verifier.verify("wrong-token")


@patch("homelab_mcp.infrastructure.auth.google.id_token.verify_oauth2_token")
def test_auth_google_token_success(mock_verify_oauth):
    mock_verify_oauth.return_value = {
        "email": "admin@cspaez.org",
        "name": "Admin User",
    }
    verifier = GoogleAuthVerifier()
    with (
        patch("homelab_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("homelab_mcp.infrastructure.auth.google.settings.service_token", "srv-tok"),
        patch(
            "homelab_mcp.infrastructure.auth.google.settings.google_client_id", "google-client-id"
        ),
        patch(
            "homelab_mcp.infrastructure.auth.google.settings.allowed_google_emails",
            ["admin@cspaez.org"],
        ),
    ):
        res = verifier.verify("valid-google-jwt")
        assert res.authenticated is True
        assert res.user == "admin@cspaez.org"
        assert res.name == "Admin User"
        assert res.auth_type == "google_oauth"


@patch("homelab_mcp.infrastructure.auth.google.id_token.verify_oauth2_token")
def test_auth_google_token_unauthorized_email(mock_verify_oauth):
    mock_verify_oauth.return_value = {
        "email": "stranger@gmail.com",
    }
    verifier = GoogleAuthVerifier()
    with (
        patch("homelab_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("homelab_mcp.infrastructure.auth.google.settings.service_token", "srv-tok"),
        patch(
            "homelab_mcp.infrastructure.auth.google.settings.google_client_id", "google-client-id"
        ),
        patch(
            "homelab_mcp.infrastructure.auth.google.settings.allowed_google_emails",
            ["admin@cspaez.org"],
        ),
        pytest.raises(AuthenticationError) as exc,
    ):
        verifier.verify("valid-google-jwt")
    assert "not in the allowed emails list" in str(exc.value)


@pytest.mark.asyncio
async def test_google_jwt_verifier_allowed_email():
    from unittest.mock import AsyncMock

    from fastmcp.server.auth import AccessToken
    from homelab_mcp.infrastructure.auth.google import GoogleJWTVerifier

    verifier = GoogleJWTVerifier(allowed_emails=["karlossanpa@gmail.com"])
    with patch.object(
        verifier,
        "load_access_token",
        new_callable=AsyncMock,
    ) as mock_load:
        mock_load.return_value = AccessToken(
            token="token123",
            client_id="karlossanpa@gmail.com",
            scopes=[],
            claims={"email": "karlossanpa@gmail.com"},
        )
        token = await verifier.verify_token("token123")
        assert token is not None
        assert token.client_id == "karlossanpa@gmail.com"


@pytest.mark.asyncio
async def test_google_jwt_verifier_rejected_email():
    from unittest.mock import AsyncMock

    from fastmcp.server.auth import AccessToken
    from homelab_mcp.infrastructure.auth.google import GoogleJWTVerifier

    verifier = GoogleJWTVerifier(allowed_emails=["karlossanpa@gmail.com"])
    with patch(
        "fastmcp.server.auth.providers.jwt.JWTVerifier.load_access_token",
        new_callable=AsyncMock,
    ) as mock_super_load:
        mock_super_load.return_value = AccessToken(
            token="token123",
            client_id="attacker@gmail.com",
            scopes=[],
            claims={"email": "attacker@gmail.com"},
        )
        token = await verifier.load_access_token("token123")
        assert token is None
