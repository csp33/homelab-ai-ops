"""Unit tests for guardrails, whitelisting, and execution boundaries."""

import pytest
from homelab_mcp.application.guardrail import GuardrailEngine
from homelab_mcp.domain.exceptions import GuardrailViolationError
from homelab_mcp.domain.models import GuardrailPolicy


def test_guardrail_tool_allowlist_wildcard():
    policy = GuardrailPolicy(allowed_tools=["ha_*", "k8s_get_*"])
    engine = GuardrailEngine(policy)

    assert engine.is_tool_allowed("ha_get_state") is True
    assert engine.is_tool_allowed("ha_set_state") is True
    assert engine.is_tool_allowed("k8s_get_pods") is True
    assert engine.is_tool_allowed("k8s_delete_pod") is False
    assert engine.is_tool_allowed("unifi_list_clients") is False


def test_guardrail_tool_denylist_precedence():
    policy = GuardrailPolicy(
        allowed_tools=["k8s_*"],
        blocked_tools=["k8s_delete_namespace", "k8s_delete_node"],
    )
    engine = GuardrailEngine(policy)

    assert engine.is_tool_allowed("k8s_get_pods") is True
    assert engine.is_tool_allowed("k8s_delete_pod") is True
    assert engine.is_tool_allowed("k8s_delete_namespace") is False
    assert engine.is_tool_allowed("k8s_delete_node") is False


def test_guardrail_blocked_namespaces():
    policy = GuardrailPolicy(
        allowed_tools=["*"],
        blocked_namespaces=["kube-system", "kube-public", "longhorn-system"],
    )
    engine = GuardrailEngine(policy)

    # Safe read operation in kube-system is permitted
    engine.validate_tool_call(
        "k8s_get_pod_diagnostics", {"namespace": "kube-system"}, upstream_name="kubernetes"
    )

    # Mutation in kube-system is blocked
    with pytest.raises(GuardrailViolationError) as exc:
        engine.validate_tool_call(
            "k8s_delete_pod",
            {"namespace": "kube-system", "pod_name": "coredns"},
            upstream_name="kubernetes",
        )
    assert "Mutation or exec operations in protected namespace 'kube-system' are prohibited" in str(
        exc.value
    )

    # Mutation in longhorn-system is blocked
    with pytest.raises(GuardrailViolationError) as exc:
        engine.validate_tool_call(
            "k8s_restart_deployment", {"namespace": "longhorn-system"}, upstream_name="kubernetes"
        )
    assert "longhorn-system" in str(exc.value)

    # Mutation in non-protected namespace is allowed
    engine.validate_tool_call(
        "k8s_delete_pod",
        {"namespace": "media", "pod_name": "radarr-xxx"},
        upstream_name="kubernetes",
    )


def test_guardrail_blocked_command_patterns():
    engine = GuardrailEngine(GuardrailPolicy())

    dangerous_commands = [
        "rm -rf /",
        "rm /tmp/test.txt",
        "rmdir /var/cache",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sdb1",
        "chmod -R 777 /",
        "chown root:root /bin/bash",
        "reboot",
        "shutdown -h now",
        "echo 1 > /dev/sda",
    ]

    for cmd in dangerous_commands:
        with pytest.raises(GuardrailViolationError) as exc:
            engine.validate_tool_call("k8s_exec", {"namespace": "default", "command": cmd})
        assert "violates blocked execution pattern" in str(exc.value)


def test_guardrail_allowed_command_whitelist():
    policy = GuardrailPolicy(
        allowed_exec_commands=["cat", "ls", "ps", "top", "df", "ip"],
    )
    engine = GuardrailEngine(policy)

    # Allowed commands
    engine.validate_tool_call(
        "k8s_exec", {"namespace": "default", "command": "cat /etc/os-release"}
    )
    engine.validate_tool_call("k8s_exec", {"namespace": "default", "command": "ls -lah /var/log"})
    engine.validate_tool_call("k8s_exec", {"namespace": "default", "command": "ps aux"})
    engine.validate_tool_call(
        "k8s_exec", {"namespace": "default", "command": "sh -c 'cat /proc/meminfo'"}
    )

    # Disallowed binary (not in allowed list, e.g. curl)
    with pytest.raises(GuardrailViolationError) as exc:
        engine.validate_tool_call(
            "k8s_exec", {"namespace": "default", "command": "curl http://external.site"}
        )
    assert "not in the allowed commands whitelist" in str(exc.value)
