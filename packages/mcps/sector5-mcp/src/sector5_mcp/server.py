"""FastMCP Gateway Composition Root."""

import logging

import uvicorn

from sector5_mcp.application.service import MCPGatewayService
from sector5_mcp.config import settings
from sector5_mcp.domain.models.upstream import UpstreamType
from sector5_mcp.infrastructure.auth.google import GoogleAuthVerifier
from sector5_mcp.infrastructure.mcp.host_router import build_host_router, host_from_base_url
from sector5_mcp.infrastructure.mcp.server import create_gateway_mcp_server
from sector5_mcp.infrastructure.telegram.client import TelegramClient
from sector5_mcp.infrastructure.upstream.client import ProcessUpstreamClient
from sector5_mcp.infrastructure.upstream.kubernetes import KubernetesUpstreamClient
from sector5_mcp.infrastructure.upstream.telegram import TelegramUpstreamClient
from sector5_mcp.infrastructure.upstream.unifi import UnifiUpstreamClient


class HealthEndpointFilter(logging.Filter):
    """Filter out HTTP access log records for health check endpoints (/health, /healthz)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str):
                clean_path = path.split("?")[0].rstrip("/")
                if clean_path in ("/health", "/healthz"):
                    return False
        msg = record.getMessage()
        return not (
            "GET /health" in msg
            or "GET /healthz" in msg
            or "HEAD /health" in msg
            or "HEAD /healthz" in msg
        )


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("uvicorn.access").addFilter(HealthEndpointFilter())
logger = logging.getLogger("sector5_mcp")


def _build_upstreams() -> dict:
    """Assemble the upstream MCP clients from settings."""
    upstreams = {}

    # 1. Home Assistant MCP (github.com/homeassistant-ai/ha-mcp)
    if settings.ha_enabled and settings.hass_token:
        upstreams[UpstreamType.HOME_ASSISTANT] = ProcessUpstreamClient(
            command=settings.ha_command,
            env={
                "HOMEASSISTANT_URL": settings.hass_url,
                "HOMEASSISTANT_TOKEN": settings.hass_token,
                "HASS_HOST": settings.hass_url,
                "HASS_URL": settings.hass_url,
                "HASS_TOKEN": settings.hass_token,
            },
            upstream_type=UpstreamType.HOME_ASSISTANT,
        )

    # 2. UniFi Network MCP (github.com/sirkirby/unifi-mcp)
    if settings.unifi_enabled and settings.unifi_user and settings.unifi_password:
        unifi_host = (
            settings.unifi_url.replace("https://", "")
            .replace("http://", "")
            .split(":")[0]
            .split("/")[0]
        )
        upstreams[UpstreamType.UNIFI] = UnifiUpstreamClient(
            command=settings.unifi_command,
            env={
                "UNIFI_NETWORK_HOST": unifi_host,
                "UNIFI_NETWORK_USERNAME": settings.unifi_user,
                "UNIFI_NETWORK_PASSWORD": settings.unifi_password,
                "UNIFI_NETWORK_SITE": settings.unifi_site,
                "UNIFI_NETWORK_VERIFY_SSL": str(settings.unifi_verify_ssl).lower(),
                "UNIFI_CONTROLLER_URL": settings.unifi_url,
                "UNIFI_HOST": unifi_host,
                "UNIFI_USERNAME": settings.unifi_user,
                "UNIFI_PASSWORD": settings.unifi_password,
                "UNIFI_SITE": settings.unifi_site,
                "UNIFI_VERIFY_SSL": str(settings.unifi_verify_ssl).lower(),
            },
            upstream_type=UpstreamType.UNIFI,
        )

    # 3. Kubernetes MCP (github.com/containers/kubernetes-mcp-server)
    if settings.k8s_enabled:
        k8s_env = {}
        if settings.kubeconfig_path:
            k8s_env["KUBECONFIG"] = settings.kubeconfig_path

        upstreams[UpstreamType.KUBERNETES] = KubernetesUpstreamClient(
            command=settings.k8s_command,
            env=k8s_env,
            upstream_type=UpstreamType.KUBERNETES,
            prefix="k8s_",
        )

    # 4. Grafana MCP (github.com/grafana/mcp-grafana)
    if settings.grafana_enabled and settings.grafana_token:
        upstreams[UpstreamType.GRAFANA] = ProcessUpstreamClient(
            command=settings.grafana_command,
            env={
                "GRAFANA_URL": settings.grafana_url,
                "GRAFANA_SERVICE_ACCOUNT_TOKEN": settings.grafana_token,
                "GRAFANA_TOKEN": settings.grafana_token,
                "GRAFANA_API_KEY": settings.grafana_token,
            },
            upstream_type=UpstreamType.GRAFANA,
            prefix="grafana_",
        )

    # 5. GitHub MCP (github-mcp-server / modelcontextprotocol/server-github)
    if settings.github_enabled and settings.github_token:
        github_env = {
            "GITHUB_PERSONAL_ACCESS_TOKEN": settings.github_token,
            "GITHUB_TOKEN": settings.github_token,
        }
        if settings.github_owner:
            github_env["GITHUB_OWNER"] = settings.github_owner

        upstreams[UpstreamType.GITHUB] = ProcessUpstreamClient(
            command=settings.github_command,
            env=github_env,
            upstream_type=UpstreamType.GITHUB,
            prefix="github_",
        )

    # 6. Telegram Bot Client (in-process provider registered as the 'telegram' domain)
    if settings.telegram_enabled and settings.telegram_bot_token:
        telegram_client = TelegramClient(
            bot_token=settings.telegram_bot_token,
            default_chat_id=settings.telegram_default_chat_id,
        )
        upstreams[UpstreamType.TELEGRAM] = TelegramUpstreamClient(telegram_client)

    return upstreams


def build_gateway_application() -> tuple[MCPGatewayService, any]:
    """Assemble Clean Architecture gateway with upstream MCP servers."""
    gateway_service = MCPGatewayService(
        upstreams=_build_upstreams(), auth_port=GoogleAuthVerifier()
    )
    mcp_app = create_gateway_mcp_server(gateway_service, base_url=settings.base_url)
    return gateway_service, mcp_app


service, mcp = build_gateway_application()


def _allowed_hosts(base_urls: list[str]) -> list[str]:
    """Hostnames (no port) derived from the configured public BASE_URLs."""
    return sorted({host_from_base_url(url) for url in base_urls})


def _serve_http_app(app) -> None:
    config = uvicorn.Config(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        timeout_graceful_shutdown=2,
        lifespan="on",
        log_level="info",
    )
    uvicorn.Server(config).run()


def run_http_gateway(
    gateway_service: MCPGatewayService, canonical_mcp, base_urls: list[str]
) -> None:
    """Serve the gateway over HTTP, one OAuth-aware app per public BASE_URL.

    A single BASE_URL (or disabled auth) keeps the stock FastMCP runner. With
    several BASE_URLs, each host gets its own FastMCP app so OAuth discovery,
    issuer, JWT audience, and the RFC 9728 resource_metadata URL match the exact
    hostname the client used. A :class:`HostRouter` dispatches by Host header.
    """
    allowed = _allowed_hosts(base_urls)
    if len(base_urls) <= 1 or not settings.auth_enabled:
        canonical_mcp.run(
            transport="http",
            host=settings.mcp_host,
            port=settings.mcp_port,
        )
        return

    servers = {base_urls[0]: canonical_mcp}
    for base_url in base_urls[1:]:
        servers[base_url] = create_gateway_mcp_server(
            gateway_service, base_url=base_url, prewarm=False
        )
    apps = {
        base_url: server.http_app(path="/mcp", transport="http", allowed_hosts=allowed)
        for base_url, server in servers.items()
    }
    logger.info(f"Serving gateway for {len(apps)} public BASE_URLs: {', '.join(base_urls)}")
    _serve_http_app(build_host_router(apps, canonical_base_url=base_urls[0]))


def main():
    logging.getLogger("uvicorn.access").addFilter(HealthEndpointFilter())
    logger.info(
        f"Starting sector5-mcp Gateway (transport: {settings.mcp_transport}, "
        f"host: {settings.mcp_host}:{settings.mcp_port})"
    )
    if settings.mcp_transport in ["http", "streamable-http"]:
        run_http_gateway(service, mcp, settings.effective_base_urls)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
