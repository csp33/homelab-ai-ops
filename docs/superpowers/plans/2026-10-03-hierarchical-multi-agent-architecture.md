# Hierarchical Multi-Agent & Scoped MCP Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a cost-optimal hierarchical multi-agent architecture where `homelab-mcp` exposes scoped domain endpoints for external IDEs (Claude Desktop/Cursor, $0 OpenAI API cost), while `LYOKO` uses domain-specialized subagents with direct tool pools for Telegram and autonomous Alertmanager remediation.

**Architecture:**
- **`homelab-mcp` (Tool Hub & Scoped Endpoints)**:
  - Serves domain-partitioned tool pools (`kubernetes`, `unifi`, `homeassistant`, `grafana`, `github`) via `get_domain_tools(domain)`.
  - Exposes dedicated FastMCP scoped routes (e.g. `/mcp/k8s`, `/mcp/network`, `/mcp/iot`) so Claude Desktop/Cursor can connect directly to domain tools and execute reasoning on Anthropic's subscription.
- **`LYOKO` (Autonomous & Telegram Multi-Agent Graph)**:
  - `SupervisorAgent` in LangGraph: Triages incoming requests and coordinates multi-step cross-domain actions.
  - `DomainSpecialistAgent` instances (`K8sSpecialist`, `NetworkSpecialist`, `SmartHomeSpecialist`, `ObservabilitySpecialist`): Initialized with direct domain tool pools (`tools=[...]`), eliminating runtime `tool_search` overhead and latency.
  - `ToolGate`: Centralized safety gate enforcing read-only vs HITL Telegram approval.

**Tech Stack:** Python 3.13+, LangGraph, LangChain, FastMCP, FastAPI, Pydantic v2, pytest-asyncio.

---

## Global Constraints
- Strict English only for all code, comments, docstrings, commits, and tests.
- Clean Architecture (Ports & Adapters) strictly enforced: no vendor/framework SDK imports in `domain/` or `application/`.
- All dependencies must have explicit major version ceilings.
- Deterministic, high-speed execution with full unit test coverage.

---

### Task 1: Domain Tool Pools & Scoped Endpoints in `homelab-mcp`

**Files:**
- Modify: `packages/mcps/homelab-mcp/src/homelab_mcp/application/service.py`
- Modify: `packages/mcps/homelab-mcp/src/homelab_mcp/infrastructure/mcp/server.py`
- Test: `tests/mcps/homelab_mcp/test_gateway_service.py`

**Interfaces:**
- Produces: `async def get_domain_tools(self, domain: str) -> list[ToolDefinition]` in `MCPGatewayService`
- Exposes: Scoped FastMCP sub-apps or domain filtering endpoints (`gateway_get_domain_tools`)

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

- [ ] **Step 3: Implement `get_domain_tools` in `MCPGatewayService`**

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

### Task 2: Domain Specialist Agents & Curated Prompts in `lyoko`

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

Create `DomainSpecialistAgent` binding direct domain tools into the LLM context.

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
- Produces: `class SupervisorAgent` orchestrating specialists as tools/subgraphs for complex or cross-domain queries.
- Integrates with: `LyokoState` in `workflow.py`.

- [ ] **Step 1: Write failing test for Supervisor multi-step delegation**

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

- [ ] **Step 3: Implement `SupervisorAgent` and wire into LangGraph StateGraph**

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

- [ ] **Step 4: Final commit and branch push**

```bash
git status
```
