"""Tool-call gate: decides whether an agent's tool call runs, needs approval, or is refused."""

import fnmatch
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.domain.models.chat import ApprovalAction, ApprovalRequest

logger = logging.getLogger("lyoko.tool_gate")

_MAX_ARGUMENTS_CHARS = 1500


class GateMode(StrEnum):
    """What the gate does with a tool that is neither read-only nor auto-approved."""

    READ_ONLY = "read_only"
    """Refuse it. Used while investigating and verifying, when nothing may change."""

    APPROVAL = "approval"
    """Ask the operator before running it. Used while remediating."""


class CallOutcome(StrEnum):
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    DENIED = "denied"
    REFUSED = "refused"


@dataclass(frozen=True)
class ToolCallRecord:
    """A state-changing tool call the gate had to decide on (read-only calls are not recorded)."""

    tool: str
    arguments: dict[str, Any]
    outcome: CallOutcome
    reason: str = ""

    @property
    def executed(self) -> bool:
        return self.outcome in (CallOutcome.AUTO_APPROVED, CallOutcome.APPROVED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "outcome": self.outcome.value,
            "reason": self.reason,
        }


def matches_any(tool_name: str, patterns: Sequence[str]) -> bool:
    """Return True when ``tool_name`` matches one of the glob ``patterns`` (case-sensitive)."""
    return any(fnmatch.fnmatchcase(tool_name, pattern) for pattern in patterns)


class ToolGate:
    """Authorizes the tool calls of one agent run.

    The gate serves any run, an incident phase or a chat reply. ``event_id`` identifies the run
    and prefixes its approval ids (they end up in Telegram callback data, limited to 64 bytes, so
    keep it short). ``origin`` is the line shown to the operator saying what triggered the run.
    Replies to an approval message continue ``session_id``, which defaults to ``event_id``.

    Policy, evaluated in order:

    1. A tool matching ``read_only_patterns`` always runs and is not recorded.
    2. In ``APPROVAL`` mode, a tool matching ``auto_approved_patterns`` runs and is recorded.
    3. Anything else needs the operator: in ``APPROVAL`` mode they are asked through the chat
       connectors and the call waits for their answer; in ``READ_ONLY`` mode the call is refused.

    Refusals are returned as text so the agent can adapt instead of crashing. When no approval
    channel is available the gate refuses rather than guessing, so a missing channel can never
    turn into an unattended change.
    """

    def __init__(
        self,
        *,
        mode: GateMode,
        read_only_patterns: Sequence[str],
        auto_approved_patterns: Sequence[str] = (),
        event_id: str,
        origin: str,
        session_id: str | None = None,
        chat_id: str = "",
        approval_manager: ApprovalManager | None = None,
        chat_manager: ChatManager | None = None,
    ) -> None:
        self.mode = mode
        self.records: list[ToolCallRecord] = []
        self._read_only_patterns = tuple(read_only_patterns)
        self._auto_approved_patterns = tuple(auto_approved_patterns)
        self._event_id = event_id
        self._origin = origin
        self._session_id = session_id or event_id
        self._chat_id = chat_id
        self._approval_manager = approval_manager
        self._chat_manager = chat_manager
        self._approval_count = 0

    async def authorize(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """Return ``None`` to allow the call, or a refusal message for the agent."""
        if matches_any(tool_name, self._read_only_patterns):
            return None

        if self.mode is GateMode.READ_ONLY:
            return self._refuse(
                tool_name,
                arguments,
                f"'{tool_name}' may change state and this phase is read-only. Do not call it. "
                "If it is needed, include it in your plan instead.",
            )

        if matches_any(tool_name, self._auto_approved_patterns):
            self._record(tool_name, arguments, CallOutcome.AUTO_APPROVED)
            return None

        return await self._ask_operator(tool_name, arguments)

    def _record(
        self, tool_name: str, arguments: dict[str, Any], outcome: CallOutcome, reason: str = ""
    ) -> None:
        self.records.append(ToolCallRecord(tool_name, arguments, outcome, reason))

    def _refuse(self, tool_name: str, arguments: dict[str, Any], message: str) -> str:
        self._record(tool_name, arguments, CallOutcome.REFUSED, message)
        logger.warning("Refused tool call '%s' for event %s", tool_name, self._event_id)
        return f"Refused: {message}"

    async def _ask_operator(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        if self._approval_manager is None or self._chat_manager is None:
            return self._refuse(
                tool_name,
                arguments,
                f"'{tool_name}' requires operator approval but no approval channel is configured.",
            )

        self._approval_count += 1
        approval_id = f"{self._event_id}.{self._approval_count}"
        request = ApprovalRequest(
            incident_id=approval_id,
            session_id=self._session_id,
            title=f"Approval required: {tool_name}",
            details=(
                f"{self._origin}\n"
                f"Tool: `{tool_name}`\n"
                f"Arguments:\n```json\n{_format_arguments(arguments)}\n```"
            ),
            chat_id=self._chat_id,
            actions=[
                ApprovalAction(action_id="approve", label="✅ Approve", style="primary"),
                ApprovalAction(action_id="reject", label="❌ Deny", style="danger"),
            ],
        )
        await self._chat_manager.broadcast_approval_request(request)
        response = await self._approval_manager.wait_for_approval(approval_id)

        if response.approved:
            self._record(tool_name, arguments, CallOutcome.APPROVED)
            return None

        reason = response.reason or "denied by the operator"
        self._record(tool_name, arguments, CallOutcome.DENIED, reason)
        logger.warning("Operator denied '%s' for event %s: %s", tool_name, self._event_id, reason)
        return (
            f"Denied: the operator did not approve '{tool_name}' ({reason}). Do not retry it or "
            "look for a way around the denial. Stop and report what you found."
        )


def _format_arguments(arguments: dict[str, Any]) -> str:
    text = json.dumps(arguments, indent=2, default=str, ensure_ascii=False)
    if len(text) > _MAX_ARGUMENTS_CHARS:
        return text[:_MAX_ARGUMENTS_CHARS] + "\n... (truncated)"
    return text
