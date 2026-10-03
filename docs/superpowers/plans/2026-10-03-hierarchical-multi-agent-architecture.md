# Hierarchical Multi-Agent & Scoped Tool Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a scalable hierarchical multi-agent architecture in `LYOKO` (Supervisor + Domain Specialist Subagents for Telegram & Alertmanager) while leveraging `homelab-mcp`'s relevance-scored Scoped Tool Search for both external IDEs (Claude Desktop/Cursor, $0 OpenAI API cost) and domain specialists.

**Architecture:**
- **`homelab-mcp` (Tool Hub & Scoped Search Engine)**:
  - Serves operational tools across upstreams (`kubernetes`, `unifi`, `homeassistant`, `grafana`, `github`).
  - Provides multi-token relevance scoring, read/mutation intent weighting, and category aliases via `gateway_list_tools(query, upstream)`.
  - Enforces centralized safety guardrails and namespace protections.
- **External IDEs (Claude Desktop / Cursor)**:
  - Connects directly to `homelab-mcp` using Scoped Tool Search. Claude performs reasoning on its own subscription ($0 OpenAI API cost) with lean context windows (<2,000 tokens).
- **`LYOKO` (Autonomous Incident Remediation & Telegram Multi-Agent Graph)**:
  - `SupervisorAgent` in LangGraph: Triages incoming events and coordinates cross-domain multi-step operations (e.g. scale K8s pod ➔ reload Home Assistant integration).
  - `DomainSpecialists` (`K8sSpecialist`, `NetworkSpecialist`, `SmartHomeSpecialist`, `ObservabilitySpecialist`): Focused domain subagents executing within their scoped toolset.
  - `IncidentBranch` (Diagnose ➔ Remediate ➔ Verify ➔ Notify): SRE loop utilizing domain specialists for targeted inspection and verified remediation.
  - `ToolGate`: Shared policy governing read-only vs interactive Telegram HITL approvals.

**Tech Stack:** Python 3.13+, LangGraph, LangChain, FastMCP, FastAPI, Pydantic v2, pytest-asyncio.

---

## Global Constraints
- Strict English only for all code, comments, docstrings, commits, and tests.
- Clean Architecture (Ports & Adapters) strictly enforced: no vendor/framework SDK imports in `domain/` or `application/`.
- All dependencies must have explicit major version ceilings.
- Deterministic, high-speed execution with full unit test coverage.

---

### Task 1: Scoped Domain Search & Tool Pools in `homelab-mcp`

**Files:**
- Modify: `packages/mcps/homelab-mcp/src/homelab_mcp/application/service.py`
- Modify: `packages/mcps/homelab-mcp/src/homelab_mcp/infrastructure/mcp/server.py`
- Test: `tests/mcps/homelab_mcp/test_gateway_service.py`

**Interfaces:**
- Produces: `async def search_tools(self, query: str | None = None, upstream: str | None = None, limit: int = 25) -> list[ToolDefinition]` in `MCPGatewayService`
- Exposes: `gateway_list_tools(query, upstream, limit)` in `infrastructure/mcp/server.py`

- [ ] **Step 1: Verify and write unit tests for scoped domain tool search**

```python
@pytest.mark.asyncio
async def test_gateway_scoped_domain_search(mock_auth):
    # Verify searching within specific upstream domain returns scoped ranked tools
    gateway = MCPGatewayService(upstreams={...}, auth_port=mock_auth)
    k8s_tools = await gateway.search_tools(upstream="kubernetes", query="pod logs")
    assert all(t.upstream_type == UpstreamType.KUBERNETES for t in k8s_tools)
```

- [ ] **Step 2: Run test to verify passes/fails**

Run: `uv run pytest tests/mcps/homelab_mcp/test_gateway_service.py -v`
Expected: PASS

- [ ] **Step 3: Commit verification**

```bash
git commit --allow-empty -m "chore(mcp): verify scoped domain search capabilities"
```

---

### Task 2: Domain Specialist Subagents & Scoped Prompts in `lyoko`

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/specialists/__init__.py`
- Create: `packages/agents/lyoko/src/lyoko/application/specialists/prompts.py`
- Create: `packages/agents/lyoko/src/lyoko/application/specialists/agent.py`
- Test: `tests/agents/lyoko/test_specialists.py`

**Interfaces:**
- Produces: `class DomainSpecialistAgent` with scoped upstream binding (`upstream="unifi"`, `upstream="kubernetes"`, `upstream="homeassistant"`, `upstream="grafana"`)
- Prompts: `NETWORK_EXPERT_PROMPT`, `K8S_EXPERT_PROMPT`, `SMARTHOME_EXPERT_PROMPT`, `OBSERVABILITY_EXPERT_PROMPT`

- [ ] **Step 1: Write failing test for `DomainSpecialistAgent`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from lyoko.application.specialists.agent import DomainSpecialistAgent
from lyoko.domain.interfaces.llm import LLMClientInterface

@pytest.mark.asyncio
async def test_domain_specialist_runs_with_scoped_domain():
    mock_llm = MagicMock(spec=LLMClientInterface)
    mock_llm.chat = AsyncMock(return_value="Client top 1: humberto (435 GB)")
    mock_mcp = MagicMock()
    
    agent = DomainSpecialistAgent(
        name="NetworkSpecialist",
        domain="unifi",
        system_prompt="You are UniFi Expert.",
        mcp_client=mock_mcp,
        llm=mock_llm,
    )
    
    response = await agent.run("Who is consuming the most traffic?")
    assert "humberto" in response
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/lyoko/test_specialists.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'lyoko.application.specialists'`)

- [ ] **Step 3: Implement `DomainSpecialistAgent` and domain prompts**

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/lyoko/test_specialists.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add packages/agents/lyoko/src/lyoko/application/specialists/ tests/agents/lyoko/test_specialists.py
git commit -m "feat(lyoko): implement domain specialist subagents with scoped prompts"
```

---

### Task 3: Multi-Agent Supervisor & Multi-Step Planner in `lyoko`

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/supervisor.py`
- Modify: `packages/agents/lyoko/src/lyoko/application/workflow.py`
- Modify: `packages/agents/lyoko/src/lyoko/application/router.py`
- Test: `tests/agents/lyoko/test_supervisor.py`

**Interfaces:**
- Produces: `class SupervisorAgent` exposing specialist delegators as LangGraph tools / subgraphs.
- Integrates with: `LyokoState` in `workflow.py`.

- [ ] **Step 1: Write failing test for Supervisor multi-step cross-domain coordination**

```python
@pytest.mark.asyncio
async def test_supervisor_coordinates_k8s_and_ha():
    mock_k8s = AsyncMock(return_value="Pod memory updated to 512Mi")
    mock_ha = AsyncMock(return_value="Zigbee integration reloaded")
    
    supervisor = SupervisorAgent(
        specialists={
            "kubernetes": mock_k8s,
            "homeassistant": mock_ha,
        },
        llm=mock_llm,
    )
    result = await supervisor.coordinate("Scale pod zigbee2mqtt memory and reload zigbee in HA")
    assert "512Mi" in result
    assert "reloaded" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/lyoko/test_supervisor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `SupervisorAgent` and integrate into `workflow.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agents/lyoko/test_supervisor.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add packages/agents/lyoko/src/lyoko/application/supervisor.py packages/agents/lyoko/src/lyoko/application/workflow.py tests/agents/lyoko/test_supervisor.py
git commit -m "feat(lyoko): implement multi-agent supervisor for cross-domain orchestration"
```

---

### Task 4: Full Workspace Integration, Clean Architecture Audit & Verification

**Files:**
- Test: `tests/`
- Check: `tests/test_clean_architecture.py`

- [ ] **Step 1: Run full pytest test suite across workspace**

Run: `uv run pytest`
Expected: 100% tests PASS

- [ ] **Step 2: Run AST Clean Architecture layer boundary tests**

Run: `uv run pytest tests/test_clean_architecture.py`
Expected: PASS (0 architectural violations)

- [ ] **Step 3: Run formatting and linting checks**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS

- [ ] **Step 4: Push branch to remote**

```bash
git push origin investigate_root_cause
```
