"""Specialist domain prompts for LYOKO loaded from markdown files."""

from lyoko.application.context.loader import build_agent_context
from lyoko.application.prompts.loader import load_prompt

NETWORK_SPECIALIST_PROMPT = (
    f"{load_prompt('specialists/network.md')}\n\n{build_agent_context('network')}"
)
K8S_SPECIALIST_PROMPT = f"{load_prompt('specialists/k8s.md')}\n\n{build_agent_context('k8s')}"
SMARTHOME_SPECIALIST_PROMPT = (
    f"{load_prompt('specialists/smarthome.md')}\n\n{build_agent_context('smarthome')}"
)
OBSERVABILITY_SPECIALIST_PROMPT = (
    f"{load_prompt('specialists/observability.md')}\n\n{build_agent_context('observability')}"
)
