"""FastMCP Gateway Server exposing aggregated upstream tools."""

import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, MultiAuth, TokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from homelab_mcp.application.service import MCPGatewayService
from homelab_mcp.config import settings
from homelab_mcp.infrastructure.auth.google import GoogleJWTVerifier

logger = logging.getLogger("homelab_mcp.gateway_server")


class GatewayTokenVerifier(TokenVerifier):
    """FastMCP TokenVerifier bridging FastMCP auth to Domain AuthVerifier."""

    def __init__(self, service: MCPGatewayService):
        super().__init__()
        self.service = service

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            identity = self.service.verify_access(token)
            if identity.authenticated:
                return AccessToken(
                    token=token,
                    client_id=identity.user,
                    scopes=[],
                    expires_at=None,
                )
        except Exception as exc:
            logger.warning(f"FastMCP authentication rejected: {exc}")
            return None
        return None


def create_gateway_mcp_server(service: MCPGatewayService) -> FastMCP:
    """Create FastMCP Gateway server aggregating upstream tools."""
    auth_provider = None
    if settings.auth_enabled:
        token_verifier = GatewayTokenVerifier(service)
        if settings.google_client_id and settings.google_client_secret:
            allowed_emails = (
                settings.allowed_google_emails
                if isinstance(settings.allowed_google_emails, list)
                else [settings.allowed_google_emails]
            )
            google_verifier = GoogleJWTVerifier(
                jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
                issuer="https://accounts.google.com",
                audience=settings.google_client_id,
                allowed_emails=allowed_emails,
            )
            oidc_proxy = OIDCProxy(
                config_url="https://accounts.google.com/.well-known/openid-configuration",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                base_url=settings.base_url,
                redirect_path=settings.redirect_path,
                verify_id_token=True,
                valid_scopes=["openid", "email", "profile"],
                extra_authorize_params={"scope": "openid email profile"},
                token_verifier=google_verifier,
            )
            auth_provider = MultiAuth(
                server=oidc_proxy,
                verifiers=[token_verifier],
            )
        else:
            auth_provider = token_verifier

    mcp = FastMCP("homelab-mcp-gateway", auth=auth_provider)
    mcp.add_middleware(
        ResponseCachingMiddleware(
            list_tools_settings={"enabled": True, "ttl": 300},
            call_tool_settings={"enabled": False},
        )
    )

    @mcp.tool()
    async def gateway_list_tools() -> list[dict[str, Any]]:
        """List all tools aggregated from upstream MCP servers (Home Assistant, UniFi, Kubernetes)."""
        tools = await service.discover_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "upstream": str(t.upstream_type),
                "parameters": t.parameters,
            }
            for t in tools
        ]

    @mcp.tool()
    async def gateway_call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute any tool across the connected upstream MCP servers with authentication and guardrails.

        Args:
            tool_name: Name of the upstream tool to invoke.
            arguments: Dictionary of arguments matching the tool schema.
        """
        result = await service.execute_tool(tool_name, arguments)
        return {
            "status": result.status,
            "content": result.content,
            "is_error": result.is_error,
        }

    return mcp
