"""FastMCP Gateway Server exposing aggregated upstream tools."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, MultiAuth, TokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from homelab_mcp.application.service import MCPGatewayService
from homelab_mcp.config import settings
from homelab_mcp.domain.models.upstream import UpstreamType
from homelab_mcp.infrastructure.auth.google import GoogleJWTVerifier

logger = logging.getLogger("homelab_mcp.gateway_server")

_GATEWAY_INSTRUCTIONS = (
    "Homelab Tool Gateway. The catalog is grouped into domains. "
    "Discover the tools of one domain with gateway_get_domain_tools(domain), read the exact "
    "arguments of a tool with gateway_get_tool_schema(tool_name), then execute it with "
    "gateway_call_tool(tool_name, arguments). "
    "Available domains: kubernetes, unifi, homeassistant, grafana, github, telegram. "
    "Tools that only read state run immediately; any tool that may change state is subject to "
    "the operator's safety policy."
)


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
                jwt_signing_key=settings.google_client_secret,
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

    @asynccontextmanager
    async def server_lifespan(server: FastMCP):
        logger.info("Pre-warming upstream MCP connections and routing table...")
        asyncio.create_task(service.discover_tools())
        yield

    mcp = FastMCP(
        "homelab-mcp-gateway",
        instructions=_GATEWAY_INSTRUCTIONS,
        auth=auth_provider,
        lifespan=server_lifespan,
    )
    mcp.add_middleware(
        ResponseCachingMiddleware(
            list_tools_settings={"enabled": True, "ttl": 300},
            call_tool_settings={"enabled": False},
        )
    )

    def _lean_index(tools: list[Any]) -> list[dict[str, Any]]:
        """Reduce tool definitions to a lean index for prompt/context efficiency."""
        results = []
        for t in tools:
            desc = (t.description or "").strip()
            first_line = desc.split("\n")[0].strip()
            short_desc = first_line[:160] + "..." if len(first_line) > 160 else first_line
            results.append(
                {
                    "name": t.name,
                    "description": short_desc,
                    "upstream": str(t.upstream_type),
                }
            )
        return results

    @mcp.tool()
    async def gateway_get_domain_tools(domain: UpstreamType) -> list[dict[str, Any]]:
        """Return the tool index for one upstream domain.

        Returns every allowed tool of that domain as a lean index (name, one-line description,
        upstream). Use it to discover what exists in a domain, then call
        gateway_get_tool_schema(tool_name) for the exact arguments before executing with
        gateway_call_tool.

        Args:
            domain: Upstream domain (e.g. kubernetes, unifi, homeassistant, grafana, github, telegram).
        """
        tools = await service.get_domain_tools(domain)
        if not tools:
            return [
                {
                    "error": (
                        f"No tools for domain '{str(domain)}'. "
                        "It may be disabled, empty, or not configured."
                    )
                }
            ]
        return _lean_index(tools)

    @mcp.tool()
    async def gateway_get_tool_schema(tool_name: str) -> dict[str, Any]:
        """Get the full parameter schema and detailed description for a specific operational tool.

        Args:
            tool_name: The exact name of the tool to inspect.
        """
        base_name = tool_name.split(".", 1)[1] if "." in tool_name else tool_name
        tools = await service.discover_tools()
        for t in tools:
            if t.name in (tool_name, base_name):
                return {
                    "name": t.name,
                    "description": t.description,
                    "upstream": str(t.upstream_type),
                    "parameters": t.parameters,
                }
        return {"error": f"Tool '{tool_name}' not found."}

    @mcp.tool()
    async def gateway_call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute any tool across the connected upstream MCP servers with authentication and guardrails.

        Args:
            tool_name: Name of the upstream tool to invoke.
            arguments: Dictionary of arguments matching the tool schema.
        """
        result = await service.execute_tool(tool_name, arguments)
        content = result.content
        # Provide clear message on empty results so LLMs do not loop retrying empty queries
        if (
            content is None or content == "" or content == [] or content == {}
        ) and not result.is_error:
            content = "No resources found or empty result."
        # Truncate excessively large strings or collections to avoid blowing LLM context windows
        elif isinstance(content, str) and len(content) > 12000:
            content = (
                content[:12000]
                + f"\n... [Output truncated. Total characters: {len(result.content)}]"
            )
        elif isinstance(content, list) and len(content) > 60:
            content = content[:60] + [
                f"... [{len(result.content) - 60} more items truncated to maintain lean context]"
            ]

        return {
            "status": result.status,
            "content": content,
            "is_error": result.is_error,
        }

    return mcp
