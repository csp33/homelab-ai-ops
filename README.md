# homelab-aiops

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![FastMCP](https://img.shields.io/badge/FastMCP-gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![LangGraph](https://img.shields.io/badge/LangGraph-workflow-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An AI operator for the whole homelab: Kubernetes, the network, the smart home, and observability. It receives incidents, works out the cause, and fixes them through a single authenticated, guardrail-protected tool gateway, with a human approving anything that is not explicitly trusted. It continuously learns from operator feedback via persistent vector episodic memory (**PostgreSQL** + **pgvector**). Powered by **FastMCP** and **LangGraph**.

[Architecture](#architecture) · [Packages](#packages) · [Features](#features) · [Quick Start](#quick-start) · [Security](#security)

## Architecture

Two packages, one unified homelab operations platform. Every tool call, whether from an external IDE (Claude Desktop, Cursor) or from LYOKO's multi-agent supervisor, goes through the `homelab-mcp` gateway with relevance-scored scoped tool search, authentication, and safety guardrails.

```mermaid
flowchart TD
    %% External clients
    subgraph Ingress ["Ingress & Triggers"]
        direction LR
        AM([Alertmanager])
        TG([Telegram Operator])
        IDE([Claude Desktop / IDEs])
    end

    %% LYOKO Multi-Agent Engine
    subgraph LYOKO ["LYOKO (Multi-Agent LangGraph Engine)"]
        direction TB
        WH[Webhook Controller]
        CH[Chat Handler]
        SUP["Supervisor & Planner"]
        MEM_ENG["Semantic Memory & Feedback Engine"]
        
        subgraph Specialists ["Domain Specialists"]
            direction LR
            K8S_S["☸️ K8s SRE"]
            NET_S["🌐 Network Spec"]
            HA_S["🏠 SmartHome Spec"]
            OBS_S["📊 Metrics Spec"]
        end

        WH --> SUP
        CH --> SUP
        SUP --> K8S_S
        SUP --> NET_S
        SUP --> HA_S
        SUP --> OBS_S
        SUP <--> MEM_ENG
    end

    %% Persistent Storage
    subgraph DB ["Persistent Storage"]
        direction TB
        PG[(PostgreSQL + pgvector<br/>HNSW Cosine Index)]
    end

    %% homelab-mcp Tool Hub
    subgraph GW ["homelab-mcp (Tool Hub & Safety Harness)"]
        direction TB
        AUTH[Auth Verifier]
        SEARCH["Scoped Tool Search Engine<br/>(Relevance Scoring & Token Matching)"]
        GUARD[Guardrail Engine]
        AUTH --> SEARCH --> GUARD
    end

    %% Upstreams
    subgraph UP ["Upstream Infrastructure"]
        direction LR
        U_K8S[(Kubernetes)]
        U_HA[(Home Assistant)]
        U_NET[(UniFi Network)]
        U_GRAF[(Grafana / Prometheus)]
        U_GH[(GitHub)]
    end

    %% Ingress Connections
    AM -->|"webhooks"| WH
    TG <-->|"chat, feedback & approvals"| CH
    IDE -->|"HTTP / stdio (Direct MCP)"| AUTH

    %% Memory Connection
    MEM_ENG <-->|"dense embeddings & past lessons"| PG

    %% LYOKO & MCP Connections
    K8S_S -->|"scoped tools"| AUTH
    NET_S -->|"scoped tools"| AUTH
    HA_S -->|"scoped tools"| AUTH
    OBS_S -->|"scoped tools"| AUTH
    GUARD --> U_K8S
    GUARD --> U_HA
    GUARD --> U_NET
    GUARD --> U_GRAF
    GUARD --> U_GH

    %% Styling
    classDef ingress fill:#475569,stroke:#334155,color:#fff;
    classDef agent fill:#7c3aed,stroke:#5b21b6,color:#fff;
    classDef spec fill:#9333ea,stroke:#6b21a8,color:#fff;
    classDef gateway fill:#0f766e,stroke:#115e59,color:#fff;
    classDef upstream fill:#b45309,stroke:#92400e,color:#fff;
    classDef storage fill:#1e3a8a,stroke:#172554,color:#fff;

    class AM,TG,IDE ingress;
    class WH,CH,SUP,MEM_ENG agent;
    class K8S_S,NET_S,HA_S,OBS_S spec;
    class AUTH,SEARCH,GUARD gateway;
    class U_K8S,U_HA,U_NET,U_GRAF,U_GH upstream;
    class PG storage;
```

### Example: an OOMKilled pod with learned memory

Every incident follows the same loop: investigate with read-only tools, retrieve prior operator lessons, decide on a fix, get approval for each change, apply it, verify, and report. If the operator previously taught the agent a specific rule for that service (e.g. *"compact WAL logs before restarting"*), the agent incorporates it into its diagnosis and remediation plan.

```mermaid
sequenceDiagram
    autonumber
    participant AM as Alertmanager
    participant L as LYOKO
    participant DB as PostgreSQL (pgvector)
    participant G as homelab-mcp
    participant O as Operator (Telegram)
    participant K as Kubernetes

    AM->>L: POST /webhook/alertmanager (KubePodOOMKilled)

    par Semantic memory lookup
        L->>DB: Search past feedback & incident rules (cosine distance)
        DB-->>L: Prior lessons & operator guidelines
    and Read-only investigation
        loop Tool investigation
            L->>G: pods_get, pods_log, events_list
            G->>K: Read pod, logs, events
            K-->>G: Exit code 137
            G-->>L: Evidence
        end
    end

    L->>L: Root cause and plan (incorporating memory rules)

    L->>G: resources_create_or_update (raise memory limit)
    Note over L,G: The tool gate holds the call
    L->>O: Approval request with tool, arguments & [💡 Teach Rule]

    alt Approved
        O-->>L: Approve
        G->>G: Guardrail check
        G->>K: Apply change
        L->>L: Wait for stabilization
        L->>G: pods_get (read-only)
        G-->>L: Pod running
    else Teach Rule / Redirect
        O-->>L: Teach Rule (e.g. "/feedback Do not increase RAM, compact WAL")
        L->>DB: Store vector embedding & rule in agent_memory
        Note over L: Memory updated for next incidents
    else Denied or timed out
        O-->>L: Deny
        Note over L: Nothing changed, incident escalated
    end

    L->>O: Incident report (including applied memories)
```

Tool names come from the upstream servers, so they depend on your deployment. The agent finds them with `gateway_list_tools`.

## Packages

| Package | Role | Description |
| :--- | :--- | :--- |
| [`homelab-mcp`](packages/mcps/homelab-mcp) | Tool gateway | FastMCP gateway that aggregates upstream MCP servers behind authentication and safety guardrails. |
| [`lyoko`](packages/agents/lyoko) | Autonomous agent | Event-driven remediation agent built with LangGraph, FastAPI, persistent semantic memory, and a Telegram chat assistant. |

## Features

- **Semantic Memory & Operator Feedback**: Learns continuously from operator interactions. Past incident resolutions and operator rules are stored in PostgreSQL with 1536-dimensional vector embeddings and HNSW indexes (`pgvector`). During diagnosis, LYOKO retrieves relevant past lessons to prevent repeating mistakes. Operators can teach rules via interactive Telegram buttons (`[💡 Teach Rule / Redirect]`), commands (`/feedback`, `/teach`), or REST API (`POST /api/v1/feedback`).
- **Guardrails**: block destructive commands (`rm -rf`, `mkfs`, fork bombs), mutations in protected namespaces (`kube-system`), and tools outside the allowlist.
- **Autonomous remediation**: for any alert, an agent investigates with read-only tools, proposes a fix, and applies it. Every state-changing tool call needs human approval unless you put it on the auto-approve list, and the agent cannot change anything while diagnosing or verifying.
- **Whole-homelab assistant**: a Telegram assistant that can inspect and operate Kubernetes, Home Assistant, UniFi, and Grafana through the same gateway. It follows the same approval policy as alerts: reads run, trusted changes run, and any other change asks you first. A message that reports a broken service is handled like an alert, with investigation, fix, verification and report.
- **One gateway**: Kubernetes, Home Assistant, UniFi, Grafana, and GitHub tools behind a single endpoint over Streamable HTTP (`/mcp`) and stdio.
- **Authentication**: Google OIDC and bearer-token verification for users and agents.
- **Reproducible toolchain**: Python 3.13+, `uv` workspace, `ruff`, Alembic migrations.

## Quick Start

### 1. Prerequisites

- [Python 3.13+](https://www.python.org/downloads/)
- [`uv`](https://docs.astral.sh/uv/) (Ultra-fast Python package installer and resolver)
- `kubectl` configured with cluster context (or in-cluster ServiceAccount)

### 2. Installation & Setup

```bash
# Clone repository
git clone https://github.com/csp33/homelab-aiops.git
cd homelab-aiops

# Install workspace dependencies deterministically
uv sync

# Configure your environment variables
cp .env.example .env
```

### 3. Configure `.env`

Edit `.env` with your homelab details:

```ini
# LLM Provider
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini

# homelab-mcp Gateway Settings
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_TRANSPORT=http

# Home Assistant (Optional)
HASS_URL=http://homeassistant.default.svc.cluster.local:8123
HASS_TOKEN=your-long-lived-access-token

# UniFi Network Controller (Optional)
UNIFI_HOST=https://192.168.1.1
UNIFI_USER=admin
UNIFI_PASSWORD=your-unifi-password

# LYOKO Agent Settings
LYOKO_HOST=0.0.0.0
LYOKO_PORT=9000
MCP_SERVER_URL=http://localhost:8000/mcp

# Persistent Storage & Vector Memory (PostgreSQL + pgvector)
POSTGRES_HOST=postgresql-rw.postgresql-cnpg.svc.cluster.local
POSTGRES_PORT=5432
POSTGRES_DB=lyoko
POSTGRES_USER=lyoko
POSTGRES_PASSWORD=your-postgres-password

# Telegram Bot (Optional for interactive HITL and /feedback)
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_DEFAULT_CHAT_ID=123456789
```

### 4. Running the Services

```bash
# 1. Start homelab-mcp Tool Gateway (port 8000)
uv run --package homelab-mcp python -m homelab_mcp.server

# 2. Start LYOKO Remediation Agent (port 9000)
uv run --package lyoko python -m lyoko.main
```

### 5. Running Tests & Quality Checks

```bash
# Run pytest test suite
uv run pytest

# Check formatting and lint rules
uv run ruff check .
```

## Security

> [!IMPORTANT]
> This platform executes real operations on physical infrastructure and Kubernetes clusters. Safety guardrails are enforced at the gateway application layer before any upstream tool execution.

- **Protected Namespaces**: Critical system namespaces (e.g. `kube-system`) are strictly read-only by default. Destructive or mutating operations are blocked.
- **Dangerous Command Interception**: Execution payloads are parsed and matched against dangerous pattern signatures (e.g., recursive deletion, partition formatting).
- **Zero-Leak Policy**: All sensitive tokens and credentials must be injected through environment variables.

> [!NOTE]
> When operating against clusters managed by GitOps controllers (such as Argo CD or Flux), live mutations to Deployment specs can cause sync drift. For permanent configuration changes, configure your agent to generate Git pull requests.