<div align="center">

# ⚡ Homelab AIOps
### Autonomous SRE & Intelligent Operations Platform for Homelabs

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![FastMCP](https://img.shields.io/badge/FastMCP-gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![LangGraph](https://img.shields.io/badge/LangGraph-workflow-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<p align="center">
  <b>Event-driven multi-agent remediation, guardrail-protected tool execution, and continuous vector memory.</b>
  <br />
  Operates across <b>Kubernetes</b>, <b>UniFi Network</b>, <b>Home Assistant</b>, <b>Grafana</b>, and <b>GitHub</b>.
</p>

[Quick Start](docs/quickstart.md) · [Architecture](docs/architecture.md) · [Security & Guardrails](docs/security-guardrails.md) · [Packages](#packages)

</div>

---

## Overview

**`homelab-aiops`** is an open-source autonomous operations platform designed for Kubernetes homelabs and smart infrastructure. It pairs an event-driven **LangGraph** SRE multi-agent engine (**LYOKO**) with a unified, guardrail-protected **FastMCP** tool gateway (**`homelab-mcp`**).

When incidents occur, the system diagnoses root causes with read-only specialists, checks prior lessons stored in **PostgreSQL + pgvector**, and requests human approval (HITL) via **Telegram** for any unverified state modification.

---

## Why Homelab AIOps?

- 🧠 **Continuous Episodic Memory**: Past incident resolutions and operator rules are stored with dense vector embeddings (`text-embedding-3-small` with HNSW cosine indexing). Operators can teach new operational rules on the fly via Telegram (`/feedback`, `[💡 Teach Rule]`).
- 🛡️ **Zero-Trust Safety & HITL**: Investigation and verification are strictly read-only. Dangerous commands (`rm -rf`, `mkfs`) and protected namespaces (`kube-system`) are blocked at the gateway, while state-changing operations require explicit Telegram inline approval.
- 🔌 **Unified MCP Tool Gateway**: A single authenticated gateway exposes typed capabilities across Kubernetes, UniFi Network, Home Assistant, Grafana, and GitHub over Streamable HTTP (`/mcp`) and `stdio`.
- 🤖 **Hierarchical Multi-Agent Engine**: A central Supervisor plans and delegates tasks to domain specialists (**K8s SRE**, **Network Specialist**, **Smart Home Specialist**, **Metrics Specialist**) with domain-scoped tool catalogs.

---

## Architecture

<p align="center">
  <a href="docs/diagrams/system-architecture.html">
    <img src="docs/assets/system-architecture.png" alt="Homelab AIOps Platform Architecture" width="100%" />
  </a>
  <br>
  <em>Click diagram to launch interactive viewer with tracing, filters, and theme switching.</em>
</p>

---

## Two Operating Modes

```mermaid
flowchart LR
    subgraph Mode1 ["1. Autonomous Incident Remediation"]
        direction LR
        A1[Alertmanager] --> D1[1. Diagnose<br/>(Read-only)]
        D1 --> R1[2. Remediate<br/>(HITL Gated)]
        R1 --> V1[3. Verify<br/>(Read-only)]
        V1 --> N1[4. Notify & Learn]
    end

    subgraph Mode2 ["2. Interactive Operator Chat"]
        direction LR
        T2[Telegram Message] --> S2[Supervisor Agent]
        S2 --> SP2[Domain Specialists]
        SP2 --> G2[ToolGate / HITL]
        G2 --> R2[Telegram Response]
    end

    classDef mode fill:#0f766e,stroke:#115e59,color:#fff;
    class A1,D1,R1,V1,N1,T2,S2,SP2,G2,R2 mode;
```

1. **Incident Remediation**: Awakened by Prometheus Alertmanager webhooks, diagnosing root causes, forming remediation plans, requesting approval for mutations, verifying stabilization, and recording learned feedback.
2. **Interactive Operator Assistant**: A Telegram chat interface coordinated by the same Supervisor and Specialists for day-to-day operations, querying telemetry, executing changes, and teaching custom operational rules.

---

## Packages

| Package | Role | Description |
| :--- | :--- | :--- |
| [`homelab-mcp`](packages/mcps/homelab-mcp) | Tool Gateway & Harness | **FastMCP** server aggregating Kubernetes, UniFi, Home Assistant, Grafana, and GitHub with RBAC, scoped search, and safety guardrails. |
| [`lyoko`](packages/agents/lyoko) | Autonomous SRE Engine | **LangGraph** multi-agent orchestrator with hierarchical domain delegation, Telegram HITL approvals, and episodic vector memory. |

---

## Quick Start (tl;dr)

```bash
# 1. Clone & install dependencies
git clone https://github.com/csp33/homelab-aiops.git
cd homelab-aiops
uv sync

# 2. Configure environment
cp .env.example .env

# 3. Start services
uv run --package homelab-mcp python -m homelab_mcp.server   # Gateway on :8000
uv run --package lyoko python -m lyoko.main                 # Agent on :9000
```

👉 See the complete **[Quick Start Guide](docs/quickstart.md)** for detailed `.env` options, database setup, and Docker instructions.

---

## Documentation

- 🚀 [**Quick Start Guide**](docs/quickstart.md): Step-by-step setup, configuration options, and running tests.
- 📐 [**System Architecture & Incident Lifecycle**](docs/architecture.md): Multi-agent orchestration, sequence diagrams, and vector memory retrieval.
- 🛡️ [**Security & Safety Guardrails**](docs/security-guardrails.md): Guardrail engine, namespace isolation, command sanitization, and GitOps policies.
- 🔌 [**`homelab-mcp` Gateway Guide**](packages/mcps/homelab-mcp/README.md): Available tools, scoped tool search, and IDE integration (Claude Desktop, Cursor).
- 🤖 [**`lyoko` Agent Guide**](packages/agents/lyoko/README.md): StateGraph workflows, Alertmanager integration, Telegram bot, and Langfuse tracing.

---

## License

Distributed under the [MIT License](LICENSE).