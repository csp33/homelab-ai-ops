"""Langfuse implementation of tracer interface."""

import logging
from typing import Any

from lyoko.domain.interfaces.tracer import TracerInterface

logger = logging.getLogger("lyoko.observability.langfuse")


class LangfuseTracer(TracerInterface):
    """Encapsulates Langfuse client lifecycle and callback generation."""

    def __init__(
        self,
        public_key: str = "",
        secret_key: str = "",
        host: str = "https://cloud.langfuse.com",
    ) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host
        self._client: Any | None = None
        self._enabled = bool(public_key and secret_key)

        if self._enabled:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host,
            )
            logger.info("Langfuse client initialized successfully.")
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

    def get_trace_config(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a LangChain / LangGraph RunnableConfig dict with Langfuse tracing, session, and metadata.

        Args:
            session_id: Session identifier to group traces into conversational threads or incident runs.
            user_id: User or actor identifier.
            trace_name: Custom name for the root trace.
            tags: List of tags for categorizing traces in Langfuse.
            metadata: Custom key-value metadata.

        Returns:
            RunnableConfig dict configured with Langfuse callback, tags, and session metadata.
        """
        config: dict[str, Any] = {}
        handler = self.get_callback_handler()
        if handler:
            config["callbacks"] = [handler]

        meta: dict[str, Any] = dict(metadata or {})
        if session_id:
            meta["langfuse_session_id"] = session_id
        if user_id:
            meta["langfuse_user_id"] = user_id
        if trace_name:
            meta["langfuse_trace_name"] = trace_name
        if tags:
            meta["langfuse_tags"] = list(tags)

        if meta:
            config["metadata"] = meta
        if tags:
            config["tags"] = list(tags)
        if trace_name:
            config["run_name"] = trace_name

        return config
