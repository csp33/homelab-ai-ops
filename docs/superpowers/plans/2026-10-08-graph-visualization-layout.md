# Graph Visualization Layout Refactor (Option B - Inline Coordinator & Specialists) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform LYOKO's StateGraph into an inline coordinator/specialist topology matching the target visualization (Capture 1 / Option B), exposing the multi-agent coordinator, domain specialist nodes (`kubernetes`, `unifi`, `homeassistant`, `grafana`), and subsequent remediation/verification pipeline.

**Architecture:** Decompose the monolith `diagnose`/`chat` nodes into an inline LangGraph coordinator loop. The `coordinator` node handles LLM reasoning and conditional routing: delegating to specialist nodes (`kubernetes`, `unifi`, `homeassistant`, `grafana`) which loop back to the `coordinator`. Once reasoning concludes, the router transitions to `remediate -> verify -> notify` (for actionable incidents) or directly to `notify` (for chat and unfixable incidents).

**Tech Stack:** Python 3.14+, LangGraph 1.2+, LangChain Core, Pydantic, pytest-asyncio.

---

## Global Constraints
- **Clean Architecture:** `domain/` and `application/` must never import `lyoko.infrastructure` or vendor SDKs (`ChatOpenAI`, `langchain_openai`, `telegram`, etc.).
- **No `__all__`:** Strictly forbidden across all modules.
- **Empty `__init__.py`:** All `__init__.py` files must remain 0 bytes.
- **File line limits:** All domain and application files must stay strictly under 280 lines.
- **Test coverage:** All existing unit and integration tests must pass without regressions.

---

## Task Decomposition

### Task 1: Create Domain Specialist Graph Nodes

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/nodes/specialists.py`
- Test: `tests/agents/lyoko/test_workflow_specialist_nodes.py`

**Interfaces:**
- Produces: `create_specialist_node(domain: str, specialist: Any, mcp_client: Any, approval_manager: Any, chat_manager: Any)`
- Consumes: `DomainSpecialistAgent`, `make_gate`, `ToolGate`

- [ ] **Step 1: Write unit test for specialist node execution and state updates**
- [ ] **Step 2: Implement `create_specialist_node` in `specialists.py`**
- [ ] **Step 3: Run pytest on the new tests**

---

### Task 2: Create Coordinator Graph Node and Conditional Edge Router

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/application/nodes/coordinator.py`
- Test: `tests/agents/lyoko/test_workflow_coordinator_node.py`

**Interfaces:**
- Produces: `create_coordinator_node(llm, supervisor, ...)` and `choose_coordinator_next(state: LyokoState) -> str`
- Consumes: `LyokoState`, `GateMode`, `SupervisorAgent`

- [ ] **Step 1: Write unit tests for coordinator node handling delegation vs final resolution**
- [ ] **Step 2: Implement `create_coordinator_node` and `choose_coordinator_next` in `coordinator.py`**
- [ ] **Step 3: Run pytest on coordinator tests**

---

### Task 3: Rewire `LyokoState` and `create_lyoko_graph` in `workflow.py`

**Files:**
- Modify: `packages/agents/lyoko/src/lyoko/application/workflow.py`
- Test: `tests/agents/lyoko/test_workflow.py`
- Test: `tests/agents/lyoko/test_graph_supervisor.py`

**Interfaces:**
- Produces: `create_lyoko_graph(...)` with topology:
  - `START -> route`
  - `route -> triage` (alert) or `coordinator` (message)
  - `triage -> notify` (handled) or `coordinator` (diagnose)
  - `coordinator <-> kubernetes, unifi, homeassistant, grafana`
  - `coordinator -> remediate` (actionable incident)
  - `coordinator -> notify` (chat response or non-actionable incident)
  - `remediate -> verify -> notify -> END`

- [ ] **Step 1: Update `LyokoState` with coordinator tracking fields**
- [ ] **Step 2: Wire specialist nodes and coordinator edges in `create_lyoko_graph`**
- [ ] **Step 3: Update and verify `test_workflow.py` and `test_graph_supervisor.py`**

---

### Task 4: Full Verification and Mermaid Visual Export

**Files:**
- Test: Run full suite `uv run pytest`
- Test: Run clean architecture test `uv run pytest tests/test_clean_architecture.py`

- [ ] **Step 1: Run full test suite and fix any regressions**
- [ ] **Step 2: Export mermaid graph and verify topology structure matches Capture 1 / Option B**
- [ ] **Step 3: Git commit the changes**
