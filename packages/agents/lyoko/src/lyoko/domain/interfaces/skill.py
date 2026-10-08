"""Domain port interface for discovering and loading skills and runbooks."""

from abc import ABC, abstractmethod

from lyoko.domain.models.skill import SkillDocument


class SkillRepositoryInterface(ABC):
    """Abstract port for querying and reading skill documents."""

    @abstractmethod
    async def list_skills(self) -> list[SkillDocument]:
        """List all available skill documents."""

    @abstractmethod
    async def get_skill(self, name: str) -> SkillDocument | None:
        """Fetch a specific skill document by unique name."""

    @abstractmethod
    async def find_skills_by_domain(self, domain: str) -> list[SkillDocument]:
        """Fetch all skills belonging to a domain (e.g. 'k8s', 'gitops')."""
