"""Unit tests for markdown prompt loading and prompt integrity."""

import pytest
from lyoko.application.chat_prompts import CHAT_SYSTEM_PROMPT
from lyoko.application.incident_prompts import (
    DIAGNOSE_SYSTEM_PROMPT,
    REMEDIATE_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT,
)
from lyoko.application.prompts.loader import load_prompt
from lyoko.application.router import ROUTER_SYSTEM_PROMPT
from lyoko.application.specialists.prompts import (
    K8S_SPECIALIST_PROMPT,
    NETWORK_SPECIALIST_PROMPT,
    OBSERVABILITY_SPECIALIST_PROMPT,
    SMARTHOME_SPECIALIST_PROMPT,
)
from lyoko.application.supervisor import SUPERVISOR_SYSTEM_PROMPT


def test_load_prompt_success():
    chat_prompt = load_prompt("chat.md")
    assert "LYOKO" in chat_prompt
    assert "AIOps" in chat_prompt


def test_load_prompt_missing_file():
    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        load_prompt("nonexistent_prompt.md")


def test_all_prompts_loaded_properly():
    assert "LYOKO" in CHAT_SYSTEM_PROMPT
    assert "READ-ONLY" in DIAGNOSE_SYSTEM_PROMPT
    assert "RESULT:" in REMEDIATE_SYSTEM_PROMPT
    assert "RESOLVED or UNRESOLVED" in VERIFY_SYSTEM_PROMPT
    assert "INCIDENT" in ROUTER_SYSTEM_PROMPT
    assert "Supervisor" in SUPERVISOR_SYSTEM_PROMPT
    assert "Kubernetes" in K8S_SPECIALIST_PROMPT
    assert "UniFi" in NETWORK_SPECIALIST_PROMPT
    assert "Home Assistant" in SMARTHOME_SPECIALIST_PROMPT
    assert (
        "Grafana" in OBSERVABILITY_SPECIALIST_PROMPT
        or "Prometheus" in OBSERVABILITY_SPECIALIST_PROMPT
    )


def test_supervisor_prompt_guards_against_hijack_and_domain_substitution():
    assert "operator's latest message" in SUPERVISOR_SYSTEM_PROMPT.lower()
    assert "Do not substitute a different domain" in SUPERVISOR_SYSTEM_PROMPT
    assert "at most once" in SUPERVISOR_SYSTEM_PROMPT


def test_smarthome_prompt_forbids_invented_tool_names():
    assert "Never invent or guess a tool name" in SMARTHOME_SPECIALIST_PROMPT
