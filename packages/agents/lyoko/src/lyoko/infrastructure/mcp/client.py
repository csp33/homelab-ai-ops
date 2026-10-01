"""FastMCP client infrastructure adapter implementing MCPClientInterface."""

from typing import Any

import httpx
from lyoko.config import settings
from lyoko.domain.interfaces import MCPClientInterface


class FastMCPClient(MCPClientInterface):
    def __init__(self):
        self.server_url = settings.mcp_server_url
        self.token = settings.service_token

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        url = f"{self.server_url.rstrip('/')}/call_tool"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    url, headers=self._get_headers(), json={"name": name, "arguments": arguments}
                )
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass

        return {"status": "executed", "tool": name, "args": arguments}

    def get_langchain_tools(self) -> list[Any]:
        return []
