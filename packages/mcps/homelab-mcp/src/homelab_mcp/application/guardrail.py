"""Guardrail service enforcing security whitelists and execution boundaries."""

import fnmatch
import logging
import re
import shlex
from typing import Any

from homelab_mcp.domain.exceptions import GuardrailViolationError
from homelab_mcp.domain.models.guardrail import GuardrailPolicy

logger = logging.getLogger("homelab_mcp.guardrails")


class GuardrailEngine:
    """Evaluates security rules, tool whitelists, and command execution guardrails."""

    def __init__(self, policy: GuardrailPolicy | None = None):
        self.policy = policy or GuardrailPolicy()

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is permitted by the allowlist and not blocked by the denylist."""
        # 1. Denylist takes absolute precedence
        for pattern in self.policy.blocked_tools:
            if fnmatch.fnmatch(tool_name, pattern):
                return False

        # 2. Allowlist check
        return any(fnmatch.fnmatch(tool_name, pattern) for pattern in self.policy.allowed_tools)

    def validate_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        upstream_name: str = "",
    ) -> None:
        """Validate tool invocation against all active guardrail rules.

        Raises:
            GuardrailViolationError: If the call violates any security rule.
        """
        # 1. Tool allowlist check
        if not self.is_tool_allowed(tool_name):
            raise GuardrailViolationError(
                f"Security Guardrail: Tool '{tool_name}' is not permitted by the tool whitelist."
            )

        # 2. Kubernetes protected namespaces check
        if upstream_name == "kubernetes" or tool_name.startswith(("k8s_", "kubernetes_")):
            namespace = arguments.get("namespace") or arguments.get("ns")
            if (
                namespace
                and namespace in self.policy.blocked_namespaces
                and any(
                    action in tool_name.lower()
                    for action in [
                        "delete",
                        "patch",
                        "create",
                        "update",
                        "restart",
                        "bump",
                        "exec",
                        "replace",
                    ]
                )
            ):
                raise GuardrailViolationError(
                    f"Security Guardrail: Mutation or exec operations in protected namespace '{namespace}' are prohibited."
                )

        # 3. Deep inspection of container exec / command execution arguments
        self._inspect_exec_commands(tool_name, arguments)

    def _inspect_exec_commands(self, tool_name: str, arguments: dict[str, Any]) -> None:
        """Inspect command strings or lists passed to execution tools to prevent destructive commands."""
        # Extract command strings from common parameter names
        command_candidates: list[str] = []

        for key in ["command", "cmd", "args", "script", "command_line", "exec"]:
            if key in arguments:
                val = arguments[key]
                if isinstance(val, str):
                    command_candidates.append(val)
                elif isinstance(val, list):
                    # List of arguments e.g. ["rm", "-rf", "/tmp"]
                    command_candidates.append(" ".join(str(item) for item in val))
                elif isinstance(val, dict):
                    # Nested structures
                    command_candidates.extend(
                        str(v) for v in val.values() if isinstance(v, (str, list))
                    )

        if not command_candidates and not any(
            k in tool_name.lower() for k in ["exec", "shell", "bash", "run_cmd"]
        ):
            return

        for cmd_str in command_candidates:
            # Check blocked regex patterns (e.g. \brm\b, \bdd\b, etc.)
            for pattern in self.policy.blocked_exec_patterns:
                if re.search(pattern, cmd_str, re.IGNORECASE):
                    raise GuardrailViolationError(
                        f"Security Guardrail: Command '{cmd_str}' violates blocked execution pattern '{pattern}'."
                    )

            # Check allowed exec binaries whitelist if configured
            if self.policy.allowed_exec_commands:
                try:
                    tokens = shlex.split(cmd_str)
                except Exception:
                    tokens = cmd_str.split()

                if tokens:
                    base_binary = tokens[0].split("/")[-1]
                    # In case of subshell wrappers e.g. "sh -c '...'", extract the actual command inside
                    if (
                        base_binary in ["sh", "bash", "zsh"]
                        and len(tokens) >= 3
                        and tokens[1] == "-c"
                    ):
                        inner_cmd = tokens[2]
                        try:
                            inner_tokens = shlex.split(inner_cmd)
                            if inner_tokens:
                                base_binary = inner_tokens[0].split("/")[-1]
                        except Exception:
                            pass

                    if base_binary not in self.policy.allowed_exec_commands:
                        raise GuardrailViolationError(
                            f"Security Guardrail: Command binary '{base_binary}' is not in the allowed commands whitelist."
                        )
