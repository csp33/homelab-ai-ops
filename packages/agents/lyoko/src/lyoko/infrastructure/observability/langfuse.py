"""Langfuse implementation of tracer interface and callback handler factory."""

import logging
from typing import Any

from lyoko.config import settings
from lyoko.domain.interfaces.tracer import TracerInterface, null_span

logger = logging.getLogger("lyoko.observability.langfuse")


class LangfuseTracer(TracerInterface):
    """Encapsulates Langfuse client lifecycle and callback generation."""

    def __init__(
        self,
        public_key: str = "",
        secret_key: str = "",
        host: str = "https://cloud.langfuse.com",
        environment: str = "local",
        release: str | None = None,
    ) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host
        self._environment = environment
        self._release = release
        self._client: Any | None = None
        self._enabled = bool(public_key and secret_key)

        if self._enabled:
            self._init_client()

    def _init_client(self) -> None:
        try:
            import os

            from langfuse import Langfuse

            if self._public_key:
                os.environ["LANGFUSE_PUBLIC_KEY"] = self._public_key
            if self._secret_key:
                os.environ["LANGFUSE_SECRET_KEY"] = self._secret_key
            if self._host:
                os.environ["LANGFUSE_HOST"] = self._host
            if self._environment:
                os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = self._environment

            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host,
                environment=self._environment,
                release=self._release,
            )
            logger.info(
                "Langfuse client initialized successfully with env '%s'.", self._environment
            )
        except Exception as exc:
            logger.warning(f"Failed to initialize Langfuse client: {exc}")
            self._enabled = False

    def get_callback_handler(self) -> Any | None:
        """Return a Langfuse CallbackHandler if enabled, else None."""
        if not self._enabled:
            return None

        try:
            from langfuse.langchain import CallbackHandler

            return CallbackHandler(public_key=self._public_key)
        except Exception as exc:
            logger.warning(f"Failed to create Langfuse callback handler: {exc}")
            return None

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> Any:
        """Open a named span in the current trace; a no-op when tracing is disabled."""
        if not self._enabled or self._client is None:
            return null_span()
        try:
            return self._client.start_as_current_observation(
                as_type="span", name=name, metadata=metadata or {}
            )
        except Exception as exc:
            logger.debug("Failed to start Langfuse span '%s': %s", name, exc)
            return null_span()

    def get_trace_config(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a LangChain / LangGraph RunnableConfig dict with Langfuse tracing, session, and metadata."""
        config: dict[str, Any] = {}
        handler = self.get_callback_handler()
        if handler:
            config["callbacks"] = [handler]

        effective_tags = list(tags or [])
        env_tag = f"env:{self._environment}"
        if env_tag not in effective_tags:
            effective_tags.append(env_tag)

        meta: dict[str, Any] = dict(metadata or {})
        meta["environment"] = self._environment
        if session_id:
            meta["langfuse_session_id"] = str(session_id)
        if user_id:
            meta["langfuse_user_id"] = str(user_id)
        if trace_name:
            meta["langfuse_trace_name"] = str(trace_name)
        if effective_tags:
            meta["langfuse_tags"] = [str(t) for t in effective_tags]

        if meta:
            config["metadata"] = meta
        if effective_tags:
            config["tags"] = [str(t) for t in effective_tags]
        if trace_name:
            config["run_name"] = str(trace_name)

        return config


def get_langfuse_callback_handler() -> Any | None:
    """Create and return a Langfuse CallbackHandler if tracing is enabled and configured."""
    if not settings.langfuse_enabled:
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse is enabled but missing public/secret keys; tracing disabled")
        return None

    try:
        secret_val = (
            settings.langfuse_secret_key.get_secret_value()
            if hasattr(settings.langfuse_secret_key, "get_secret_value")
            else str(settings.langfuse_secret_key)
        )
        tracer = LangfuseTracer(
            public_key=settings.langfuse_public_key,
            secret_key=secret_val,
            host=settings.langfuse_host,
            environment=settings.get_langfuse_environment(),
            release=settings.langfuse_release,
        )
        return tracer.get_callback_handler()
    except Exception as e:
        logger.error("Failed to initialize Langfuse callback handler: %s", e)
        return None


def get_langfuse_trace_config(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    trace_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a full LangChain/LangGraph trace config dict with Langfuse session_id, user_id, tags and metadata."""
    if not settings.langfuse_enabled:
        return {}

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return {}

    try:
        secret_val = (
            settings.langfuse_secret_key.get_secret_value()
            if hasattr(settings.langfuse_secret_key, "get_secret_value")
            else str(settings.langfuse_secret_key)
        )
        tracer = LangfuseTracer(
            public_key=settings.langfuse_public_key,
            secret_key=secret_val,
            host=settings.langfuse_host,
            environment=settings.get_langfuse_environment(),
            release=settings.langfuse_release,
        )
        return tracer.get_trace_config(
            session_id=session_id,
            user_id=user_id,
            trace_name=trace_name,
            tags=tags,
            metadata=metadata,
        )
    except Exception as e:
        logger.error("Failed to build Langfuse trace config: %s", e)
        return {}
