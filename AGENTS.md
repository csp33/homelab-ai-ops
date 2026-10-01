# AGENTS.md — Homelab AIOps

Project context, architectural standards, and operating rules for AI coding agents and contributors working in `homelab-aiops`.

---

## 1. Project Overview

`homelab-aiops` is a modular, open-source Homelab AIOps & autonomous operations platform designed for Kubernetes homelab environments and smart infrastructure.

The platform consists of two primary systems within a Python `uv` monorepo:

1. **`homelab-mcp` (Tool Gateway & Safety Harness)**:
   - Built on **FastMCP** (Model Context Protocol).
   - Serves as a unified tool aggregator providing structured, typed, and RBAC-controlled tools for:
     - Kubernetes inspection and safe patching (pod diagnostics, logs, resource bump, rollout restart).
     - Home Assistant IoT operations (service calls, state inspection).
     - UniFi Network management (client discovery, device status, port management).
     - Telegram alert and interactive reporting.
   - Operates over Streamable HTTP (`/mcp`) and stdio transports, allowing both autonomous in-cluster agents and local developer IDEs (Antigravity, Cursor, Claude) to use the exact same tool suite safely.

2. **`LYOKO` (Autonomous Remediation Agent)**:
   - **L**ive **Y**aml **O**ptimization & **K**8s **O**rchestration.
   - Built with **LangGraph** (StateGraph / Finite State Machine) and **FastAPI**.
   - Event-driven: Awakened by Prometheus Alertmanager webhooks or Kubernetes event watchers when pods crash (`OOMKilled`, `CrashLoopBackOff`, volume errors).
   - Executes a deterministic ReAct / remediation workflow:
     1. **Diagnose**: Fetches logs and pod termination reasons via `homelab-mcp`.
     2. **Decide & Guard**: Computes required resource adjustments (e.g., memory increment from 512Mi to 1Gi) with fallback boundaries.
     3. **Human-in-the-Loop (HITL)**: Can pause critical remediations to request approval via Telegram inline buttons.
     4. **Remediate**: Applies live patches or triggers GitOps updates.
     5. **Verify**: Waits for pod stabilization and confirms health.
     6. **Notify**: Posts structured markdown reports to Telegram with full root-cause attribution.

---

## 2. Core Rules & Development Guidelines

### Language & Style
- **Strict English Only**: All code, docstrings, comments, commit messages, PR descriptions, test cases, and documentation (`README.md`, `AGENTS.md`, etc.) **must always be written in English**.

### Security & Zero-Leak Policy (Public Repository)
- This repository is **public**. Under no circumstances should secrets, real API keys, bearer tokens, Telegram bot tokens, WireGuard keys, internal production domains, or private network identifiers be committed.
- All secrets must be loaded via environment variables using `.env` (ignored by git) and documented through `.env.example`.
- All Kubernetes operations in `homelab-mcp` must validate inputs using Pydantic models and enforce namespace allowlists / denylists (e.g., blocking mutations in `kube-system` unless explicitly configured).

### Monorepo Structure (`uv` Workspace & Clean Architecture)

```text
homelab-aiops/
├── pyproject.toml              # Root uv workspace configuration
├── uv.lock                     # Shared deterministic dependency lock
├── .env.example                # Documented configuration template
├── packages/
│   ├── mcps/                   # MCP Server packages (Capabilities & Tool Hubs)
│   │   └── homelab-mcp/        # FastMCP Gateway package
│   │       ├── pyproject.toml
│   │       ├── Dockerfile
│   │       └── src/
│   │           └── homelab_mcp/
│   │               ├── domain/
│   │               │   ├── models/     # k8s.py, homeassistant.py, unifi.py, auth.py, guardrail.py
│   │               │   ├── exceptions/ # base.py, auth.py, upstream.py, tool.py, guardrail.py
│   │               │   └── interfaces/ # upstream.py, auth.py
│   │               ├── application/    # MCPGatewayService, GuardrailEngine
│   │               ├── infrastructure/ # FastMCP, upstream clients, Google Auth
│   │               ├── config.py
│   │               └── server.py       # Composition root
│   │
│   └── agents/                 # Autonomous Agent packages (Cognitive Loops)
│       └── lyoko/              # LangGraph Auto-Remediation Agent
│           ├── pyproject.toml
│           ├── Dockerfile
│           └── src/
│               └── lyoko/
│                   ├── domain/
│                   │   ├── models/     # incident.py
│                   │   ├── exceptions/ # base.py, incident.py
│                   │   └── interfaces/ # mcp.py, llm.py
│                   ├── application/    # StateGraph workflow
│                   ├── infrastructure/ # FastAPI webhook controller & MCP client
│                   ├── config.py
│                   └── main.py         # Composition root
│
└── tests/                      # Automated test suite
    ├── agents/lyoko/           # Tests for LYOKO agent (LangGraph, webhooks, models)
    └── mcps/homelab_mcp/       # Tests for MCP gateway (routing, auth, guardrails)
```

---

## 3. Tooling & Quality Standards

- **Python Version**: Python 3.13+
- **Package Manager**: `uv` (`uv sync`, `uv run`, `uv add`)
- **Linter & Formatter**: `ruff` (`ruff check .`, `ruff format .`)
- **Testing**: `pytest` with `pytest-asyncio` for asynchronous tool and graph execution
- **Type Checking**: Full type annotations required on all public interfaces and Pydantic schemas.

---

## 4. GitOps Compatibility Notice

When `LYOKO` operates against Kubernetes clusters managed by GitOps controllers (such as Argo CD or Flux):
- Live `kubectl patch` modifications to Deployment specs can cause GitOps drift.
- Prefer non-conflicting mutation techniques (e.g., mutating annotations or scaling) or generating Git PRs against the source charts repository for permanent config changes.
