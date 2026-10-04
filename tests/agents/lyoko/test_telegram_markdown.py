def test_markdown_to_telegram_html():
    from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

    # Empty / none
    assert markdown_to_telegram_html("") == ""

    # Bold and italics
    assert markdown_to_telegram_html("**bold text**") == "<b>bold text</b>"
    assert markdown_to_telegram_html("*italic text*") == "<i>italic text</i>"

    # Underscores in identifiers must NOT be eaten or converted to italic
    assert (
        markdown_to_telegram_html("Connected to MOVISTAR_25EO_IOT wifi network")
        == "Connected to MOVISTAR_25EO_IOT wifi network"
    )

    # Inline code
    assert (
        markdown_to_telegram_html("Use `kubectl get pods -n kube-system` now")
        == "Use <code>kubectl get pods -n kube-system</code> now"
    )

    # Code block with language
    code_block = '```json\n{"status": "ok"}\n```'
    assert (
        markdown_to_telegram_html(code_block)
        == '<pre><code class="language-json">{\n  &quot;status&quot;: &quot;ok&quot;\n}\n</code></pre>'
        or "<pre><code>" in markdown_to_telegram_html(code_block)
    )

    # HTML special characters escaping
    assert markdown_to_telegram_html("5 < 10 && 10 > 5") == "5 &lt; 10 &amp;&amp; 10 &gt; 5"

    # Headers
    assert markdown_to_telegram_html("### Header Title") == "<b>Header Title</b>"

    # Links
    assert (
        markdown_to_telegram_html("[Grafana](http://grafana.local)")
        == '<a href="http://grafana.local">Grafana</a>'
    )


def test_markdown_table_narrow_becomes_monospace_block():
    from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

    table = "| Name | State |\n|------|-------|\n| **WLAN** | OK |\n| LAN | `Down` |"
    result = markdown_to_telegram_html(table)

    assert result.startswith("<pre><code>")
    assert "|" not in result
    assert "WLAN  OK" in result
    assert "LAN   Down" in result


def test_markdown_table_wide_becomes_cards():
    from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

    table = (
        "| Subsystem | Status | Active Users | Bytes Received (Rx) | Bytes Sent (Tx) |\n"
        "|-----------|--------|--------------|---------------------|-----------------|\n"
        "| WLAN | OK | 36 | 9,465 | 2,500 |\n"
        "| VPN | OK | - | - | - |"
    )
    result = markdown_to_telegram_html(table)

    assert "|" not in result
    assert "<pre>" not in result
    assert "<b>WLAN</b>\n• Status: OK\n• Active Users: 36" in result
    assert "<b>VPN</b>\n• Status: OK" in result
    assert "VPN</b>\n• Status: OK\n•" not in result  # empty "-" values are skipped


def test_markdown_table_inside_code_block_is_untouched():
    from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

    text = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```"
    assert "| a | b |" in markdown_to_telegram_html(text)


def test_markdown_to_telegram_html_expandable_blockquote():
    """Verify markdown blockquotes are converted to <blockquote expandable>."""
    from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

    # Single line blockquote
    single = "> This is a quote"
    assert (
        markdown_to_telegram_html(single) == "<blockquote expandable>This is a quote</blockquote>"
    )

    # Multi-line blockquote with formatting
    multi = "> Line 1 with **bold**\n> Line 2 with `code`"
    expected = (
        "<blockquote expandable>Line 1 with <b>bold</b>\nLine 2 with <code>code</code></blockquote>"
    )
    assert markdown_to_telegram_html(multi) == expected

    # Blockquote followed by regular text
    mixed = "> Quote header\n\nRegular text after quote"
    expected_mixed = "<blockquote expandable>Quote header</blockquote>\n\nRegular text after quote"
    assert markdown_to_telegram_html(mixed) == expected_mixed
