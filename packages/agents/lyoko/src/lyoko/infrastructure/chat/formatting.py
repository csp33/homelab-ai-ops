"""Markdown to Telegram HTML conversion helpers.

Telegram's HTML parser supports only a small tag set and no tables, so LLM Markdown output is
rewritten into that dialect before it is sent.
"""

import html
import re

# Telegram has no table support. Tables narrower than this many characters are rendered as
# aligned monospace blocks; wider ones wrap badly on phones, so they become per-row cards.
MAX_TABLE_PRE_WIDTH = 42

_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_EMPTY_CELL_VALUES = {"", "-", "—", "–"}


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_clean_table_cell(cell) for cell in stripped.split("|")]


def _clean_table_cell(cell: str) -> str:
    """Strip inline Markdown from a table cell so it renders as plain text."""
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    cell = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r"\1", cell)
    cell = cell.replace("**", "").replace("`", "")
    return cell.strip()


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header, separator = lines[index], lines[index + 1]
    return "|" in header and "|" in separator and bool(_TABLE_SEPARATOR_RE.match(separator))


def _render_table(rows: list[list[str]]) -> tuple[str, bool]:
    """Render parsed table rows. Returns (text, is_preformatted)."""
    header, body = rows[0], rows[1:]
    columns = len(header)
    body = [(row + [""] * columns)[:columns] for row in body]

    widths = [max(len(r[i]) for r in [header, *body]) for i in range(columns)]
    total_width = sum(widths) + 2 * (columns - 1)

    if total_width <= MAX_TABLE_PRE_WIDTH:
        lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(header)).rstrip()]
        lines.append("  ".join("─" * w for w in widths))
        lines.extend(
            "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip() for row in body
        )
        return "\n".join(lines), True

    cards: list[str] = []
    for row in body:
        card = [f"**{row[0] or header[0]}**"]
        card.extend(
            f"• {header[i]}: {row[i]}"
            for i in range(1, columns)
            if row[i] not in _EMPTY_CELL_VALUES
        )
        cards.append("\n".join(card))
    return "\n\n".join(cards), False


def _convert_markdown_tables(text: str, code_blocks: list[str]) -> str:
    """Replace Markdown tables with Telegram-friendly text (Telegram cannot render tables)."""
    lines = text.split("\n")
    output: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_table_start(lines, i):
            output.append(lines[i])
            i += 1
            continue

        rows = [_split_table_row(lines[i])]
        i += 2  # skip header + separator
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            rows.append(_split_table_row(lines[i]))
            i += 1

        rendered, preformatted = _render_table(rows)
        if preformatted:
            code_blocks.append(rendered)
            output.append(f"@@CODE_BLOCK_{len(code_blocks) - 1}@@")
        else:
            output.append(rendered)
    return "\n".join(output)


def _convert_markdown_blockquotes(text: str) -> str:
    """Convert lines starting with '&gt;' into Telegram expandable blockquotes."""
    lines = text.split("\n")
    output: list[str] = []
    quote_buffer: list[str] = []

    def flush_quote():
        if quote_buffer:
            content = "\n".join(quote_buffer)
            output.append(f"<blockquote expandable>{content}</blockquote>")
            quote_buffer.clear()

    for line in lines:
        stripped_line = line.lstrip()
        if stripped_line.startswith("&gt;"):
            inner = stripped_line[4:]
            if inner.startswith(" "):
                inner = inner[1:]
            quote_buffer.append(inner)
        else:
            flush_quote()
            output.append(line)
    flush_quote()
    return "\n".join(output)


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown output from LLMs to Telegram-compatible HTML formatting."""
    if not text:
        return ""

    # 1. Extract and preserve code blocks
    code_blocks: list[str] = []

    def save_code_block(match: re.Match) -> str:
        code_blocks.append(match.group(2))
        return f"@@CODE_BLOCK_{len(code_blocks) - 1}@@"

    # Match ```lang\ncode``` or ```code```
    processed = re.sub(r"```([a-zA-Z0-9_-]*\n)?(.*?)```", save_code_block, text, flags=re.DOTALL)

    # 1b. Convert Markdown tables (unsupported by Telegram) into monospace blocks or cards
    processed = _convert_markdown_tables(processed, code_blocks)

    # 2. Extract and preserve inline code
    inline_codes: list[str] = []

    def save_inline_code(match: re.Match) -> str:
        inline_codes.append(match.group(1))
        return f"@@INLINE_CODE_{len(inline_codes) - 1}@@"

    processed = re.sub(r"`([^`\n]+)`", save_inline_code, processed)

    # 3. HTML escape standard text so '<', '>', '&' don't break Telegram parser
    processed = html.escape(processed)

    # 4. Headers (# Title -> <b>Title</b>)
    processed = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", processed, flags=re.MULTILINE)

    # 5. Bold (**bold**)
    processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed)

    # 6. Italic (*italic* only when surrounded by non-alphanumeric or word boundaries)
    processed = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", processed)

    # 7. Links [title](url)
    processed = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', processed)

    # 7b. Expandable Blockquotes (> quote -> <blockquote expandable>quote</blockquote>)
    processed = _convert_markdown_blockquotes(processed)

    # 8. Restore inline code (HTML escaped content inside <code>)
    for i, code in enumerate(inline_codes):
        processed = processed.replace(f"@@INLINE_CODE_{i}@@", f"<code>{html.escape(code)}</code>")

    # 9. Restore code blocks (HTML escaped content inside <pre>)
    for i, code in enumerate(code_blocks):
        processed = processed.replace(
            f"@@CODE_BLOCK_{i}@@", f"<pre><code>{html.escape(code.strip())}</code></pre>"
        )

    return processed
