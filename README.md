# homelab-aiops

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![FastMCP](https://img.shields.io/badge/FastMCP-gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![LangGraph](https://img.shields.io/badge/LangGraph-workflow-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**`homelab-aiops`** is an open-source, autonomous operations and incident remediation platform for Kubernetes homelabs and smart infrastructure. 

It receives alerts from Prometheus Alertmanager, investigates root causes using read-only domain specialists, proposes fixes governed by safety guardrails, learns from operator feedback using persistent vector episodic memory (**PostgreSQL** + **pgvector**), and requests human-in-the-loop (HITL) approval via Telegram for any unverified state mutation.

[Architecture](#architecture) · [Packages](#packages) · [Key Capabilities](#key-capabilities) · [Quick Start](#quick-start) · [Documentation](#documentation)

---

## Architecture

`homelab-aiops` is organized into two core systems within a Python `uv` monorepo:

<p align="center">
  <a href="docs/diagrams/system-architecture.html">
    <img src="docs/assets/system-architecture.png" alt="Homelab AIOps Platform Architecture" width="100%" />
  </a>
  <br>
  <em>Click diagram to launch interactive viewer with tracing, filters, and theme switching.</em>
</p>

---

## Packages

| Package | Type | Description |
| :--- | :--- | :--- |
| [`homelab-mcp`](packages/mcps/homelab-mcp) | Tool Gateway & Harness | **FastMCP** server aggregating Kubernetes, UniFi, Home Assistant, Grafana, and GitHub APIs with RBAC, scoped tool search, and namespace guardrails. |
| [`lyoko`](packages/agents/lyoko) | Multi-Agent Orchestrator | **LangGraph** SRE engine with supervisor-led domain delegation, Telegram chat/HITL approvals, and episodic vector memory. |

---

## Key Capabilities

- **Autonomous 4-Stage Remediation**: Executes `diagnose` ➔ `remediate` ➔ `verify` ➔ `notify`. Diagnosis and verification are strictly read-only.
- **Continuous Episodic Memory (`pgvector`)**: Stores incident resolutions and operator rules as 1536-dimensional embeddings (HNSW cosine index). Operators can teach rules via Telegram (`/feedback`, `[💡 Teach Rule]`).
- **Human-in-the-Loop Safety (`ToolGate`)**: Destructive actions are blocked. State mutations require explicit Telegram inline approval unless allowlisted.
- **Unified Tool Gateway**: Exposes cluster and IoT tools over Streamable HTTP (`/mcp`) and `stdio` for both LYOKO and local IDEs (Claude Desktop, Cursor).
- **Interactive Chat Assistant**: Operators can query metrics, inspect logs, or request infrastructure changes directly via Telegram.

---

## Quick Start

### 1. Prerequisites

- [Python 3.13+](https://www.python.org/downloads/)
- [`uv`](https://docs.astral.sh/uv/) (Python package manager)
- `kubectl` configured with cluster context (or in-cluster ServiceAccount)

### 2. Setup

```bash
# Clone repository
git clone https://github.com/csp33/homelab-aiops.git
cd homelab-aiops

# Install workspace dependencies deterministically
uv sync

# Copy and configure environment variables
cp .env.example .env
```

### 3. Run Services

```bash
# Terminal 1: Start homelab-mcp Gateway (port 8000)
uv run --package homelab-mcp python -m homelab_mcp.server

# Terminal 2: Start LYOKO Agent (port 9000)
uv run --package lyoko python -m lyoko.main
```

### 4. Run Test Suite

```bash
# Run all unit and integration tests across the workspace
uv run pytest

# Lint and format checks
uv run ruff check .
```

---

## Documentation

- 📐 [**System Architecture & Incident Lifecycle**](docs/architecture.md): Deep-dive into multi-agent coordination, sequence diagrams, and vector memory retrieval.
- 🛡️ [**Security & Safety Guardrails**](docs/security-guardrails.md): Guardrail engine checks, protected namespaces, command sanitization, and GitOps policies.
- 🚪 [**`homelab-mcp` Gateway Guide**](packages/mcps/homelab-mcp/README.md): Available tools, scoped search algorithms, and IDE configuration.
- 🤖 [**`LYOKO` Agent Guide**](packages/agents/lyoko/README.md): StateGraph design, Alertmanager webhook setup, Telegram bot, and Langfuse tracing.

---

## License

This project is licensed under the [MIT License](LICENSE).