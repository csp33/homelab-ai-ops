"""Unit tests for multi BASE_URL configuration in sector5-mcp."""

from sector5_mcp.config import GatewaySettings


def test_base_urls_parses_json_list():
    settings = GatewaySettings(
        base_urls='["https://mcp.example.com","https://mcp.internal.example.com"]'
    )
    assert settings.base_urls == [
        "https://mcp.example.com",
        "https://mcp.internal.example.com",
    ]


def test_base_urls_parses_comma_separated():
    settings = GatewaySettings(base_urls="https://a.example, https://b.example")
    assert settings.base_urls == ["https://a.example", "https://b.example"]


def test_public_and_canonical_urls_are_normalized_and_deduped():
    settings = GatewaySettings(
        base_urls=[
            "https://mcp.example.com/",
            "https://mcp.internal.example.com/",
            "https://mcp.example.com",
        ],
    )
    assert settings.public_base_urls == [
        "https://mcp.example.com",
        "https://mcp.internal.example.com",
    ]
    assert settings.canonical_base_url == "https://mcp.example.com"


def test_legacy_base_url_env_still_supported(monkeypatch):
    monkeypatch.delenv("BASE_URLS", raising=False)
    monkeypatch.setenv("BASE_URL", "https://mcp.example.com")
    settings = GatewaySettings(_env_file=None)
    assert settings.public_base_urls == ["https://mcp.example.com"]


def test_base_urls_env_takes_precedence_over_legacy(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://legacy.example")
    monkeypatch.setenv("BASE_URLS", "https://mcp.example.com,https://mcp.internal.example.com")
    settings = GatewaySettings(_env_file=None)
    assert settings.public_base_urls == [
        "https://mcp.example.com",
        "https://mcp.internal.example.com",
    ]
