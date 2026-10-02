# LYOKO

[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/FastAPI-Webhook-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**LYOKO** (**L**ive **Y**aml **O**ptimization & **K**8s **O**rchestration) is an event-driven autonomous incident remediation agent built with **LangGraph** and **FastAPI**. It intercepts Kubernetes failure alerts from Prometheus Alertmanager, performs root-cause analysis via the `homelab-mcp` tool gateway, applies safe live adjustments, and verifies service recovery.

---

## 🤖 Remediation State Machine

LYOKO's cognitive loop is implemented as a deterministic **LangGraph StateGraph** finite state machine:

```mermaid
stateDiagram-v2
    direction TB
    [*] --> START
    START --> Diagnose : Prometheus Alert Ingested
    
    state Diagnose {
        [*] --> FetchDiagnostics : call_tool(k8s_get_pod_diagnostics)
        FetchDiagnostics --> LLMAnalysis : Inspect Logs & Exit Codes (OOM 137)
        LLMAnalysis --> [*] : Identify Root Cause
    }

    Diagnose --> Remediate : Root Cause Determined

    state Remediate {
        [*] --> CheckPolicy
        CheckPolicy --> AutoBump : Root Cause = OOMKilled
        CheckPolicy --> Escalate : Other Cause / Unknown
        AutoBump --> PatchDeployment : call_tool(k8s_bump_deployment_resources)
        Escalate --> [*] : Mark Requires Escalation
        PatchDeployment --> [*] : Apply Resource Increase
    }

    Remediate --> Verify : Action Executed

    state Verify {
        [*] --> StabilizationWait : Sleep (Verification Delay)
        StabilizationWait --> ProbePod : Query Current Pod Phase
        ProbePod --> [*] : Confirm Running / Healthy
    }

    Verify --> Notify : Verification Complete

    state Notify {
        [*] --> FormatReport
        FormatReport --> TelegramAlert : Structured Incident Markdown
        TelegramAlert --> [*] : Completed
    }

    Notify --> END
    END --> [*]
```

---

## ⚡ Incident Remediation Workflow

```mermaid
flowchart TD
    subgraph Trigger ["1. Monitoring Alert Trigger"]
        PROM["🔥 Prometheus Engine"] -->|Alert: PodOOMKilled| AM["🔔 Alertmanager"]
        AM -->|POST /webhook/alertmanager| EP["⚡ FastAPI Controller"]
    end

    subgraph LangGraph_Agent ["2. LYOKO State Machine (Async Background Task)"]
        direction TB
        N1["🔍 Node: diagnose<br/>• Query homelab-mcp for pod diagnostics & logs<br/>• LLM determines failure pattern"]
        N2["🔧 Node: remediate<br/>• Evaluate OOM condition<br/>• Bump memory limit/request via homelab-mcp"]
        N3["⏱️ Node: verify<br/>• Wait stabilization window (e.g. 5s)<br/>• Probe pod status & restart counter"]
        N4["📢 Node: notify<br/>• Emit structured incident audit summary<br/>• Post notification to Telegram"]

        N1 --> N2 --> N3 --> N4
    end

    subgraph Tool_Gateway ["3. Tool Execution Layer"]
        MCP["🛡️ homelab-mcp Gateway<br/>(k8s_get_pod_diagnostics, k8s_bump_deployment_resources)"]
    end

    subgraph Cluster ["4. Cluster & Operators"]
        K8S[("☸️ Kubernetes Cluster")]
        TG["📱 Telegram Chat"]
    end

    EP -->|Enqueue State| N1
    N1 & N2 & N3 <-->|Tool Protocol| MCP
    MCP <-->|Cluster API| K8S
    N4 -.->|Publish Report| TG

    classDef trigger fill:#fff3e0,stroke:#ff9800,stroke-width:1px,color:#e65100;
    classDef agent fill:#ede7f6,stroke:#7e57c2,stroke-width:1px,color:#311b92;
    classDef gateway fill:#e0f2f1,stroke:#26a69a,stroke-width:1px,color:#004d40;
    classDef target fill:#eceff1,stroke:#607d8b,stroke-width:1px,color:#263238;

    class PROM,AM,EP trigger;
    class N1,N2,N3,N4 agent;
    class MCP gateway;
    class K8S,TG target;
```

---

## ⚙️ Configuration Reference

Configure LYOKO using environment variables (in `.env` or Kubernetes ConfigMap/Secret):

| Variable | Default | Description |
| :--- | :--- | :--- |
| `LYOKO_HOST` | `0.0.0.0` | Webhook receiver interface. |
| `LYOKO_PORT` | `9000` | Webhook receiver port. |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | URL of the `homelab-mcp` gateway endpoint. |
| `OPENAI_API_KEY` | `""` | OpenAI API key for LLM diagnosis. |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model used for root-cause inference. |
| `VERIFICATION_DELAY_SECONDS` | `5` | Stabilization wait time (in seconds) before post-remediation verification. |
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram bot token for alerting. |
| `TELEGRAM_CHAT_ID` | `""` | Telegram chat ID for incident reports. |

---

## 🔔 Prometheus Alertmanager Integration

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

---

## 🚀 Running LYOKO Locally

```bash
# Start LYOKO agent (FastAPI server on port 9000)
uv run --package lyoko python -m lyoko.main
```

### Triggering a Test Webhook

Simulate a firing Alertmanager event:

```bash
curl -X POST http://localhost:9000/webhook/alertmanager \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "KubePodOOMKilled",
          "namespace": "default",
          "pod": "web-service-6789abcd-ef123",
          "deployment": "web-service"
        },
        "annotations": {
          "summary": "Pod terminated with OOMKilled exit code 137"
        }
      }
    ]
  }'
```

---

## 🧪 Testing

```bash
# Run LYOKO workflow and webhook test suites
uv run pytest tests/agents/lyoko/
```
