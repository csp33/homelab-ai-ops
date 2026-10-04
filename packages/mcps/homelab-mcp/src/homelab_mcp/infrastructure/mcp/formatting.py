"""Context-efficiency helpers for gateway tool responses."""

from typing import Any

_MAX_DESCRIPTION = 160
_MAX_STRING_CONTENT = 12000
_MAX_LIST_CONTENT = 60


def lean_tool_index(tools: list[Any]) -> list[dict[str, Any]]:
    """Reduce tool definitions to a lean index for prompt/context efficiency."""
    results = []
    for t in tools:
        desc = (t.description or "").strip()
        first_line = desc.split("\n")[0].strip()
        short_desc = (
            first_line[:_MAX_DESCRIPTION] + "..."
            if len(first_line) > _MAX_DESCRIPTION
            else first_line
        )
        results.append(
            {
                "name": t.name,
                "description": short_desc,
                "upstream": str(t.upstream_type),
            }
        )
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
