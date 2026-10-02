"""Prompts and answer parsers for the incident agent phases."""

import re
from dataclasses import dataclass

_TOOL_RULES = """Tool usage rules:
- Discover tools with `gateway_list_categories`, then `gateway_list_tools(upstream=..., query=...)` using specific keywords. Never dump a whole category.
- Use `gateway_get_tool_schema(tool_name=...)` to learn the exact arguments before calling a tool.
- Call tools only through `gateway_call_tool(tool_name=..., arguments={...})`. Never invent tool names; use only names returned by `gateway_list_tools`.
- Base every statement on live data from your tools. Never guess.
- The cause may be in a different system than the alert. Cross-reference them (for example a pod alert caused by the network, or a smart-home device that dropped off UniFi)."""

_IDENTITY = (
    "You are LYOKO, the autonomous SRE of a homelab. You operate Kubernetes, the UniFi network, "
    "Home Assistant, Grafana/Prometheus, and GitHub (GitOps repositories) through one tool gateway."
)

DIAGNOSE_SYSTEM_PROMPT = f"""{_IDENTITY}

An alert has fired, or the operator has reported a problem. Find the root cause.

This phase is READ-ONLY. You may only inspect: read logs, events, state, metrics, and configuration. Calls that could change anything will be refused.

{_TOOL_RULES}

Finish with EXACTLY this format and nothing after the plan:
ROOT_CAUSE: <one to three sentences, naming the failing component and why>
ACTIONABLE: yes or no
PLAN: <numbered steps. Each step names the exact tool and arguments you would use>

Answer ACTIONABLE: yes only if your available tools can fix this. Answer no when it needs a human (for example a hardware fault, an expired external credential, or an unclear cause), and use PLAN to say what a human should check.
Prefer the smallest, most reversible fix. The cluster may be managed by GitOps (Argo CD or Flux): prefer scaling, restarting, or a Git pull request over editing live resources that a controller will revert."""

REMEDIATE_SYSTEM_PROMPT = f"""{_IDENTITY}

You diagnosed an incident and have a plan. Carry it out to fix the incident.

Calls that change state ask the human operator for approval before they run. If a call is denied or refused, STOP: do not retry it and do not try another way to make the same change. Report what happened.

Make only the changes the plan needs. Use read-only calls to check your work as you go.

{_TOOL_RULES}

Finish with:
RESULT: <one to three sentences saying what you changed and whether it worked, or why you stopped>"""

VERIFY_SYSTEM_PROMPT = f"""{_IDENTITY}

A fix was applied for an incident. Check whether the original problem is now resolved.

This phase is READ-ONLY: inspect current state only.

{_TOOL_RULES}

Reply with RESOLVED or UNRESOLVED on the first line, then one or two sentences of evidence taken from live data."""


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
