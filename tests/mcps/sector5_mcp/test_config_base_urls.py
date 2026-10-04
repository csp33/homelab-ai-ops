"""Unit tests for multi BASE_URL configuration in sector5-mcp."""

from sector5_mcp.config import GatewaySettings


def test_base_urls_parses_json_list():
    settings = GatewaySettings(
        base_url="https://mcp.cspaez.org",
        base_urls='["https://mcp.internal.cspaez.org"]',
    )
    assert settings.base_urls == ["https://mcp.internal.cspaez.org"]


def test_base_urls_parses_comma_separated():
    settings = GatewaySettings(
        base_url="https://mcp.cspaez.org",
        base_urls="https://a.example, https://b.example",
    )
    assert settings.base_urls == ["https://a.example", "https://b.example"]


def test_effective_base_urls_includes_canonical_first_and_dedupes():
    settings = GatewaySettings(
        base_url="https://mcp.cspaez.org/",
        base_urls=["https://mcp.internal.cspaez.org/", "https://mcp.cspaez.org"],
    )
    assert settings.effective_base_urls == [
        "https://mcp.cspaez.org",
        "https://mcp.internal.cspaez.org",
    ]


def test_effective_base_urls_defaults_to_canonical_only():
    settings = GatewaySettings(base_url="http://localhost:8080", base_urls=[])
    assert settings.effective_base_urls == ["http://localhost:8080"]
