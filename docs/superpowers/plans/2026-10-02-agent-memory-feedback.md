# Agent Memory & Feedback Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement persistent semantic memory and an operator feedback loop for LYOKO using PostgreSQL, `pgvector`, Alembic migrations, and LangGraph workflow injection.

**Architecture:** Operator feedback and incident remediation lessons are stored in PostgreSQL with 1536-dim vector embeddings (`pgvector` with HNSW index) managed by Alembic. When an incident occurs, LYOKO's `diagnose_node` queries the most relevant past feedback and injects it into the LLM diagnostic prompt to prevent repeating mistakes. Operators can submit corrections via `POST /api/v1/feedback`.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, LangChain, PostgreSQL 18 + `pgvector` / `VectorChord`, Alembic, SQLAlchemy 2, `psycopg3`, `pytest-asyncio`.

## Global Constraints
- All dependencies must include an explicit major version ceiling (e.g., `alembic>=1.14.0,<2.0.0`).
- Strict English for all code, comments, docstrings, commits, and tests.
- Re-use existing PostgreSQL connection configuration (`settings.get_postgres_uri()`, `db_pool`).
- Defensive Alembic migration for `CREATE EXTENSION IF NOT EXISTS vector`.

---

### Task 1: Add Dependencies & Setup Alembic Migrations

**Files:**
- Modify: `packages/agents/lyoko/pyproject.toml`
- Create: `packages/agents/lyoko/alembic.ini`
- Create: `packages/agents/lyoko/migrations/env.py`
- Create: `packages/agents/lyoko/migrations/script.py.mako`
- Create: `packages/agents/lyoko/migrations/versions/0001_create_agent_memory_table.py`
- Test: `tests/agents/lyoko/test_migrations.py`

**Interfaces:**
- Produces: Alembic migration suite creating `agent_memory` table with `id`, `namespace`, `service_name`, `alert_name`, `incident_pattern`, `operator_feedback`, `action_rule`, `embedding (vector(1536))`, and HNSW index.

- [ ] **Step 1: Update `pyproject.toml` with `alembic`, `sqlalchemy`, `pgvector`**
- [ ] **Step 2: Run `uv sync` to update `uv.lock`**
- [ ] **Step 3: Create `alembic.ini` and `migrations/` setup with version 0001**
- [ ] **Step 4: Write test verifying migration generation and SQL structure**
- [ ] **Step 5: Run tests and verify passing**

---

### Task 2: Domain Models & Memory Repository

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/domain/models/memory.py`
- Create: `packages/agents/lyoko/src/lyoko/infrastructure/db/memory_repository.py`
- Modify: `packages/agents/lyoko/src/lyoko/config.py` (add embedding settings if needed)
- Test: `tests/agents/lyoko/test_memory_repository.py`

**Interfaces:**
- Produces:
  - `MemoryEntry` model (`namespace`, `service_name`, `alert_name`, `incident_pattern`, `operator_feedback`, `action_rule`, `created_at`).
  - `FeedbackRequest` model for API requests.
  - `PostgresMemoryRepository`:
    - `async def initialize(self) -> None`: Runs Alembic migrations or verifies schema.
    - `async def save_memory(self, entry: MemoryEntry, embedding: list[float] | None = None) -> int`: Persists memory.
    - `async def search_memories(self, query_embedding: list[float], namespace: str | None = None, service_name: str | None = None, limit: int = 3) -> list[MemoryEntry]`: Cosine similarity search (`<=>`).

- [ ] **Step 1: Write tests for memory models and repository methods (mocking DB pool)**
- [ ] **Step 2: Implement domain models in `lyoko/domain/models/memory.py`**
- [ ] **Step 3: Implement `PostgresMemoryRepository` in `lyoko/infrastructure/db/memory_repository.py`**
- [ ] **Step 4: Run repository tests and ensure all pass**

---

### Task 3: Embeddings Service & Workflow Memory Injection

**Files:**
- Create: `packages/agents/lyoko/src/lyoko/infrastructure/embeddings.py`
- Modify: `packages/agents/lyoko/src/lyoko/application/workflow.py`
- Test: `tests/agents/lyoko/test_workflow_memory.py`

**Interfaces:**
- Produces:
  - `EmbeddingsService`: generates embeddings using `OpenAIEmbeddings(model="text-embedding-3-small")` with graceful fallback for testing/offline mode.
  - `workflow.py`: `create_remediation_workflow(mcp_client, checkpointer=None, memory_repository=None, embeddings_service=None)`
  - `diagnose_node`: fetches top relevant memories for the incident and injects "PAST LESSONS & OPERATOR FEEDBACK" into the LLM diagnosis prompt.

- [ ] **Step 1: Write unit tests for `EmbeddingsService` and `diagnose_node` memory prompt injection**
- [ ] **Step 2: Implement `EmbeddingsService`**
- [ ] **Step 3: Update `workflow.py` to retrieve and format past lessons into the diagnostic prompt**
- [ ] **Step 4: Run workflow tests and verify memory injection behavior**

---

### Task 4: Feedback API Endpoint & Main Lifespan Integration

**Files:**
- Modify: `packages/agents/lyoko/src/lyoko/infrastructure/web/controller.py`
- Modify: `packages/agents/lyoko/src/lyoko/main.py`
- Test: `tests/agents/lyoko/test_feedback_endpoint.py`
- Test: `tests/agents/lyoko/test_main.py`

**Interfaces:**
- Produces:
  - `POST /api/v1/feedback`: Accepts `FeedbackRequest`, generates embedding, and persists to PostgreSQL.
  - `GET /api/v1/feedback`: Lists recent feedback entries.
  - `lifespan`: Initializes `PostgresMemoryRepository`, applies migrations on startup when PostgreSQL is configured.

- [ ] **Step 1: Write tests for `POST /api/v1/feedback` and `GET /api/v1/feedback`**
- [ ] **Step 2: Implement feedback routes in `controller.py`**
- [ ] **Step 3: Update `main.py` composition root to wire repository and run migration setup**
- [ ] **Step 4: Run full test suite (`pytest`) and linters (`ruff check .`, `ruff format .`)**
