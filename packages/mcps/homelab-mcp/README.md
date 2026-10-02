# homelab-mcp

[![FastMCP](https://img.shields.io/badge/FastMCP-Gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**`homelab-mcp`** is a unified **Model Context Protocol (MCP)** tool gateway and security harness. It aggregates upstream MCP servers for Kubernetes, Home Assistant, and UniFi Network into a single, authenticated, guardrail-protected endpoint accessible over **Streamable HTTP** (`/mcp`) and **stdio**.

---

## 🏛️ Gateway Architecture

```mermaid
flowchart TD
    subgraph Inbound_Clients ["Inbound AI Clients & Transports"]
        C1["🤖 Autonomous Agents (LYOKO)"]
        C2["💻 Developer IDEs (Antigravity, Cursor, Claude)"]
    end

    subgraph FastMCP_Gateway ["homelab-mcp Gateway Core"]
        direction TB
        
        subgraph Transport_Layer ["Transport & Middleware"]
            T1["🌐 Streamable HTTP (/mcp:8000)"]
            T2["📟 stdio Process Pipe"]
            CACHE["⚡ Response Caching Middleware<br/>(list_tools TTL: 300s)"]
        end

        subgraph Security_Layer ["Security & Guardrail Pipeline"]
            AUTH{"🔐 Auth Verifier<br/>(Google OIDC / JWT Token)"}
            GUARD{"🛡️ GuardrailEngine<br/>(Namespace & Exec Filter)"}
        end

        subgraph Aggregation_Layer ["Service & Router"]
            SVC["🔀 MCPGatewayService<br/>(Parallel Tool Discovery & Dispatch)"]
        end

        T1 & T2 --> CACHE --> AUTH --> GUARD --> SVC
    end

    subgraph Upstream_Processes ["Upstream MCP Server Subprocesses"]
        U_K8S["☸️ ProcessUpstreamClient<br/>(containers/kubernetes-mcp-server)"]
        U_HA["🏠 ProcessUpstreamClient<br/>(homeassistant-ai/ha-mcp)"]
        U_UNIFI["🌐 ProcessUpstreamClient<br/>(sirkirby/unifi-mcp)"]
    end

    subgraph Homelab_Targets ["Homelab Targets"]
        T_K8S[("☸️ Kubernetes Cluster API")]
        T_HA[("🏠 Home Assistant REST / WS")]
        T_UNIFI[("🌐 UniFi Controller API")]
    end

    C1 -->|Streamable HTTP| T1
    C2 -->|Streamable HTTP / stdio| T1 & T2

    SVC -->|Async Stdio Pipe| U_K8S --> T_K8S
    SVC -->|Async Stdio Pipe| U_HA --> T_HA
    SVC -->|Async Stdio Pipe| U_UNIFI --> T_UNIFI

    classDef client fill:#e1f5fe,stroke:#0288d1,stroke-width:1px,color:#01579b;
    classDef gateway fill:#e0f2f1,stroke:#26a69a,stroke-width:1px,color:#004d40;
    classDef upstream fill:#fff3e0,stroke:#ff9800,stroke-width:1px,color:#e65100;
    classDef target fill:#eceff1,stroke:#607d8b,stroke-width:1px,color:#263238;

    class C1,C2 client;
    class T1,T2,CACHE,AUTH,GUARD,SVC gateway;
    class U_K8S,U_HA,U_UNIFI upstream;
    class T_K8S,T_HA,T_UNIFI target;
```

---

## 🛡️ Guardrails & Security Model

`homelab-mcp` implements defense-in-depth safety controls before any tool call reaches an upstream system:

```mermaid
flowchart LR
    REQ["Incoming Tool Request<br/><code>{tool, args}</code>"] --> C1{"1. Tool Allowlist?"}
    C1 -- No --> ERR1["❌ Rejected: Tool Not Permitted"]
    C1 -- Yes --> C2{"2. Protected Namespace?<br/>(e.g. kube-system)"}
    C2 -- Mutating Action --> ERR2["❌ Rejected: Protected Namespace"]
    C2 -- Safe Action --> C3{"3. Dangerous Exec Pattern?<br/>(rm -rf, mkfs, dd, fork bomb)"}
    C3 -- Dangerous --> ERR3["❌ Rejected: Blocked Command"]
    C3 -- Safe --> EXEC["✅ Dispatch to Upstream MCP"]

    classDef reject fill:#ffebee,stroke:#e53935,stroke-width:1px,color:#b71c1c;
    classDef pass fill:#e8f5e9,stroke:#43a047,stroke-width:1px,color:#1b5e20;
    classDef check fill:#e0f2f1,stroke:#00897b,stroke-width:1px,color:#004d40;

    class C1,C2,C3 check;
    class ERR1,ERR2,ERR3 reject;
    class EXEC pass;
```

### Security Capabilities
1. **Namespace Isolation**: Mutating actions (`delete`, `patch`, `update`, `restart`, `bump`, `exec`) targeting protected namespaces like `kube-system` are intercepted and rejected.
2. **Command Exec Filtering**: Commands executed in containers or hosts are parsed via `shlex` and evaluated against regex signatures for destructive operations (`rm -rf /`, `dd if=...`, `mkfs`, fork bombs).
3. **Multi-Tenant Google OIDC Authentication**: Support for Google OAuth / OIDC with email allowlisting to restrict gateway tool execution to verified identities.

---

## 🧰 Integrated Tool Domains

| Domain | Upstream MCP Provider | Capabilities | Example Tools |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | `kubernetes-mcp-server` | Pod diagnostics, logs, deployment resource adjustments, rollout restarts, namespace queries. | `k8s_get_pod_diagnostics`<br/>`k8s_bump_deployment_resources`<br/>`k8s_rollout_restart` |
| **Home Assistant** | `homeassistant-ai/ha-mcp` | IoT entity state inspection, domain service execution, automation trigger, health monitoring. | `ha_get_state`<br/>`ha_call_service`<br/>`ha_get_overview` |
| **UniFi Network** | `sirkirby/unifi-mcp` | Network topology, connected client inspection, port profiles, controller metrics, support bundles. | `unifi_tool_index`<br/>`unifi_execute`<br/>`unifi_get_support_bundle` |

---

## ⚙️ Configuration Reference

Configure `homelab-mcp` via environment variables (in `.env` or container environments):

| Variable | Default | Description |
| :--- | :--- | :--- |
| `MCP_HOST` | `0.0.0.0` | Gateway listening interface. |
| `MCP_PORT` | `8000` | Gateway listening HTTP port. |
| `MCP_TRANSPORT` | `http` | Transport mode: `http` (Streamable HTTP) or `stdio`. |
| `AUTH_ENABLED` | `false` | Enable/disable token and OIDC verification. |
| `GOOGLE_CLIENT_ID` | `""` | Google OAuth client ID for OIDC proxy. |
| `GOOGLE_CLIENT_SECRET`| `""` | Google OAuth client secret for OIDC proxy. |
| `HASS_ENABLED` | `true` | Enable Home Assistant upstream MCP. |
| `HASS_URL` | `http://homeassistant...:8123` | Home Assistant instance URL. |
| `HASS_TOKEN` | `""` | Long-lived access token for Home Assistant. |
| `UNIFI_ENABLED` | `true` | Enable UniFi Network upstream MCP. |
| `UNIFI_URL` | `https://192.168.1.1` | UniFi controller URL / gateway IP. |
| `UNIFI_USER` | `""` | UniFi admin username. |
| `UNIFI_PASSWORD` | `""` | UniFi admin password. |
| `K8S_ENABLED` | `true` | Enable Kubernetes upstream MCP. |
| `KUBECONFIG` | `~/.kube/config` | Path to kubeconfig (or in-cluster SA). |

---

## 🚀 Usage & Integration

### 1. Running as Streamable HTTP Server (Cluster / Monorepo Mode)

```bash
uv run --package homelab-mcp python -m homelab_mcp.server
```

The gateway exposes its endpoints:
- Tool Gateway: `http://localhost:8000/mcp`
- Tool Discovery: Dynamic aggregation with 300s TTL cache.

### 2. Claude Desktop / Cursor IDE Integration (`stdio` Mode)

Add the following to your `claude_desktop_config.json` or Cursor MCP settings:

```json
{
  "mcpServers": {
    "homelab": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/homelab-aiops",
        "run",
        "--package",
        "homelab-mcp",
        "python",
        "-m",
        "homelab_mcp.server"
      ],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "HASS_URL": "http://homeassistant.local:8123",
        "HASS_TOKEN": "your-token-here",
        "UNIFI_HOST": "https://192.168.1.1",
        "UNIFI_USER": "admin",
        "UNIFI_PASSWORD": "your-password"
      }
    }
  }
}
```

---

## 🧪 Testing

```bash
# Run unit and integration tests for homelab-mcp
uv run pytest tests/mcps/homelab_mcp/
```
