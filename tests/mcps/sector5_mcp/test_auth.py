"""Unit tests for authentication verification in sector5-mcp."""

from unittest.mock import patch

import pytest
from sector5_mcp.domain.exceptions.auth import AuthenticationError
from sector5_mcp.infrastructure.auth.google import GoogleAuthVerifier


def test_auth_disabled_returns_anonymous():
    verifier = GoogleAuthVerifier()
    with patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", False):
        res = verifier.verify(None)
        assert res.authenticated is True
        assert res.user == "anonymous"
        assert res.auth_type == "disabled"


def test_auth_enabled_missing_token_raises_error():
    verifier = GoogleAuthVerifier()
    with patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True):
        with pytest.raises(AuthenticationError) as exc:
            verifier.verify(None)
        assert "Authentication required" in str(exc.value)


def test_auth_valid_service_token():
    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.service_token", "super-secret-token"
        ),
    ):
        res = verifier.verify("super-secret-token")
        assert res.authenticated is True
        assert res.user == "service-account"
        assert res.auth_type == "service_token"


def test_auth_invalid_service_token_fails():
    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.service_token", "super-secret-token"
        ),
        patch("sector5_mcp.infrastructure.auth.google.settings.google_client_id", ""),
        pytest.raises(AuthenticationError),
    ):
        verifier.verify("wrong-token")


@patch("sector5_mcp.infrastructure.auth.google.id_token.verify_oauth2_token")
def test_auth_google_token_success(mock_verify_oauth):
    mock_verify_oauth.return_value = {
        "email": "admin@cspaez.org",
        "name": "Admin User",
    }
    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.service_token", "srv-tok"),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.google_client_id", "google-client-id"
        ),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails",
            ["admin@cspaez.org"],
        ),
    ):
        res = verifier.verify("valid-google-jwt")
        assert res.authenticated is True
        assert res.user == "admin@cspaez.org"
        assert res.name == "Admin User"
        assert res.auth_type == "google_oauth"


@patch("sector5_mcp.infrastructure.auth.google.id_token.verify_oauth2_token")
def test_auth_google_token_unauthorized_email(mock_verify_oauth):
    mock_verify_oauth.return_value = {
        "email": "stranger@gmail.com",
    }
    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.service_token", "srv-tok"),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.google_client_id", "google-client-id"
        ),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails",
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
    from sector5_mcp.infrastructure.auth.google import GoogleJWTVerifier

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
    from sector5_mcp.infrastructure.auth.google import GoogleJWTVerifier

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


def test_auth_hs256_jwt_with_jwt_secret_success():
    import jwt

    secret = "my-custom-jwt-secret-key-1234567890-secure-32bytes"
    token = jwt.encode(
        {"email": "admin@cspaez.org", "name": "Admin User", "sub": "12345"},
        secret,
        algorithm="HS256",
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.jwt_secret", secret),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails",
            ["admin@cspaez.org"],
        ),
    ):
        res = verifier.verify(token)
        assert res.authenticated is True
        assert res.user == "admin@cspaez.org"
        assert res.name == "Admin User"
        assert res.auth_type == "jwt_hs256"


def test_auth_hs256_jwt_with_google_client_secret_fastmcp_token_success():
    from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key

    client_secret = "google-oauth-client-secret-xyz123-very-secure-32bytes"
    signing_key = derive_jwt_key(
        high_entropy_material=client_secret, salt="fastmcp-jwt-signing-key"
    )
    issuer = JWTIssuer(
        issuer="http://localhost:8080",
        audience="http://localhost:8080/mcp",
        signing_key=signing_key,
    )
    token = issuer.issue_access_token(
        client_id="admin@cspaez.org",
        scopes=["openid", "email"],
        jti="sample-jti-uuid",
        upstream_claims={"email": "admin@cspaez.org", "name": "Admin FastMCP"},
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.google_client_secret", client_secret
        ),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails",
            ["admin@cspaez.org"],
        ),
    ):
        res = verifier.verify(token)
        assert res.authenticated is True
        assert res.user == "admin@cspaez.org"
        assert res.name == "Admin FastMCP"
        assert res.auth_type == "jwt_hs256"


def test_auth_hs256_jwt_with_service_token_secret_success():
    import jwt

    srv_secret = "shared-service-token-hmac-key-32bytes-long-secret"
    token = jwt.encode(
        {"user": "lyoko-agent", "role": "remediator"},
        srv_secret,
        algorithm="HS256",
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.service_token", srv_secret),
        patch("sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails", []),
    ):
        res = verifier.verify(token)
        assert res.authenticated is True
        assert res.user == "lyoko-agent"
        assert res.auth_type == "jwt_hs256"


def test_auth_hs256_jwt_unauthorized_email():
    import jwt

    secret = "my-custom-jwt-secret-at-least-32-bytes-long-now"
    token = jwt.encode(
        {"email": "unauthorized@gmail.com", "name": "Unauthorized User"},
        secret,
        algorithm="HS256",
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.jwt_secret", secret),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails",
            ["admin@cspaez.org"],
        ),
        pytest.raises(AuthenticationError) as exc,
    ):
        verifier.verify(token)
    assert "not in the allowed emails list" in str(exc.value)


def test_auth_hs256_jwt_expired_raises_error():
    import time

    import jwt

    secret = "my-custom-jwt-secret-at-least-32-bytes-long-now"
    token = jwt.encode(
        {"email": "admin@cspaez.org", "exp": int(time.time()) - 100},
        secret,
        algorithm="HS256",
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.jwt_secret", secret),
        pytest.raises(AuthenticationError) as exc,
    ):
        verifier.verify(token)
    assert "expired" in str(exc.value).lower()


def test_auth_hs256_jwt_invalid_signature_raises_error():
    import jwt

    token = jwt.encode(
        {"email": "admin@cspaez.org"},
        "wrong-secret-key-with-at-least-32-bytes-for-hmac",
        algorithm="HS256",
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch(
            "sector5_mcp.infrastructure.auth.google.settings.jwt_secret",
            "correct-secret-key-with-at-least-32-bytes-hmac",
        ),
        pytest.raises(AuthenticationError) as exc,
    ):
        verifier.verify(token)
    assert "Invalid HS256 signature" in str(exc.value)


def test_auth_hs256_jwt_no_secrets_configured_raises_error():
    import jwt

    token = jwt.encode(
        {"email": "admin@cspaez.org"},
        "some-secret-key-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )

    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.jwt_secret", ""),
        patch("sector5_mcp.infrastructure.auth.google.settings.google_client_secret", ""),
        patch("sector5_mcp.infrastructure.auth.google.settings.service_token", ""),
        pytest.raises(AuthenticationError) as exc,
    ):
        verifier.verify(token)
    assert "No HMAC secret key configured" in str(exc.value)


@pytest.mark.asyncio
async def test_gateway_token_verifier_with_hs256_token():
    from unittest.mock import MagicMock

    import jwt
    from sector5_mcp.application.service import MCPGatewayService
    from sector5_mcp.infrastructure.mcp.auth import GatewayTokenVerifier

    secret = "mcp-shared-secret-key-1234567890-at-least-32-chars"
    token = jwt.encode(
        {"email": "admin@cspaez.org", "name": "Admin Paez"},
        secret,
        algorithm="HS256",
    )

    service = MagicMock(spec=MCPGatewayService)
    verifier = GoogleAuthVerifier()
    with (
        patch("sector5_mcp.infrastructure.auth.google.settings.auth_enabled", True),
        patch("sector5_mcp.infrastructure.auth.google.settings.jwt_secret", secret),
        patch("sector5_mcp.infrastructure.auth.google.settings.allowed_google_emails", []),
    ):
        service.verify_access.side_effect = verifier.verify
        gateway_verifier = GatewayTokenVerifier(service)
        access_token = await gateway_verifier.verify_token(token)

        assert access_token is not None
        assert access_token.client_id == "admin@cspaez.org"
        assert access_token.token == token


def test_build_auth_provider_requests_google_offline_refresh_token():
    """Google needs access_type=offline (+ prompt=consent) to hand back a refresh token."""
    from unittest.mock import MagicMock

    from sector5_mcp.infrastructure.mcp import auth as auth_module

    settings = MagicMock()
    settings.auth_enabled = True
    settings.google_client_id = "client-id.apps.googleusercontent.com"
    settings.google_client_secret = "client-secret-xyz"
    settings.allowed_google_emails = ["admin@cspaez.org"]
    settings.base_url = "https://mcp.cspaez.org"
    settings.redirect_path = "/oauth/callback"

    with (
        patch.object(auth_module, "settings", settings),
        patch.object(auth_module, "OIDCProxy") as mock_proxy,
        patch.object(auth_module, "MultiAuth") as mock_multi,
    ):
        auth_module.build_auth_provider(MagicMock())

    assert mock_proxy.called
    extra = mock_proxy.call_args.kwargs["extra_authorize_params"]
    assert extra["access_type"] == "offline"
    assert extra["prompt"] == "consent"
    assert mock_multi.called
