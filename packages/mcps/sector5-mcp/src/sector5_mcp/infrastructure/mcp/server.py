"""FastMCP Gateway Server exposing aggregated upstream tools."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from sector5_mcp.application.service import MCPGatewayService
from sector5_mcp.infrastructure.mcp.auth import build_auth_provider
from sector5_mcp.infrastructure.mcp.tools import register_gateway_tools

logger = logging.getLogger("sector5_mcp.gateway_server")

_GATEWAY_INSTRUCTIONS = (
    "Homelab Tool Gateway. The catalog is grouped into domains. "
    "Discover the tools of one domain with gateway_get_domain_tools(domain), read the exact "
    "arguments of a tool with gateway_get_tool_schema(tool_name), then execute it with "
    "gateway_call_tool(tool_name, arguments). "
    "Available domains: kubernetes, unifi, homeassistant, grafana, github, telegram. "
    "Tools that only read state run immediately; any tool that may change state is subject to "
    "the operator's safety policy."
)


def create_gateway_mcp_server(
    service: MCPGatewayService,
    base_url: str | None = None,
    prewarm: bool = True,
) -> FastMCP:
    """Create FastMCP Gateway server aggregating upstream tools.

    ``base_url`` binds this server's OAuth provider to a specific public host.
    ``prewarm`` controls whether this server triggers the initial upstream tool
    discovery at startup (only the first of several per-host servers should).
    """
    auth_provider = build_auth_provider(service, base_url=base_url)

    @asynccontextmanager
    async def server_lifespan(server: FastMCP):
        if prewarm:
            logger.info("Pre-warming upstream MCP connections and routing table...")
            asyncio.create_task(service.discover_tools())
        yield

    mcp = FastMCP(
        "sector5-mcp-gateway",
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

    register_gateway_tools(mcp, service)
    return mcp
