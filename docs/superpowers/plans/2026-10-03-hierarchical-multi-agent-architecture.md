# Hierarchical Multi-Agent Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a hierarchical multi-agent architecture in `homelab-aiops` with domain-specialized subagents (K8s, UniFi Network, Home Assistant, Observability) receiving direct tool pools without tool-search overhead, orchestrated by a top-level Supervisor and exposed as `Agent-as-a-Tool` via MCP for external IDEs (Claude Desktop / Cursor).

**Architecture:** 
- `homelab-mcp`: Exposes domain-partitioned tool pools (`k8s`, `unifi`, `homeassistant`, `grafana`, `github`) and security guardrails.
- `LYOKO`: Contains specialized domain agents (`K8sSpecialist`, `NetworkSpecialist`, `SmartHomeSpecialist`, `ObservabilitySpecialist`) with direct domain tool injection (`tools=[...]`), a top-level `SupervisorAgent` in LangGraph that breaks multi-step user requests into specialist calls, and an MCP server endpoint exposing high-level `Agent-as-a-Tool` functions (`ask_network_expert`, `ask_k8s_sre`, `ask_smarthome_expert`, `diagnose_incident`).

**Tech Stack:** Python 3.13+, LangGraph, LangChain, FastMCP, FastAPI, Pydantic v2, pytest-asyncio.

---

## Global Constraints
- Strict English only for all code, comments, docstrings, commits, and tests.
- Clean Architecture (Ports & Adapters) strictly enforced: no vendor/framework SDK imports in `domain/` or `application/`.
- All dependencies must have explicit major version ceilings.
- Deterministic, high-speed execution with full unit test coverage.

---

### Task 1: Domain Tool Pools in `homelab-mcp`

**Files:**
- Modify: `packages/mcps/homelab-mcp/src/homelab_mcp/application/service.py`
- Modify: `packages/mcps/homelab-mcp/src/homelab_mcp/infrastructure/mcp/server.py`
- Test: `tests/mcps/homelab_mcp/test_gateway_service.py`

**Interfaces:**
- Produces: `async def get_domain_tools(self, domain: str) -> list[ToolDefinition]` in `MCPGatewayService`
- Exposes: MCP tool `gateway_get_domain_tools(domain: str) -> list[dict]` in `infrastructure/mcp/server.py`

- [ ] **Step 1: Write failing unit test for `get_domain_tools`**

```python
@pytest.mark.asyncio
async def test_gateway_get_domain_tools(mock_auth):
    mock_k8s = MagicMock(spec=UpstreamMCPInterface)
    mock_k8s.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="k8s_get_pods",
                description="List pods",
                upstream_type=UpstreamType.KUBERNETES,
            )
        ]
    )
    gateway = MCPGatewayService(
        upstreams={UpstreamType.KUBERNETES: mock_k8s},
        auth_port=mock_auth,
    )
    tools = await gateway.get_domain_tools("kubernetes")
    assert len(tools) == 1
    assert tools[0].name == "k8s_get_pods"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcps/homelab_mcp/test_gateway_service.py -k test_gateway_get_domain_tools -v`
Expected: FAIL (`AttributeError: 'MCPGatewayService' object has no attribute 'get_domain_tools'`)

- [ ] **Step 3: Implement `get_domain_tools` in `MCPGatewayService` and server tool**

```python
async def get_domain_tools(self, domain: str) -> list[ToolDefinition]:
    """Retrieve all allowed tools belonging to a specific upstream domain."""
    tools = await self.discover_tools()
    canonical_target = UPSTREAM_ALIASES.get(domain.strip().lower(), domain.strip().lower())
    return [
        t for t in tools
        if canonical_target == str(t.upstream_type).lower()
        or canonical_target in str(t.upstream_type).lower()
        or canonical_target in t.name.lower()
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcps/homelab_mcp/test_gateway_service.py -k test_gateway_get_domain_tools -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add packages/mcps/homelab-mcp/src/homelab_mcp/application/service.py packages/mcps/homelab-mcp/src/homelab_mcp/infrastructure/mcp/server.py tests/mcps/homelab_mcp/test_gateway_service.py
git commit -m "feat(mcp): add get_domain_tools to retrieve curated domain tool pools"
```

---

### Task 2: Domain Specialist Prompts & Subagents in `lyoko`

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/specialists/__init__.py`
- Create: `packages/agents/lyoko/src/lyoko/application/specialists/prompts.py`
- Create: `packages/agents/lyoko/src/lyoko/application/specialists/agent.py`
- Test: `tests/agents/lyoko/test_specialists.py`

**Interfaces:**
- Produces: `class DomainSpecialistAgent` and specialist system prompts (`NETWORK_EXPERT_PROMPT`, `K8S_EXPERT_PROMPT`, `SMARTHOME_EXPERT_PROMPT`, `OBSERVABILITY_EXPERT_PROMPT`)

- [ ] **Step 1: Write failing test for `DomainSpecialistAgent`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from lyoko.application.specialists.agent import DomainSpecialistAgent
from lyoko.domain.interfaces.llm import LLMClientInterface

@pytest.mark.asyncio
async def test_domain_specialist_execution():
    mock_llm = MagicMock(spec=LLMClientInterface)
    mock_llm.chat = AsyncMock(return_value="Client top 1: humberto (435 GB)")
    
    agent = DomainSpecialistAgent(
        name="NetworkSpecialist",
        domain="unifi",
        system_prompt="You are UniFi Expert.",
        tools=[MagicMock(name="unifi_get_top_clients")],
        llm=mock_llm,
    )
    
    response = await agent.run("Who is consuming the most traffic?")
    assert "humberto" in response
    mock_llm.chat.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/lyoko/test_specialists.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'lyoko.application.specialists'`)

- [ ] **Step 3: Implement `DomainSpecialistAgent` and prompts**

Create `DomainSpecialistAgent` with direct domain tools binding and dedicated system prompts for network, k8s, domotics, and metrics.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/lyoko/test_specialists.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add packages/agents/lyoko/src/lyoko/application/specialists/ tests/agents/lyoko/test_specialists.py
git commit -m "feat(lyoko): implement domain specialist agents and specialized prompts"
```

---

### Task 3: Multi-Agent Supervisor & Multi-Step Planner in `lyoko`

**Files:**
- Modify: `packages/agents/lyoko/src/lyoko/application/workflow.py`
- Modify: `packages/agents/lyoko/src/lyoko/application/router.py`
- Create: `packages/agents/lyoko/src/lyoko/application/supervisor.py`
- Test: `tests/agents/lyoko/test_supervisor.py`

**Interfaces:**
- Produces: `class SupervisorAgent` exposing callable specialist tools (`ask_network_expert`, `ask_k8s_sre`, `ask_smarthome_expert`, `ask_metrics_expert`).
- Integrates with: `LyokoState` in `workflow.py`.

- [ ] **Step 1: Write failing test for Supervisor multi-step coordination**

```python
@pytest.mark.asyncio
async def test_supervisor_multi_step_delegation():
    mock_k8s_specialist = AsyncMock(return_value="Pod memory updated to 512Mi")
    mock_ha_specialist = AsyncMock(return_value="Zigbee integration reloaded")
    
    supervisor = SupervisorAgent(
        specialists={
            "kubernetes": mock_k8s_specialist,
            "homeassistant": mock_ha_specialist,
        },
        llm=mock_llm_runner,
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

### Task 4: FastMCP Agent-as-a-Tool Endpoint for External IDEs

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/infrastructure/mcp/server.py`
- Modify: `packages/agents/lyoko/src/lyoko/infrastructure/web/controller.py`
- Modify: `packages/agents/lyoko/src/lyoko/main.py`
- Test: `tests/agents/lyoko/test_mcp_agent_server.py`

**Interfaces:**
- Produces: FastMCP endpoint at `/mcp` exposing:
  - `ask_network_expert(query: str) -> str`
  - `ask_k8s_sre(query: str) -> str`
  - `ask_smarthome(query: str) -> str`
  - `diagnose_incident(alert_or_query: str) -> str`

- [ ] **Step 1: Write failing test for Lyoko FastMCP server tools**

```python
@pytest.mark.asyncio
async def test_lyoko_mcp_agent_as_a_tool():
    mcp_server = create_lyoko_mcp_server(mock_supervisor)
    tools = await mcp_server.list_tools()
    tool_names = [t.name for t in tools]
    assert "ask_network_expert" in tool_names
    assert "ask_k8s_sre" in tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/lyoko/test_mcp_agent_server.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `create_lyoko_mcp_server` and mount in FastAPI**

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/lyoko/test_mcp_agent_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add packages/agents/lyoko/src/lyoko/infrastructure/mcp/ packages/agents/lyoko/src/lyoko/infrastructure/web/controller.py tests/agents/lyoko/test_mcp_agent_server.py
git commit -m "feat(lyoko): expose FastMCP Agent-as-a-Tool endpoint for Claude Desktop and Cursor"
```

---

### Task 5: Full Test Suite Verification & Clean Architecture Audit

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

- [ ] **Step 4: Final commit and branch validation**

```bash
git status
```
