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
