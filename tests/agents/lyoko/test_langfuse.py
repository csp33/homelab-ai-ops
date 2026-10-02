"""Tests for Langfuse observability callback handler factory in LYOKO."""

from lyoko.infrastructure.observability.langfuse import get_langfuse_callback_handler
from pydantic import SecretStr


def test_langfuse_disabled_returns_none(monkeypatch):
    """When langfuse_enabled is False, get_langfuse_callback_handler should return None."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", False)
    handler = get_langfuse_callback_handler()
    assert handler is None


def test_langfuse_enabled_initialization(monkeypatch):
    """When langfuse_enabled is True and keys are provided, it returns a CallbackHandler."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", True)
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", "sk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_host", "https://cloud.langfuse.com")

    handler = get_langfuse_callback_handler()
    assert handler is not None


def test_langfuse_enabled_with_secret_str(monkeypatch):
    """When langfuse_secret_key is a Pydantic SecretStr, handler is initialized correctly."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", True)
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", SecretStr("sk-lf-test"))
    monkeypatch.setattr("lyoko.config.settings.langfuse_host", "https://cloud.langfuse.com")

    handler = get_langfuse_callback_handler()
    assert handler is not None


def test_langfuse_missing_keys_returns_none(monkeypatch):
    """When langfuse_enabled is True but keys are missing, return None and do not crash."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", True)
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", None)
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", None)

    handler = get_langfuse_callback_handler()
    assert handler is None

    # Test with public key only
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", None)
    handler = get_langfuse_callback_handler()
    assert handler is None

    # Test with secret key only
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", None)
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", SecretStr("sk-lf-test"))
    handler = get_langfuse_callback_handler()
    assert handler is None


def test_langfuse_initialization_exception_returns_none(monkeypatch):
    """When an unexpected exception occurs during handler creation, return None safely."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", True)
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", "sk-lf-test")

    def broken_handler(*args, **kwargs):
        raise RuntimeError("Langfuse server connection failed")

    monkeypatch.setattr(
        "lyoko.infrastructure.observability.langfuse.LangfuseTracer.get_callback_handler",
        broken_handler,
    )

    handler = get_langfuse_callback_handler()
    assert handler is None


def test_get_langfuse_trace_config_disabled(monkeypatch):
    """When langfuse is disabled, get_langfuse_trace_config returns empty dict."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", False)
    from lyoko.infrastructure.observability.langfuse import get_langfuse_trace_config

    cfg = get_langfuse_trace_config(session_id="s123", user_id="u456")
    assert cfg == {}


def test_get_langfuse_trace_config_enabled(monkeypatch):
    """When langfuse is enabled, get_langfuse_trace_config returns config with metadata and callbacks."""
    monkeypatch.setattr("lyoko.config.settings.langfuse_enabled", True)
    monkeypatch.setattr("lyoko.config.settings.langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_secret_key", "sk-lf-test")
    monkeypatch.setattr("lyoko.config.settings.langfuse_host", "https://cloud.langfuse.com")
    from lyoko.infrastructure.observability.langfuse import get_langfuse_trace_config

    cfg = get_langfuse_trace_config(
        session_id="telegram-12345",
        user_id="user-999",
        trace_name="chat-trace",
        tags=["tg", "chat"],
        metadata={"extra": "val"},
    )
    assert "callbacks" in cfg
    assert len(cfg["callbacks"]) == 1
    assert cfg["metadata"]["langfuse_session_id"] == "telegram-12345"
    assert cfg["metadata"]["langfuse_user_id"] == "user-999"
    assert cfg["metadata"]["langfuse_trace_name"] == "chat-trace"
    assert cfg["metadata"]["langfuse_tags"] == ["tg", "chat"]
    assert cfg["metadata"]["extra"] == "val"
    assert cfg["run_name"] == "chat-trace"
    assert cfg["tags"] == ["tg", "chat"]
