# homelab-aiops

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![FastMCP](https://img.shields.io/badge/FastMCP-gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![LangGraph](https://img.shields.io/badge/LangGraph-workflow-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Autonomous **Homelab AIOps & Operations Platform** designed for Kubernetes homelabs and smart infrastructure, powered by **FastMCP** and **LangGraph**.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Trigger_Layer ["1. Trigger & Client Layer"]
        AM["🔔 Prometheus Alertmanager<br/>(Firing Alerts / OOMKilled)"]
        IDE["💻 Developer IDEs / Agents<br/>(Antigravity, Cursor, Claude)"]
    end

    subgraph Autonomous_Agent ["2. Cognitive Loop — LYOKO"]
        direction TB
        WH["⚡ FastAPI Webhook Controller<br/><code>/webhook/alertmanager</code>"]
        LG{"🤖 LangGraph StateGraph<br/>(Diagnose ➔ Request Approval ➔ Remediate ➔ Verify ➔ Notify)"}
        WH --> LG
    end

    subgraph Gateway_Layer ["3. Tool Gateway & Safety Harness — homelab-mcp"]
        direction TB
        SEC["🔐 Auth & OIDC Verifier<br/>(Google JWT / Bearer Token)"]
        GR["🛡️ Guardrail Engine<br/>(Namespace Protection, Command Regex, Tool Allowlist)"]
        MUX["🔀 Upstream Process Multiplexer<br/>(Parallel Tool Discovery & Routing)"]
        SEC --> GR --> MUX
    end

    subgraph Upstream_Servers ["4. Upstream MCP Adapters"]
        K8S_MCP["☸️ kubernetes-mcp-server"]
        HA_MCP["🏠 homeassistant-ai/ha-mcp"]
        UNIFI_MCP["🌐 sirkirby/unifi-mcp"]
    end

    subgraph Homelab_Infra ["5. Physical & Virtual Homelab Infrastructure"]
        K8S[("☸️ Kubernetes Cluster<br/>(Pods, Deployments, RBAC)")]
        HASS[("🏠 Home Assistant<br/>(Sensors, Lights, Automations)")]
        UDM[("🌐 UniFi Network / UDM<br/>(Gateways, APs, Switches)")]
        TG["📱 Telegram Messenger<br/>(Incident Reports, Assistant & HITL)"]
    end

    AM -->|POST JSON Webhook| WH
    IDE -->|Streamable HTTP / stdio| SEC
    LG -->|FastMCP Client Calls| SEC

    MUX -->|Process Stdio Proxy| K8S_MCP --> K8S
    MUX -->|Process Stdio Proxy| HA_MCP --> HASS
    MUX -->|Process Stdio Proxy| UNIFI_MCP --> UDM
    LG <-->|HITL Approvals & Chat| TG

    classDef client fill:#e1f5fe,stroke:#0288d1,stroke-width:1px,color:#01579b;
    classDef agent fill:#ede7f6,stroke:#7e57c2,stroke-width:1px,color:#311b92;
    classDef gateway fill:#e0f2f1,stroke:#26a69a,stroke-width:1px,color:#004d40;
    classDef upstream fill:#fff3e0,stroke:#ff9800,stroke-width:1px,color:#e65100;
    classDef infra fill:#eceff1,stroke:#607d8b,stroke-width:1px,color:#263238;

    class AM,IDE client;
    class WH,LG agent;
    class SEC,GR,MUX gateway;
    class K8S_MCP,HA_MCP,UNIFI_MCP upstream;
    class K8S,HASS,UDM,TG infra;
```

---

## ⚡ Incident Remediation Lifecycle (with HITL Approval)

```mermaid
sequenceDiagram
    autonumber
    actor Alertmanager as 🔔 Alertmanager
    participant LYOKO as 🤖 LYOKO Agent
    participant Gateway as 🛡️ homelab-mcp Gateway
    actor Operator as 👤 Homelab Operator (Telegram)
    participant K8s as ☸️ Kubernetes Cluster

    Alertmanager->>LYOKO: Webhook: Pod OOMKilled / CrashLoop (Target: memory-hungry-app)
    activate LYOKO
    LYOKO->>Gateway: call_tool("k8s_get_pod_diagnostics", {namespace, pod})
    Gateway->>Gateway: Validate Guardrail Policy (Allowed Tool & Namespace)
    Gateway->>K8s: Fetch Pod Logs & Exit Codes (137 OOM)
    K8s-->>Gateway: Return Pod Diagnostics & Logs
    Gateway-->>LYOKO: Return Diagnostic Payload
    
    LYOKO->>LYOKO: LLM Analysis: Diagnose root cause as OOMKilled
    LYOKO->>Operator: Telegram HITL Prompt: [✅ Approve (1Gi Bump)] [❌ Deny]
    Operator-->>LYOKO: Inline Button Click: Approved
    LYOKO->>Gateway: call_tool("k8s_bump_deployment_resources", {memory_limit: "1Gi"})
    Gateway->>Gateway: Guardrail Check: Namespace != kube-system & Resource within limits
    Gateway->>K8s: Apply Live Patch (Limits: 1Gi, Requests: 512Mi)
    K8s-->>Gateway: Patch Acknowledged
    Gateway-->>LYOKO: Deployment Updated

    LYOKO->>LYOKO: Sleep verification interval (e.g. 5s)
    LYOKO->>Gateway: call_tool("k8s_get_pod_diagnostics", {namespace, pod})
    Gateway->>K8s: Probe Pod Status
    K8s-->>Gateway: Status: Running (0 Restarts)
    Gateway-->>LYOKO: Healthy

    LYOKO->>Operator: Telegram Incident Report: Incident Resolved (1Gi BUMP)
    deactivate LYOKO

```

---

## 📦 Packages in this Monorepo

| Package | Path | Type | Description |
| :--- | :--- | :--- | :--- |
| **`homelab-mcp`** | [`packages/mcps/homelab-mcp`](packages/mcps/homelab-mcp) | **Gateway & Safety Harness** | Aggregated **FastMCP Gateway** proxying upstream tools (`ha-mcp`, `unifi-mcp`, `kubernetes-mcp-server`) with multi-tenant auth and safety guardrails. |
| **`lyoko`** | [`packages/agents/lyoko`](packages/agents/lyoko) | **Autonomous Agent** | Event-driven auto-remediation agent built with **LangGraph** StateGraph state machine and **FastAPI**. |

---

## ✨ Key Features

- **🛡️ Strict Safety Guardrails**: Built-in engine preventing destructive commands (`rm -rf`, `mkfs`, fork bombs), mutation in protected namespaces (`kube-system`), and unapproved tool invocations.
- **🔄 Event-Driven Self-Healing**: Automated diagnosis and remediation loops for common Kubernetes incident classes (`OOMKilled`, `CrashLoopBackOff`).
- **🔀 Unified FastMCP Gateway**: Single endpoint exposing Kubernetes, Home Assistant, and UniFi Network tools over Streamable HTTP (`/mcp`) and stdio.
- **🔐 Enterprise-Grade Authentication**: Google OIDC and token verification ensuring only authorized users and agents can execute infrastructure tools.
- **⚡ Modern Python Toolchain**: Built on Python 3.13+, managed deterministically via `uv` workspaces, and styled with `ruff`.

---

## 🚀 Quick Start

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

---

## 🔒 Security & Safety Harness

> [!IMPORTANT]
> This platform executes real operations on physical infrastructure and Kubernetes clusters. Safety guardrails are enforced at the gateway application layer before any upstream tool execution.

- **Protected Namespaces**: Critical system namespaces (e.g. `kube-system`) are strictly read-only by default. Destructive or mutating operations are blocked.
- **Dangerous Command Interception**: Execution payloads are parsed and matched against dangerous pattern signatures (e.g., recursive deletion, partition formatting).
- **Zero-Leak Policy**: All sensitive tokens and credentials must be injected through environment variables.

> [!NOTE]
> When operating against clusters managed by GitOps controllers (such as Argo CD or Flux), live mutations to Deployment specs can cause sync drift. For permanent configuration changes, configure your agent to generate Git pull requests.