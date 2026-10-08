"""Domain service for matching operational skills to incident alerts and context."""

from lyoko.domain.interfaces.skill import SkillRepositoryInterface
from lyoko.domain.models.skill import SkillDocument, SkillMatch


class SkillMatcherService:
    """Matches alerts and context against domain runbooks and skills."""

    def __init__(self, repository: SkillRepositoryInterface) -> None:
        self._repository = repository

    def _score_skill(
        self,
        skill: SkillDocument,
        tokens: set[str],
        full_text: str,
    ) -> SkillMatch | None:
        best_pattern: str | None = None
        score = 0.0

        for pattern in skill.match_patterns:
            pat_norm = pattern.strip().lower()
            if pat_norm in tokens:
                score += 2.0
                best_pattern = pattern
            elif pat_norm in full_text:
                score += 1.0
                if not best_pattern:
                    best_pattern = pattern

        if score > 0.0 and best_pattern:
            return SkillMatch(skill=skill, matched_by=best_pattern, score=score)
        return None

    async def match_skills_for_alert(
        self,
        alert_name: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> list[SkillMatch]:
        """Find skills matching the alert name, labels, and annotations."""
        all_skills = await self._repository.list_skills()
        labels_map = labels or {}
        annotations_map = annotations or {}

        search_corpus = [alert_name]
        search_corpus.extend(labels_map.values())
        search_corpus.extend(labels_map.keys())
        search_corpus.extend(annotations_map.values())

        full_text = " ".join(search_corpus).lower()
        tokens = {word.lower() for word in full_text.split() if word}

        matches: list[SkillMatch] = []
        for skill in all_skills:
            match = self._score_skill(skill, tokens, full_text)
            if match:
                matches.append(match)

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    async def format_matched_skills_context(
        self,
        alert_name: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        max_skills: int = 2,
    ) -> str:
        """Format matched skills into a markdown section ready for prompt injection."""
        matches = await self.match_skills_for_alert(alert_name, labels, annotations)
        if not matches:
            return ""

        selected = matches[:max_skills]
        sections: list[str] = []
        for item in selected:
            skill = item.skill
            sections.append(
                f"### Runbook: {skill.name} (Matched on '{item.matched_by}')\n{skill.content}"
            )

        body = "\n\n".join(sections)
        return f"\n\n--- RELEVANT OPERATIONAL RUNBOOKS ---\n{body}\n--------------------------------------"
