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
