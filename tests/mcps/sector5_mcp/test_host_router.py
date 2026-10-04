"""Unit tests for multi-host ASGI dispatch in sector5-mcp."""

from sector5_mcp.infrastructure.mcp.host_router import (
    HostRouter,
    build_host_router,
    host_from_base_url,
)
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _make_app(label: str) -> Starlette:
    async def endpoint(request):
        return PlainTextResponse(label)

    return Starlette(routes=[Route("/", endpoint)])


def test_host_from_base_url_strips_scheme_path_and_port():
    assert host_from_base_url("https://mcp.cspaez.org/") == "mcp.cspaez.org"
    assert host_from_base_url("http://localhost:8080") == "localhost"
    assert host_from_base_url("https://MCP.Internal.Cspaez.org:8443/mcp") == (
        "mcp.internal.cspaez.org"
    )


def test_host_router_dispatches_by_host_header():
    internal = _make_app("internal")
    public = _make_app("public")
    router = HostRouter(apps={"mcp.internal.cspaez.org": internal}, default=public)

    with TestClient(router) as client:
        assert client.get("/", headers={"host": "mcp.internal.cspaez.org"}).text == "internal"
        assert client.get("/", headers={"host": "mcp.cspaez.org"}).text == "public"


def test_host_router_falls_back_to_canonical_for_unknown_host():
    public = _make_app("public")
    router = HostRouter(apps={}, default=public)

    with TestClient(router) as client:
        assert client.get("/", headers={"host": "unknown.example"}).text == "public"


def test_build_host_router_maps_each_base_url():
    internal = _make_app("internal")
    public = _make_app("public")
    router = build_host_router(
        {
            "https://mcp.cspaez.org": public,
            "https://mcp.internal.cspaez.org": internal,
        },
        canonical_base_url="https://mcp.cspaez.org",
    )

    assert set(router.apps) == {"mcp.cspaez.org", "mcp.internal.cspaez.org"}
    with TestClient(router) as client:
        assert client.get("/", headers={"host": "mcp.internal.cspaez.org"}).text == "internal"
