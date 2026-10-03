"""Heuristic relevance scoring engine for MCP tools."""

import re

from homelab_mcp.domain.models.upstream import ToolDefinition

READ_PREFIXES: tuple[str, ...] = (
    "get_",
    "list_",
    "top_",
    "describe_",
    "inspect_",
    "show_",
    "fetch_",
    "find_",
)

MUTATION_PREFIXES: tuple[str, ...] = (
    "create_",
    "delete_",
    "block_",
    "unblock_",
    "update_",
    "set_",
    "apply_",
    "remove_",
    "restart_",
    "patch_",
    "authorize_",
    "forget_",
    "force_",
    "reconnect_",
)

MUTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "create",
        "delete",
        "block",
        "unblock",
        "remove",
        "update",
        "set",
        "restart",
        "patch",
        "modify",
        "kill",
        "reconnect",
        "authorize",
        "forget",
    }
)


def score_tool(tool: ToolDefinition, query_tokens: list[str], raw_query_clean: str) -> float:
    """Calculate a relevance score for a tool against a query and token list."""
    name_lower = tool.name.lower()
    desc_lower = (tool.description or "").lower()
    upstream_lower = str(tool.upstream_type or "").lower()
    name_words = set(re.findall(r"\w+", name_lower))
    desc_words = set(re.findall(r"\w+", desc_lower))

    score = 0.0

    # Exact full query match
    if name_lower == raw_query_clean:
        score += 100.0
    elif raw_query_clean in name_lower:
        score += 40.0
    elif raw_query_clean in desc_lower:
        score += 20.0

    # Token-level scoring
    matched_tokens = 0
    for token in query_tokens:
        token_matched = False
        if token in name_words:
            score += 15.0
            token_matched = True
        elif token in name_lower:
            score += 8.0
            token_matched = True

        if token in desc_words:
            score += 6.0
            token_matched = True
        elif token in desc_lower:
            score += 2.0
            token_matched = True

        if token in upstream_lower:
            score += 3.0
            token_matched = True

        if token_matched:
            matched_tokens += 1

    # Bonus when multiple tokens match
    if query_tokens and matched_tokens == len(query_tokens):
        score += 25.0 * len(query_tokens)

    # If no tokens or query matched, this tool is irrelevant
    if score == 0.0:
        return 0.0

    # Read vs Mutation Intent
    has_mutation_intent = any(tok in MUTATION_KEYWORDS for tok in query_tokens)
    is_mutation_tool = any(
        name_lower.startswith(p) or f"_{p}" in name_lower for p in MUTATION_PREFIXES
    )
    is_read_tool = any(name_lower.startswith(p) or f"_{p}" in name_lower for p in READ_PREFIXES)

    if has_mutation_intent:
        if is_mutation_tool:
            score += 15.0
    else:
        if is_read_tool:
            score += 15.0
        elif is_mutation_tool:
            score -= 8.0

    return score
