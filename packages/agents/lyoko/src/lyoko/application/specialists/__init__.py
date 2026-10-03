"""Specialist agents and domain prompts for LYOKO."""

from lyoko.application.specialists.agent import DomainSpecialistAgent
from lyoko.application.specialists.prompts import (
    K8S_SPECIALIST_PROMPT,
    NETWORK_SPECIALIST_PROMPT,
    OBSERVABILITY_SPECIALIST_PROMPT,
    SMARTHOME_SPECIALIST_PROMPT,
)

__all__ = [
    "DomainSpecialistAgent",
    "K8S_SPECIALIST_PROMPT",
    "NETWORK_SPECIALIST_PROMPT",
    "SMARTHOME_SPECIALIST_PROMPT",
    "OBSERVABILITY_SPECIALIST_PROMPT",
]
