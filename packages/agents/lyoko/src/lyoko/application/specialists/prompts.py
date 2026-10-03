"""Specialist domain prompts for LYOKO loaded from markdown files."""

from lyoko.application.prompts.loader import load_prompt

NETWORK_SPECIALIST_PROMPT = load_prompt("specialists/network.md")
K8S_SPECIALIST_PROMPT = load_prompt("specialists/k8s.md")
SMARTHOME_SPECIALIST_PROMPT = load_prompt("specialists/smarthome.md")
OBSERVABILITY_SPECIALIST_PROMPT = load_prompt("specialists/observability.md")
