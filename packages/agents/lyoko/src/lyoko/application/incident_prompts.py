"""Prompts and answer parsers for the incident agent phases."""

import re
from dataclasses import dataclass

from lyoko.application.prompts.loader import load_prompt

DIAGNOSE_SYSTEM_PROMPT = load_prompt("diagnose.md")
REMEDIATE_SYSTEM_PROMPT = load_prompt("remediate.md")
VERIFY_SYSTEM_PROMPT = load_prompt("verify.md")


@dataclass(frozen=True)
class Diagnosis:
    root_cause: str
    actionable: bool
    plan: str


_ROOT_CAUSE_RE = re.compile(r"^ROOT_CAUSE:\s*(.*?)(?=^ACTIONABLE:|\Z)", re.S | re.M | re.I)
_ACTIONABLE_RE = re.compile(r"^ACTIONABLE:\s*(yes|no)\b", re.M | re.I)
_PLAN_RE = re.compile(r"^PLAN:\s*(.*)\Z", re.S | re.M | re.I)
_RESULT_RE = re.compile(r"^RESULT:\s*(.*)\Z", re.S | re.M | re.I)
_VERDICT_RE = re.compile(r"\W*(RESOLVED|UNRESOLVED)\b[\s:.*\-]*(.*)", re.S | re.I)


def parse_diagnosis(text: str) -> Diagnosis:
    """Parse the diagnose answer. Anything unparseable is treated as not actionable."""
    root_cause_match = _ROOT_CAUSE_RE.search(text)
    actionable_match = _ACTIONABLE_RE.search(text)
    plan_match = _PLAN_RE.search(text)

    root_cause = (root_cause_match.group(1).strip() if root_cause_match else "") or text.strip()[
        :500
    ]
    actionable = bool(actionable_match and actionable_match.group(1).lower() == "yes")
    plan = plan_match.group(1).strip() if plan_match else ""
    return Diagnosis(root_cause=root_cause, actionable=actionable and bool(plan), plan=plan)


def parse_result(text: str) -> str:
    """Return the ``RESULT:`` summary of a remediation, or the whole answer if it is missing."""
    match = _RESULT_RE.search(text)
    return (match.group(1) if match else text).strip()


def parse_verdict(text: str) -> tuple[bool, str]:
    """Parse the verify answer into ``(resolved, evidence)``. Unclear answers are unresolved."""
    stripped = text.strip()
    match = _VERDICT_RE.match(stripped)
    if match is None:
        return False, stripped
    return match.group(1).upper() == "RESOLVED", match.group(2).strip()
