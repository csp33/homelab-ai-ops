# Deterministic Triage Expansion & Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the LYOKO workflow's `triage` node into an extensible deterministic triage dispatcher and implement deterministic fast-paths for `ArgoCDAppOutOfSync` (existing), `KubePodCrashLooping`, `CloudflaredPodRestarts` / `CloudflaredPodNotReady`, and `ArgoCDAppSyncFailed`.

**Architecture:** 
1. Build a modular triage framework under `lyoko.application.triage`:
   - `base.py`: Protocol/interface for deterministic triage handlers (`TriageHandlerInterface` or callable protocol) returning a structured `TriageResult` or `None`.
   - `dispatcher.py`: Dispatches events (both `alert` and `message`) sequentially to registered deterministic handlers. If none match or handle the event, falls through to `diagnose`.
   - `argocd_outofsync.py`: Preserves the current Argo CD autosync logic adapted to the triage handler interface.
   - `pod_crashloop.py`: Detects `KubePodCrashLooping` (and chat messages about crashing pods) and safely deletes the pod (via `k8s_pods_delete`) to trigger a clean restart by its controller (or triggers rollout restart/pod delete), verifying pod health afterwards.
   - `cloudflare_tunnel.py`: Detects `CloudflaredPodRestarts` / `CloudflaredPodNotReady` and executes a restart of the `cloudflare-tunnel` deployment pod in `cloudflare-tunnel` namespace, verifying replica availability.
   - `argocd_sync_failed.py`: Detects `ArgoCDAppSyncFailed`, inspects `status.operationState`, and if transient / non-fatal or retryable, triggers sync / refresh or reports exact transient error handling.
2. Wire the triage dispatcher into `workflow.py` replacing the single-purpose `create_argocd_autosync_node`.
3. Support both `event_type == "alert"` (from Alertmanager webhooks with `alert_name`, `labels`, `annotations`) and `event_type == "message"` (from operator chat).

**Tech Stack:** Python 3.14+, LangGraph StateGraph, Pydantic, pytest, sector5-mcp / Kubernetes MCP toolset.

**Spec:** User request to add `KubePodCrashLooping`, `CloudflaredPodRestarts` / `CloudflaredPodNotReady`, `ArgoCDAppSyncFailed` and refactor the `triage` node.

## Global Constraints
- Clean Architecture: 0 external infrastructure imports in `domain/` and `application/`.
- All `__init__.py` files must remain empty (0 bytes).
- All files in `domain/` and `application/` must be < 280 lines.
- All code, comments, docstrings, and commits in English.
- ToolGate enforcement: All mutation tool calls must be gated and recorded.

---

### Task 1: Triage Core Models & Dispatcher Architecture

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/triage/base.py`
- Create: `packages/agents/lyoko/src/lyoko/application/triage/dispatcher.py`
- Create: `packages/agents/lyoko/src/lyoko/application/triage/__init__.py` (0 bytes)
- Test: `tests/agents/lyoko/test_triage_dispatcher.py`

**Interfaces:**
- Consumes: `MCPClientInterface`, `ApprovalManager`, `ChatManager`, `TracerInterface`, `ToolGate`, `RunnableConfig`
- Produces: `TriageHandlerInterface` protocol, `TriageResult` dataclass, `create_triage_node` factory function.

- [ ] **Step 1: Write failing unit test for triage dispatcher**

```python
# tests/agents/lyoko/test_triage_dispatcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from lyoko.application.triage.base import TriageResult
from lyoko.application.triage.dispatcher import create_triage_node


@pytest.mark.asyncio
async def test_triage_dispatcher_falls_through_when_no_handler_matches():
    node = create_triage_node(handlers=[])
    state = {"event_type": "alert", "alert_name": "UnknownAlert"}
    result = await node(state, {})
    assert result == {"triage": "diagnose"}


@pytest.mark.asyncio
async def test_triage_dispatcher_executes_first_matching_handler():
    handler = MagicMock()
    handler.can_handle = MagicMock(return_value=True)
    handler.execute = AsyncMock(
        return_value=TriageResult(
            handled=True,
            root_cause="Found issue",
            plan="Fixed issue",
            action_taken="Took action",
            is_resolved=True,
        )
    )
    node = create_triage_node(handlers=[handler])
    state = {"event_type": "alert", "alert_name": "TestAlert"}
    result = await node(state, {})
    assert result["triage"] == "handled"
    assert result["root_cause"] == "Found issue"
    assert result["is_resolved"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/lyoko/test_triage_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lyoko.application.triage'`

- [ ] **Step 3: Implement `base.py`, empty `__init__.py`, and `dispatcher.py`**

Create `packages/agents/lyoko/src/lyoko/application/triage/__init__.py` (empty).

In `packages/agents/lyoko/src/lyoko/application/triage/base.py`:
```python
from dataclasses import dataclass, field
from typing import Any, Protocol
from langchain_core.runnables import RunnableConfig


@dataclass(frozen=True)
class TriageResult:
    handled: bool
    root_cause: str = ""
    plan: str = ""
    action_taken: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    verification: str = ""
    is_resolved: bool = False
    requires_escalation: bool = False

    def to_state_patch(self) -> dict[str, Any]:
        if not self.handled:
            return {"triage": "diagnose"}
        return {
            "triage": "handled",
            "root_cause": self.root_cause,
            "plan": self.plan,
            "action_taken": self.action_taken,
            "actions": self.actions,
            "verification": self.verification,
            "is_resolved": self.is_resolved,
            "requires_escalation": self.requires_escalation,
        }


class TriageHandler(Protocol):
    def can_handle(self, state: dict[str, Any]) -> bool: ...

    async def execute(
        self, state: dict[str, Any], config: RunnableConfig
    ) -> TriageResult | None: ...
```

In `packages/agents/lyoko/src/lyoko/application/triage/dispatcher.py`:
```python
import logging
from collections.abc import Callable, Sequence
from typing import Any
from langchain_core.runnables import RunnableConfig
from lyoko.application.triage.base import TriageHandler

logger = logging.getLogger("lyoko.workflow.triage")

TRIAGE_DIAGNOSE = "diagnose"
TRIAGE_HANDLED = "handled"


def choose_triage(state: dict[str, Any]) -> str:
    """Route a handled fast-path incident to notify, otherwise continue to diagnose."""
    return TRIAGE_HANDLED if state.get("triage") == TRIAGE_HANDLED else TRIAGE_DIAGNOSE


def create_triage_node(
    handlers: Sequence[TriageHandler],
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the composite triage node delegating to registered handlers."""

    async def triage_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        for handler in handlers:
            try:
                if handler.can_handle(state):
                    result = await handler.execute(state, config)
                    if result is not None and result.handled:
                        return result.to_state_patch()
            except Exception as exc:
                logger.warning(
                    "Triage handler %s failed: %s; falling through.",
                    handler.__class__.__name__,
                    exc,
                )
        return {"triage": TRIAGE_DIAGNOSE}

    return triage_node
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/lyoko/test_triage_dispatcher.py -v`
Expected: PASS

- [ ] **Step 5: Verify clean architecture and line limits**

Run: `uv run pytest tests/test_clean_architecture.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/agents/lyoko/src/lyoko/application/triage/ tests/agents/lyoko/test_triage_dispatcher.py
git commit -m "feat(lyoko): implement deterministic triage dispatcher architecture"
```

---

### Task 2: Migrate Argo CD OutOfSync to Triage Handler

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/triage/argocd_autosync.py`
- Modify: `packages/agents/lyoko/src/lyoko/application/nodes/argocd_autosync.py` (backward-compatibility wrapper)
- Test: `tests/agents/lyoko/test_argocd_autosync.py`

**Interfaces:**
- Consumes: `parse_outofsync_app`, `enable_autosync`, `is_synced_and_healthy`, `manifest_from_tool_result`, `manifest_to_yaml` from `lyoko.application.argocd_outofsync`
- Produces: `ArgoCDAutosyncHandler` implementing `TriageHandler` protocol.

- [ ] **Step 1: Write test for `ArgoCDAutosyncHandler` supporting both alert and message**

In `tests/agents/lyoko/test_argocd_autosync.py`, add tests asserting that `can_handle` returns `True` for:
1. Message: `Argo CD application arr-stack has sync status OutOfSync`
2. Alert: `alert_name == "ArgoCDAppOutOfSync"` with label `name: "arr-stack"`

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/lyoko/test_argocd_autosync.py -k "test_handler" -v`
Expected: FAIL

- [ ] **Step 3: Implement `ArgoCDAutosyncHandler` in `packages/agents/lyoko/src/lyoko/application/triage/argocd_autosync.py`**

Extract and encapsulate the execution logic from `packages/agents/lyoko/src/lyoko/application/nodes/argocd_autosync.py` into a clean `ArgoCDAutosyncHandler` class. Make sure it stays well under 250 lines.

- [ ] **Step 4: Update `create_argocd_autosync_node` to delegate to `ArgoCDAutosyncHandler`**

Keep `create_argocd_autosync_node` in `lyoko.application.nodes.argocd_autosync` so existing callers and tests remain 100% compatible.

- [ ] **Step 5: Run tests and clean architecture checks**

Run: `uv run pytest tests/agents/lyoko/test_argocd_autosync.py tests/test_clean_architecture.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/agents/lyoko/src/lyoko/application/triage/argocd_autosync.py packages/agents/lyoko/src/lyoko/application/nodes/argocd_autosync.py tests/agents/lyoko/test_argocd_autosync.py
git commit -m "refactor(lyoko): migrate Argo CD autosync to triage handler"
```

---

### Task 3: Implement `KubePodCrashLooping` Deterministic Triage Handler

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/triage/pod_crashloop.py`
- Test: `tests/agents/lyoko/test_triage_pod_crashloop.py`

**Detection & Logic:**
- `can_handle`:
  - Alert: `state.get("alert_name") == "KubePodCrashLooping"` or labels contain `namespace` + `pod` + crashloop indicator.
  - Message: operator mentions pod crashing in crashloop, e.g. "pod <name> in <ns> is crashlooping".
- Remediation:
  - Pod deletion via `k8s_pods_delete(name=pod, namespace=namespace)` so Kubernetes controller restarts it afresh (e.g. clears bad state / lock).
  - Puts action through `ToolGate` (operator approval requested via Telegram).
- Verification:
  - Polls `k8s_pods_get` / `k8s_pods_list_in_namespace` for the pod/controller.
  - Verifies that new pod is `Running` and no container is in `CrashLoopBackOff`.
  - If still crashlooping after bounded attempts, flags `requires_escalation=True` and falls through / reports status.

- [ ] **Step 1: Write unit tests for `PodCrashLoopHandler`**

Include:
- `can_handle` with alert `KubePodCrashLooping`
- `can_handle` with chat text
- successful restart with gate approval and verification
- refusal by operator
- verification failure

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/agents/lyoko/test_triage_pod_crashloop.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `PodCrashLoopHandler` in `packages/agents/lyoko/src/lyoko/application/triage/pod_crashloop.py`**

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/agents/lyoko/test_triage_pod_crashloop.py -v`
Expected: PASS

- [ ] **Step 5: Verify clean architecture rules**

Run: `uv run pytest tests/test_clean_architecture.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/agents/lyoko/src/lyoko/application/triage/pod_crashloop.py tests/agents/lyoko/test_triage_pod_crashloop.py
git commit -m "feat(lyoko): implement KubePodCrashLooping deterministic triage handler"
```

---

### Task 4: Implement `CloudflaredPodRestarts` & `CloudflaredPodNotReady` Deterministic Triage Handler

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/triage/cloudflare_tunnel.py`
- Test: `tests/agents/lyoko/test_triage_cloudflare_tunnel.py`

**Detection & Logic:**
- `can_handle`:
  - Alert: `alert_name` in `("CloudflaredPodNotReady", "CloudflaredPodRestarts")` or (`namespace == "cloudflare-tunnel"` and `deployment == "cloudflare-tunnel"`).
- Remediation:
  - Deletes pod in namespace `cloudflare-tunnel` (or triggers deployment restart) using `k8s_pods_delete` after asking operator approval.
- Verification:
  - Checks deployment available replicas >= 1 in namespace `cloudflare-tunnel` using `k8s_resources_get(apiVersion="apps/v1", kind="Deployment", name="cloudflare-tunnel", namespace="cloudflare-tunnel")`.

- [ ] **Step 1: Write unit tests for `CloudflareTunnelHandler`**

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/agents/lyoko/test_triage_cloudflare_tunnel.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `CloudflareTunnelHandler` in `packages/agents/lyoko/src/lyoko/application/triage/cloudflare_tunnel.py`**

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/agents/lyoko/test_triage_cloudflare_tunnel.py -v`
Expected: PASS

- [ ] **Step 5: Verify clean architecture rules**

Run: `uv run pytest tests/test_clean_architecture.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/agents/lyoko/src/lyoko/application/triage/cloudflare_tunnel.py tests/agents/lyoko/test_triage_cloudflare_tunnel.py
git commit -m "feat(lyoko): implement Cloudflared restart/not-ready deterministic triage handler"
```

---

### Task 5: Implement `ArgoCDAppSyncFailed` Deterministic Triage Handler

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/triage/argocd_sync_failed.py`
- Test: `tests/agents/lyoko/test_triage_argocd_sync_failed.py`

**Detection & Logic:**
- `can_handle`:
  - Alert: `alert_name == "ArgoCDAppSyncFailed"` with label `name: <app>`.
- Diagnostic check:
  - Fetches Application CRD via `k8s_resources_get(apiVersion="argoproj.io/v1alpha1", kind="Application", name=app, namespace="argocd")`.
  - Inspects `status.operationState`.
  - If already succeeded, resolves as transient/stale.
  - If comparison/syntax error (`ComparisonError`, invalid manifest in git), cannot be resolved automatically: returns `handled=False` (falls through to `diagnose` with rich context).
  - If transient lock/timeout or sync pending: requests approval to trigger retry / sync annotation or refresh, verifies health.

- [ ] **Step 1: Write unit tests for `ArgoCDSyncFailedHandler`**

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/agents/lyoko/test_triage_argocd_sync_failed.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `ArgoCDSyncFailedHandler` in `packages/agents/lyoko/src/lyoko/application/triage/argocd_sync_failed.py`**

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/agents/lyoko/test_triage_argocd_sync_failed.py -v`
Expected: PASS

- [ ] **Step 5: Verify clean architecture rules**

Run: `uv run pytest tests/test_clean_architecture.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/agents/lyoko/src/lyoko/application/triage/argocd_sync_failed.py tests/agents/lyoko/test_triage_argocd_sync_failed.py
git commit -m "feat(lyoko): implement ArgoCDAppSyncFailed deterministic triage handler"
```

---

### Task 6: Wire Composite Triage Node in Workflow & End-to-End Testing

**Files:**
- Modify: `packages/agents/lyoko/src/lyoko/application/workflow.py`
- Test: `tests/agents/lyoko/test_workflow.py`
- Test: `tests/agents/lyoko/test_workflow_nodes.py`

- [ ] **Step 1: Update `workflow.py` to instantiate and register all handlers into `create_triage_node`**
- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/`
Expected: All 435+ tests PASS.

- [ ] **Step 3: Run clean architecture tests & linter**

Run: `uv run pytest tests/test_clean_architecture.py`
Run: `uv run ruff check .`
Run: `uv run ruff format --check .`

- [ ] **Step 4: Commit**

```bash
git add packages/agents/lyoko/src/lyoko/application/workflow.py tests/
git commit -m "feat(lyoko): wire all deterministic triage handlers into workflow triage node"
```
