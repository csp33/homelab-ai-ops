"""Host-based ASGI dispatcher serving one FastMCP app per public BASE_URL.

FastMCP bakes the OAuth issuer, discovery endpoints, JWT audience, and the
RFC 9728 ``resource_metadata`` URL into an app when it is created, so a single
process cannot satisfy several public hostnames with one app. Instead we build
one FastMCP server (and HTTP app) per configured BASE_URL and route each request
to the app whose host matches the incoming ``Host`` header.
"""

import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("sector5_mcp.host_router")

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def host_from_base_url(base_url: str) -> str:
    """Extract the lowercase hostname (no port) from a base URL."""
    without_scheme = base_url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].split(":")[0].strip().lower()


def _host_from_scope(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"host":
            return value.decode("latin-1").split(":")[0].strip().lower()
    return None


class HostRouter:
    """Dispatch each request to the per-host FastMCP ASGI app.

    Requests whose Host is unknown fall back to ``default`` (the canonical app).
    The lifespan protocol is forwarded to every distinct sub-app exactly once.
    """

    def __init__(self, apps: dict[str, ASGIApp], default: ASGIApp):
        self._apps = apps
        self._default = default
        self.state = SimpleNamespace(path="")

        unique: list[ASGIApp] = []
        seen: set[int] = set()
        for app in [*apps.values(), default]:
            if id(app) not in seen:
                seen.add(id(app))
                unique.append(app)
        self._lifespan_apps = unique

    @property
    def apps(self) -> dict[str, ASGIApp]:
        return self._apps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._serve_lifespan(receive, send)
            return

        host = _host_from_scope(scope)
        app = self._apps.get(host) if host else None
        if app is None:
            logger.debug("Host '%s' is not mapped; falling back to canonical app", host)
            app = self._default
        await app(scope, receive, send)

    async def _serve_lifespan(self, receive: Receive, send: Send) -> None:
        async with AsyncExitStack() as stack:
            for app in self._lifespan_apps:
                await stack.enter_async_context(app.router.lifespan_context(app))
            message = await receive()
            if message["type"] != "lifespan.startup":
                return
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            if message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})


def build_host_router(apps_by_base_url: dict[str, ASGIApp], canonical_base_url: str) -> HostRouter:
    """Map every configured BASE_URL's hostname to its app."""
    apps = {host_from_base_url(base_url): app for base_url, app in apps_by_base_url.items()}
    return HostRouter(apps=apps, default=apps_by_base_url[canonical_base_url])
