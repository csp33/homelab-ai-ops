# LYOKO

[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/FastAPI-Webhook-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Langfuse](https://img.shields.io/badge/Langfuse-Observability-black.svg?style=flat)](https://langfuse.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**LYOKO** (**L**ive **Y**aml **O**ptimization & **K**8s **O**rchestration) is an event-driven autonomous incident remediation and operations agent built with **LangGraph**, **FastAPI**, and **python-telegram-bot**.

It serves two primary roles:
1. **Autonomous Incident Remediation**: Intercepts Kubernetes failure alerts from Prometheus Alertmanager, diagnoses root causes via `homelab-mcp`, pauses for Human-in-the-Loop (HITL) approval via Telegram inline buttons, applies safe live adjustments, and verifies recovery.
2. **Interactive Homelab Chat Assistant**: Provides a conversational Telegram interface powered by FastMCP tools to answer infrastructure queries, manage smart home entities (Home Assistant), inspect network topology (UniFi), and execute administrative operations.

## Remediation workflow

The remediation loop is a **LangGraph StateGraph** with PostgreSQL checkpoint persistence. The graph is linear. Instead of branching, each node inspects the shared state and short-circuits when the incident must be escalated.

```mermaid
flowchart LR
    AM([Alertmanager]) -->|POST /webhook/alertmanager| D

    subgraph WF["LYOKO workflow"]
        direction LR
        D[diagnose] --> A[request_approval] --> R[remediate] --> V[verify] --> N[notify]
    end

    D <-->|pod diagnostics| MCP[homelab-mcp]
    R -->|bump resources| MCP
    V <-->|pod status| MCP
    A <-->|approve or deny| TG([Telegram])
    N -->|incident report| TG

    A -.->|rejected, timed out, or not OOM| N

    classDef external fill:#64748b,stroke:#334155,color:#fff;
    classDef step fill:#7c3aed,stroke:#4c1d95,color:#fff;
    classDef gateway fill:#0f766e,stroke:#134e4a,color:#fff;

    class AM,TG external;
    class D,A,R,V,N step;
    class MCP gateway;
```

| Node | What it does | Gateway tool |
| :--- | :--- | :--- |
| `diagnose` | Fetches pod status and logs, then asks the LLM for a root cause. Falls back to log inspection if the LLM fails. | `k8s_get_pod_diagnostics` |
| `request_approval` | For OOMKilled pods, sends Approve / Deny buttons to Telegram and waits for the operator. Without an approval manager, it auto-approves. | - |
| `remediate` | Bumps the deployment to 1Gi limit and 512Mi request. Becomes a no-op when approval was denied or the cause is not OOM. | `k8s_bump_deployment_resources` |
| `verify` | Waits for the stabilization delay, then checks that the pod is running. Skipped when escalated. | `k8s_get_pod_diagnostics` |
| `notify` | Posts a structured incident report. The status is `RESOLVED`, or `ESCALATED` when a human must act. | - |

## Telegram chat assistant

LYOKO connects directly to Telegram as a bidirectional operations assistant:
- **RBAC Authorization**: Restricts access via `TELEGRAM_ALLOWED_USER_IDS` and `TELEGRAM_ALLOWED_CHAT_IDS`.
- **Targeted Tool Discovery**: Queries tools on demand using `gateway_list_tools(query="...")` and `gateway_get_tool_schema` to maintain lean context windows (<2,000 tokens per turn).
- **Clean HTML Formatting**: Automatically converts LLM Markdown into Telegram-compliant HTML tags without mangling underscore identifiers (`MOVISTAR_25EO_IOT`).

## Observability

All LLM runs, ReAct agent turns, and StateGraph checkpoints are natively traced in **Langfuse**:
- **Sessions**: Threaded per Telegram chat (`telegram-{chat_id}`) and incident ID (`inc-{id}`).
- **Environments**: Explicitly segregated (`ENVIRONMENT=local` vs `ENVIRONMENT=homelab`).
- **Cost & Token Tracking**: Real-time token usage and cost accounting across all generations.

## Configuration

Configure LYOKO using environment variables (in `.env` or Kubernetes ConfigMap/Secret):

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ENVIRONMENT` | `local` | Operational environment tag (`local`, `homelab`, `production`). |
| `LYOKO_HOST` | `0.0.0.0` | Webhook receiver bind host. |
| `LYOKO_PORT` | `9000` | Webhook receiver bind port. |
| `OPENAI_API_KEY` | `""` | OpenAI API key for LLM diagnosis and chat. |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model used for chat and remediation reasoning. |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | URL of the `homelab-mcp` gateway endpoint. |
| `SERVICE_TOKEN` | `""` | Bearer token for authenticating against `homelab-mcp`. Required when the gateway runs with `AUTH_ENABLED=true`. |
| `MCP_FAIL_FAST` | `true` | Abort startup if the gateway rejects the credentials (401/403) or the URL is not an MCP endpoint (404). An unreachable gateway only logs an error. |
| `TELEGRAM_ENABLED` | `false` | Enable Telegram assistant, channel posting, and HITL approvals. |
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram Bot Token from `@BotFather`. |
| `TELEGRAM_ALLOWED_USER_IDS` | `[]` | List of authorized Telegram user IDs. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | `[]` | List of authorized Telegram channel/group IDs. |
| `TELEGRAM_DEFAULT_CHAT_ID` | `""` | Default chat ID for broadcast notifications and alerts. |
| `LANGFUSE_ENABLED` | `false` | Enable Langfuse tracing and observability. |
| `LANGFUSE_PUBLIC_KEY` | `""` | Langfuse Project Public API Key. |
| `LANGFUSE_SECRET_KEY` | `""` | Langfuse Project Secret API Key. |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse instance host URL. |
| `POSTGRES_CHECKPOINTER_URL` | `""` | PostgreSQL connection string for LangGraph persistent state checkpointing. |

## Alertmanager integration

Configure your Prometheus Alertmanager `config.yml` to route firing pod alerts directly to LYOKO:

```yaml
receivers:
  - name: "lyoko-remediation"
    webhook_configs:
      - url: "http://lyoko.aiops.svc.cluster.local:9000/webhook/alertmanager"
        send_resolved: false

route:
  group_by: ["alertname", "namespace", "pod"]
  group_wait: 10s
  group_interval: 30s
  repeat_interval: 1h
  routes:
    - match:
        alertname: KubePodCrashLooping
      receiver: "lyoko-remediation"
    - match:
        alertname: KubePodOOMKilled
      receiver: "lyoko-remediation"
```

## Running locally

```bash
# Start LYOKO agent (FastAPI server on port 9000)
uv run --package lyoko python -m lyoko.main
```

## Testing

```bash
# Run LYOKO workflow, webhook, and connector test suites
uv run pytest tests/agents/lyoko/
```
