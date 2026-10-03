<div align="center">

# Homelab AIOps

**Autonomous SRE and multi-agent operations platform for Kubernetes and smart infrastructure.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![FastMCP](https://img.shields.io/badge/FastMCP-gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![LangGraph](https://img.shields.io/badge/LangGraph-workflow-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<p align="center">
  Unified operations across <b>Kubernetes</b>, <b>UniFi Network</b>, <b>Home Assistant</b>, <b>Grafana</b>, and <b>GitHub</b>.
</p>

[Quick Start](docs/quickstart.md) · [Architecture](docs/architecture.md) · [Security](docs/security-guardrails.md) · [Packages](#packages)

</div>

---

## Overview

**Homelab AIOps** pairs an event-driven SRE multi-agent engine (**LYOKO**) with a unified, guardrail-protected tool gateway (**`homelab-mcp`**). 

When incidents occur, the system diagnoses root causes using read-only specialists, retrieves prior lessons from persistent vector memory (**PostgreSQL + pgvector**), and requests human approval (HITL) via **Telegram** before applying any state modification.

---

## Key Capabilities

- **Continuous Episodic Memory**: Stores incident resolutions and operator rules as vector embeddings in PostgreSQL. Retrieves relevant lessons during triage and allows operators to teach custom operational guidelines on the fly.
- **Zero-Trust Safety Harness**: Investigation and verification phases are strictly read-only. Destructive shell commands and protected namespaces are blocked at the gateway, while state-changing operations require explicit operator approval.
- **Unified Tool Gateway**: Aggregates Kubernetes, UniFi Network, Home Assistant, Grafana, and GitHub behind a single authenticated FastMCP gateway over Streamable HTTP and stdio.
- **Hierarchical Multi-Agent Engine**: A central LangGraph supervisor coordinates specialized domain subagents for cluster, network, smart home, and observability operations.

---

## Architecture

<p align="center">
  <img src="docs/assets/system-architecture.png" alt="Homelab AIOps Platform Architecture" width="100%" />
</p>

---

## Operating Modes

1. **Autonomous Incident Remediation**: Awakened by Prometheus Alertmanager webhooks. Runs an end-to-end loop: `Diagnose (Read-only) ➔ Remediate (Approval-Gated) ➔ Verify (Read-only) ➔ Notify & Learn`.
2. **Interactive Operator Assistant**: A conversational Telegram assistant for day-to-day operations, log queries, resource adjustments, and teaching operator rules.

---

## Packages

| Package | Role | Description |
| :--- | :--- | :--- |
| [`homelab-mcp`](packages/mcps/homelab-mcp) | Tool Gateway | FastMCP server aggregating upstream APIs with authentication, scoped tool search, and namespace guardrails. |
| [`lyoko`](packages/agents/lyoko) | Multi-Agent Engine | LangGraph orchestrator with hierarchical domain specialists, Telegram approvals, and episodic vector memory. |

---

## Quick Start

```bash
# 1. Clone repository and install dependencies
git clone https://github.com/csp33/homelab-aiops.git
cd homelab-aiops
uv sync

# 2. Configure environment
cp .env.example .env

# 3. Start services
uv run --package homelab-mcp python -m homelab_mcp.server   # Tool Gateway on :8000
uv run --package lyoko python -m lyoko.main                 # Remediation Agent on :9000
```

For environment variables, PostgreSQL setup, and testing guides, see the [Quick Start Guide](docs/quickstart.md).

---

## Documentation

- [Quick Start Guide](docs/quickstart.md): Step-by-step installation, `.env` options, and verification.
- [System Architecture](docs/architecture.md): Multi-agent design, sequence diagrams, and vector memory model.
- [Security & Guardrails](docs/security-guardrails.md): Namespace protections, command execution filtering, and GitOps policies.
- [`homelab-mcp` Gateway](packages/mcps/homelab-mcp/README.md): Available tools, scoped search, and IDE integration.
- [`lyoko` Agent](packages/agents/lyoko/README.md): StateGraph workflows, Alertmanager integration, and Langfuse tracing.

---

## License

Distributed under the [MIT License](LICENSE).