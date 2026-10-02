"""Parsing of the router's one-word answer."""

import pytest
from lyoko.application.router import ROUTER_SYSTEM_PROMPT, Route, parse_route


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("INCIDENT", Route.INCIDENT),
        ("incident", Route.INCIDENT),
        ("  Incident.\n", Route.INCIDENT),
        ("**INCIDENT**", Route.INCIDENT),
        ("CHAT", Route.CHAT),
        ("chat", Route.CHAT),
    ],
)
def test_parse_route_reads_the_decision(answer, expected):
    assert parse_route(answer) is expected


@pytest.mark.parametrize("answer", ["", "   ", "I am not sure", "incidental", "chatty"])
def test_parse_route_defaults_to_chat(answer):
    assert parse_route(answer) is Route.CHAT


def test_parse_route_uses_the_first_decision():
    assert parse_route("CHAT, although this could be an INCIDENT") is Route.CHAT


def test_parse_route_handles_missing_answer():
    assert parse_route(None) is Route.CHAT  # type: ignore[arg-type]


def test_router_prompt_names_both_routes_and_defaults_to_chat():
    assert "INCIDENT" in ROUTER_SYSTEM_PROMPT
    assert "CHAT" in ROUTER_SYSTEM_PROMPT
    assert "When in doubt, reply CHAT" in ROUTER_SYSTEM_PROMPT
