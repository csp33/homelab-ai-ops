"""FastMCP Gateway Composition Root."""

import logging

from homelab_mcp.application.service import MCPGatewayService
from homelab_mcp.config import settings
from homelab_mcp.domain.models import UpstreamType
from homelab_mcp.infrastructure.auth.google import GoogleAuthVerifier
from homelab_mcp.infrastructure.mcp.server import create_gateway_mcp_server
from homelab_mcp.infrastructure.upstream.client import ProcessUpstreamClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("homelab_mcp")


def build_gateway_application() -> tuple[MCPGatewayService, any]:
    """Assemble Clean Architecture gateway with upstream MCP servers."""
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
        upstreams[UpstreamType.UNIFI] = ProcessUpstreamClient(
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

        upstreams[UpstreamType.KUBERNETES] = ProcessUpstreamClient(
            command=settings.k8s_command,
            env=k8s_env,
            upstream_type=UpstreamType.KUBERNETES,
        )

    # 4. GitHub MCP (github-mcp-server / modelcontextprotocol/server-github)
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
        )

    auth_verifier = GoogleAuthVerifier()
    gateway_service = MCPGatewayService(upstreams=upstreams, auth_port=auth_verifier)
    mcp_app = create_gateway_mcp_server(gateway_service)

    return gateway_service, mcp_app


service, mcp = build_gateway_application()


def main():
    logger.info(
        f"Starting homelab-mcp Gateway (transport: {settings.mcp_transport}, "
        f"host: {settings.mcp_host}:{settings.mcp_port})"
    )
    if settings.mcp_transport in ["http", "streamable-http"]:
        mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
