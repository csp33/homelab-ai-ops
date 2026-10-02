"""Unit tests for LYOKO observability and Langfuse tracer implementation."""

from unittest.mock import patch

from lyoko.domain.interfaces.tracer import TracerInterface
from lyoko.infrastructure.observability.langfuse import LangfuseTracer


def test_tracer_implements_interface():
    tracer = LangfuseTracer()
    assert isinstance(tracer, TracerInterface)


def test_langfuse_tracer_disabled_when_keys_missing():
    tracer = LangfuseTracer(public_key="", secret_key="")
    assert tracer.get_callback_handler() is None


def test_langfuse_tracer_enabled_when_keys_present():
    with patch("langfuse.Langfuse"):
        tracer = LangfuseTracer(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="https://cloud.langfuse.com",
        )
        callback = tracer.get_callback_handler()
        assert callback is not None
        assert callback.__class__.__name__ == "LangchainCallbackHandler"


def test_langfuse_tracer_get_trace_config_with_session_and_user():
    with patch("langfuse.Langfuse"):
        tracer = LangfuseTracer(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="https://cloud.langfuse.com",
        )
        config = tracer.get_trace_config(
            session_id="incident-xyz123",
            user_id="alert:OOMKilled",
            trace_name="lyoko-OOMKilled-radarr-xxx",
            tags=["lyoko", "ns:media", "alert:OOMKilled"],
            metadata={"pod_name": "radarr-xxx", "custom": "value"},
        )
        assert config is not None
        assert "callbacks" in config
        assert len(config["callbacks"]) == 1
        assert config["tags"] == ["lyoko", "ns:media", "alert:OOMKilled"]
        assert config["run_name"] == "lyoko-OOMKilled-radarr-xxx"
        assert config["metadata"]["langfuse_session_id"] == "incident-xyz123"
        assert config["metadata"]["langfuse_user_id"] == "alert:OOMKilled"
        assert config["metadata"]["langfuse_trace_name"] == "lyoko-OOMKilled-radarr-xxx"
        assert config["metadata"]["langfuse_tags"] == ["lyoko", "ns:media", "alert:OOMKilled"]
        assert config["metadata"]["pod_name"] == "radarr-xxx"
        assert config["metadata"]["custom"] == "value"


def test_langfuse_tracer_get_trace_config_when_disabled():
    tracer = LangfuseTracer(public_key="", secret_key="")
    config = tracer.get_trace_config(
        session_id="incident-xyz",
        trace_name="test-run",
        tags=["lyoko"],
        metadata={"pod": "test"},
    )
    assert config == {
        "tags": ["lyoko"],
        "metadata": {
            "pod": "test",
            "langfuse_session_id": "incident-xyz",
            "langfuse_trace_name": "test-run",
            "langfuse_tags": ["lyoko"],
        },
        "run_name": "test-run",
    }
