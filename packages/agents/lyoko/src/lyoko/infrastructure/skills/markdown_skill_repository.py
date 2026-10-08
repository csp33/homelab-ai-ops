"""Filesystem adapter for discovering and loading markdown skill runbooks."""

import re
from pathlib import Path

import yaml
from lyoko.domain.interfaces.skill import SkillRepositoryInterface
from lyoko.domain.models.skill import SkillDocument

_FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_DESC_REGEX = re.compile(r"<!--\s*description:\s*(.*?)\s*-->", re.IGNORECASE)
_PATTERNS_REGEX = re.compile(r"<!--\s*patterns:\s*(.*?)\s*-->", re.IGNORECASE)


class MarkdownSkillRepository(SkillRepositoryInterface):
    """Loads skill documents from a directory containing domain-subfolder markdown files."""

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        if skills_dir is None:
            self._skills_dir = (
                Path(__file__).resolve().parent.parent.parent / "application" / "skills"
            )
        else:
            self._skills_dir = Path(skills_dir)

    def _parse_skill(self, file_path: Path) -> SkillDocument:
        domain = file_path.parent.name
        name = file_path.stem
        raw_text = file_path.read_text(encoding="utf-8")

        description = ""
        patterns: list[str] = []

        frontmatter_match = _FRONTMATTER_REGEX.match(raw_text)
        if frontmatter_match:
            try:
                meta = yaml.safe_load(frontmatter_match.group(1)) or {}
                if isinstance(meta, dict):
                    name = meta.get("name") or name
                    description = meta.get("description", "")
                    raw_patterns = meta.get("patterns", [])
                    if isinstance(raw_patterns, list):
                        patterns = [str(p).strip() for p in raw_patterns if str(p).strip()]
                    elif isinstance(raw_patterns, str):
                        patterns = [p.strip() for p in raw_patterns.split(",") if p.strip()]
            except Exception:
                pass

        if not description:
            desc_match = _DESC_REGEX.search(raw_text)
            description = desc_match.group(1).strip() if desc_match else ""

        if not patterns:
            pats_match = _PATTERNS_REGEX.search(raw_text)
            if pats_match:
                raw_pats = pats_match.group(1)
                patterns = [p.strip() for p in raw_pats.split(",") if p.strip()]

        return SkillDocument(
            name=name,
            domain=domain,
            content=raw_text.strip(),
            description=description,
            match_patterns=patterns,
        )

    async def list_skills(self) -> list[SkillDocument]:
        """Discover and load all markdown skills in the repository."""
        if not self._skills_dir.exists():
            return []
        skills: list[SkillDocument] = []
        for path in sorted(self._skills_dir.glob("*/*.md")):
            if path.is_file():
                skills.append(self._parse_skill(path))
        return skills

    async def get_skill(self, name: str) -> SkillDocument | None:
        """Fetch a specific skill by stem name."""
        all_skills = await self.list_skills()
        for skill in all_skills:
            if skill.name == name:
                return skill
        return None

    async def find_skills_by_domain(self, domain: str) -> list[SkillDocument]:
        """Fetch all skills in the given domain directory."""
        all_skills = await self.list_skills()
        norm = domain.strip().lower()
        return [s for s in all_skills if s.domain.lower() == norm]
