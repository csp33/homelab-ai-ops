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
from homelab_mcp.domain.interfaces.telegram import TelegramClientInterface
from homelab_mcp.domain.models.telegram import (
    TelegramAlertRequest,
    TelegramMessageRequest,
    TelegramReactionRequest,
    TelegramSeverity,
)
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


def create_gateway_mcp_server(
    service: MCPGatewayService,
    telegram_client: TelegramClientInterface | None = None,
) -> FastMCP:
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

    mcp = FastMCP("homelab-mcp-gateway", auth=auth_provider, lifespan=server_lifespan)
    mcp.add_middleware(
        ResponseCachingMiddleware(
            list_tools_settings={"enabled": True, "ttl": 300},
            call_tool_settings={"enabled": False},
        )
    )

    @mcp.tool()
    async def gateway_list_categories() -> list[dict[str, Any]]:
        """List all connected upstream MCP categories and their available tool counts."""
        tools = await service.discover_tools()
        counts: dict[str, int] = {}
        for t in tools:
            key = str(t.upstream_type)
            counts[key] = counts.get(key, 0) + 1
        return [{"upstream": k, "tool_count": v} for k, v in sorted(counts.items())]

    @mcp.tool()
    async def gateway_list_tools(
        query: str | None = None,
        upstream: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """List operational tools aggregated from connected upstream MCP servers with optional keyword search and category filtering.

        Args:
            query: Optional keyword to search tool names and descriptions (e.g. 'client', 'pod', 'light', 'blind').
            upstream: Optional upstream name to filter tools by category (e.g. 'homeassistant', 'unifi', 'kubernetes', 'grafana', 'github').
            limit: Maximum number of tools to return (default: 25, max: 50).
        """
        tools = await service.discover_tools()
        if upstream:
            target = upstream.strip().lower()
            tools = [
                t
                for t in tools
                if target == str(t.upstream_type).lower()
                or target in str(t.upstream_type).lower()
                or target in t.name.lower()
            ]

        if query:
            q = query.strip().lower()
            tools = [
                t
                for t in tools
                if q in t.name.lower()
                or (t.description and q in t.description.lower())
                or (t.upstream_type and q in str(t.upstream_type).lower())
            ]

        bounded_limit = max(1, min(limit, 50))
        results = []
        for t in tools[:bounded_limit]:
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
    async def gateway_get_tool_schema(tool_name: str) -> dict[str, Any]:
        """Get the full parameter schema and detailed description for a specific operational tool.

        Args:
            tool_name: The exact name of the tool to inspect.
        """
        tools = await service.discover_tools()
        for t in tools:
            if t.name == tool_name:
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
        # Truncate excessively large strings or collections to avoid blowing LLM context windows
        if isinstance(content, str) and len(content) > 12000:
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

    if telegram_client is not None:

        @mcp.tool()
        async def telegram_send_message(
            text: str,
            chat_id: str | None = None,
            parse_mode: str = "Markdown",
            reply_to_message_id: int | str | None = None,
        ) -> dict[str, Any]:
            """Send a text message to Telegram via the configured bot.

            Args:
                text: Message text to send.
                chat_id: Optional target Telegram chat ID (falls back to default if not set).
                parse_mode: Text format parsing mode (e.g. 'Markdown', 'HTML').
                reply_to_message_id: Optional message ID to reply to directly.
            """
            request = TelegramMessageRequest(
                text=text,
                chat_id=chat_id,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_message_id,
            )
            return await telegram_client.send_message(request)

        @mcp.tool()
        async def telegram_set_reaction(
            message_id: int,
            emoji: str = "👀",
            chat_id: str | None = None,
        ) -> dict[str, Any]:
            """Set an emoji reaction on a message in Telegram.

            Args:
                message_id: The ID of the Telegram message to react to.
                emoji: Emoji string to react with (e.g. '👀', '⚡', '👍', '🔥', '🎉').
                chat_id: Optional target Telegram chat ID (falls back to default if not set).
            """
            request = TelegramReactionRequest(
                message_id=message_id,
                emoji=emoji,
                chat_id=chat_id,
            )
            return await telegram_client.set_reaction(request)

        @mcp.tool()
        async def telegram_send_alert(
            title: str,
            message: str,
            severity: str = "warning",
            chat_id: str | None = None,
        ) -> dict[str, Any]:
            """Send a formatted alert message with severity indicator to Telegram.

            Args:
                title: Alert title.
                message: Alert description or message body.
                severity: Severity level ('info', 'warning', 'critical', 'ok').
                chat_id: Optional target Telegram chat ID (falls back to default if not set).
            """
            if isinstance(severity, TelegramSeverity):
                parsed_severity = severity
            elif isinstance(severity, str):
                try:
                    parsed_severity = TelegramSeverity(severity.lower())
                except ValueError:
                    parsed_severity = TelegramSeverity.WARNING
            else:
                parsed_severity = TelegramSeverity.WARNING

            request = TelegramAlertRequest(
                title=title,
                message=message,
                severity=parsed_severity,
                chat_id=chat_id,
            )
            return await telegram_client.send_alert(request)

    return mcp
