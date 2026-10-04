"""Run-configuration helpers for LLM calls nested in an already traced graph run."""

from typing import Any


def child_config(
    parent_config: dict[str, Any],
    name: str | None,
    tags: list[str] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the run config of a call nested in an already traced graph run.

    Only the callbacks are taken from the parent, so the call becomes a child span of it. The
    rest of the parent config (``configurable``, checkpoint state, recursion limit) belongs to the
    parent graph and must not leak into this one.
    """
    config: dict[str, Any] = {}
    if parent_config.get("callbacks") is not None:
        config["callbacks"] = parent_config["callbacks"]
    if name:
        config["run_name"] = name
    if tags:
        config["tags"] = list(tags)
    if metadata:
        config["metadata"] = dict(metadata)
    return config
