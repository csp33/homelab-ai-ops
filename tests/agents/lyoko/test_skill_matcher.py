"""Tests for SkillMatcherService."""

import pytest
from lyoko.application.skills.matcher import SkillMatcherService
from lyoko.domain.models.skill import SkillDocument
from lyoko.infrastructure.skills.markdown_skill_repository import MarkdownSkillRepository


class InMemorySkillRepo:
    def __init__(self, skills: list[SkillDocument]):
        self._skills = skills

    async def list_skills(self) -> list[SkillDocument]:
        return self._skills

    async def get_skill(self, name: str) -> SkillDocument | None:
        for s in self._skills:
            if s.name == name:
                return s
        return None

    async def find_skills_by_domain(self, domain: str) -> list[SkillDocument]:
        return [s for s in self._skills if s.domain == domain]


@pytest.mark.asyncio
async def test_match_crashloop_alert():
    skills = [
        SkillDocument(
            name="pod_crashloop",
            domain="k8s",
            content="# CrashLoop Guide\nCheck logs and previous termination.",
            match_patterns=["CrashLoopBackOff", "OOMKilled"],
        ),
        SkillDocument(
            name="pvc_pending",
            domain="k8s",
            content="# PVC Guide\nCheck storage class.",
            match_patterns=["KubePersistentVolumeFillingUp", "VolumePending"],
        ),
    ]
    matcher = SkillMatcherService(repository=InMemorySkillRepo(skills))

    matches = await matcher.match_skills_for_alert(
        alert_name="KubePodCrashLooping",
        labels={"alertname": "KubePodCrashLooping", "reason": "CrashLoopBackOff"},
    )

    assert len(matches) == 1
    assert matches[0].skill.name == "pod_crashloop"
    assert matches[0].matched_by == "CrashLoopBackOff"

    context = await matcher.format_matched_skills_context(
        alert_name="KubePodCrashLooping",
        labels={"reason": "CrashLoopBackOff"},
    )
    assert "RELEVANT OPERATIONAL RUNBOOKS" in context
    assert "Runbook: pod_crashloop" in context
    assert "Check logs and previous termination." in context


@pytest.mark.asyncio
async def test_no_matches_returns_empty_context():
    matcher = SkillMatcherService(repository=InMemorySkillRepo([]))
    context = await matcher.format_matched_skills_context(alert_name="UnrelatedAlert")
    assert context == ""


@pytest.mark.asyncio
async def test_matcher_with_real_markdown_repo():
    repo = MarkdownSkillRepository()
    matcher = SkillMatcherService(repository=repo)

    matches = await matcher.match_skills_for_alert(
        alert_name="ArgoAppOutOfSync",
        labels={"alertname": "ArgoAppOutOfSync"},
    )
    assert len(matches) >= 1
    assert matches[0].skill.name == "argocd_sync"
