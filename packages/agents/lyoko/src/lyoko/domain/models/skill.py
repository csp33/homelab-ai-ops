"""Domain models for agent skills and runbooks."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillDocument:
    """Represents an operational runbook or specialized diagnostic skill."""

    name: str
    domain: str
    content: str
    description: str = ""
    match_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillMatch:
    """A matched skill with rationale and ranking score."""

    skill: SkillDocument
    matched_by: str
    score: float = 1.0
