"""Tests for MarkdownSkillRepository adapter."""

from pathlib import Path

import pytest
from lyoko.infrastructure.skills.markdown_skill_repository import MarkdownSkillRepository


@pytest.mark.asyncio
async def test_discover_real_skills():
    repo = MarkdownSkillRepository()
    skills = await repo.list_skills()

    assert len(skills) >= 3
    names = {s.name for s in skills}
    assert "pod_crashloop" in names
    assert "pvc_pending_storage" in names
    assert "argocd_sync" in names

    crashloop = await repo.get_skill("pod_crashloop")
    assert crashloop is not None
    assert crashloop.domain == "k8s"
    assert "CrashLoopBackOff" in crashloop.match_patterns
    assert "Objective" in crashloop.content


@pytest.mark.asyncio
async def test_find_skills_by_domain():
    repo = MarkdownSkillRepository()
    k8s_skills = await repo.find_skills_by_domain("k8s")
    assert len(k8s_skills) >= 2
    for s in k8s_skills:
        assert s.domain == "k8s"


@pytest.mark.asyncio
async def test_empty_or_nonexistent_directory(tmp_path: Path):
    repo = MarkdownSkillRepository(skills_dir=tmp_path / "does_not_exist")
    skills = await repo.list_skills()
    assert skills == []
