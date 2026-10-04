"""Home Assistant domain models."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EntityState:
    entity_id: str
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)
    last_changed: str | None = None
    last_updated: str | None = None
