"""Context-efficiency helpers for gateway tool responses."""

from typing import Any

_MAX_DESCRIPTION = 160
_MAX_STRING_CONTENT = 12000
_MAX_LIST_CONTENT = 60


def tool_index(tools: list[Any]) -> list[dict[str, Any]]:
    """Reduce tool definitions to an index entry with description and raw JSON schema.

    The parameter schema is always included so an agent never has to guess argument names
    behind a generic call, and never needs a separate schema round-trip.
    """
    results = []
    for t in tools:
        desc = (t.description or "").strip()
        first_line = desc.split("\n")[0].strip()
        short_desc = (
            first_line[:_MAX_DESCRIPTION] + "..."
            if len(first_line) > _MAX_DESCRIPTION
            else first_line
        )
        entry: dict[str, Any] = {
            "name": t.name,
            "description": short_desc,
            "upstream": str(t.upstream_type),
            "parameters": t.parameters or {"type": "object", "properties": {}},
        }
        # Only surface the hint when the upstream declared one, so a missing key means
        # "unknown" rather than being mistaken for an explicit "not read-only".
        read_only = getattr(t, "read_only", None)
        if read_only is not None:
            entry["read_only_hint"] = read_only
        results.append(entry)
    return results


def shape_tool_content(content: Any, is_error: bool) -> Any:
    """Normalize and truncate tool output to keep LLM context windows lean."""
    if (content is None or content == "" or content == [] or content == {}) and not is_error:
        return "No resources found or empty result."

    if isinstance(content, str) and len(content) > _MAX_STRING_CONTENT:
        return (
            content[:_MAX_STRING_CONTENT]
            + f"\n... [Output truncated. Total characters: {len(content)}]"
        )

    if isinstance(content, list) and len(content) > _MAX_LIST_CONTENT:
        return content[:_MAX_LIST_CONTENT] + [
            f"... [{len(content) - _MAX_LIST_CONTENT} more items truncated to maintain lean context]"
        ]

    return content
