# homelab-mcp

[![FastMCP](https://img.shields.io/badge/FastMCP-Gateway-009688.svg?style=flat)](https://github.com/jlowin/fastmcp)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**`homelab-mcp`** is a unified **Model Context Protocol (MCP)** tool gateway and security harness. It aggregates upstream MCP servers for Kubernetes, Home Assistant, UniFi Network, Grafana, and GitHub into a single, authenticated, guardrail-protected endpoint accessible over **Streamable HTTP** (`/mcp`) and **stdio**.

## Architecture

```mermaid
flowchart LR
    subgraph IN["Clients"]
        direction TB
        C1[LYOKO agent]
        C2[IDEs and MCP clients]
    end

    subgraph GW["homelab-mcp"]
        direction LR
        T[Streamable HTTP /mcp and stdio] --> AUTH[Auth verifier]
        AUTH --> CACHE[Response cache]
        CACHE --> SVC[MCPGatewayService]
        SVC --> GUARD[GuardrailEngine]
    end

    subgraph UP["Upstream MCP servers (subprocesses)"]
        direction TB
        K8S[kubernetes-mcp-server]
        HA[ha-mcp]
        UNIFI[unifi-mcp]
        GRAF[Grafana]
        GH[GitHub]
    end

    C1 --> T
    C2 --> T
    GUARD -->|allowed calls| K8S & HA & UNIFI & GRAF & GH

    classDef client fill:#64748b,stroke:#334155,color:#fff;
    classDef gateway fill:#0f766e,stroke:#134e4a,color:#fff;
    classDef upstream fill:#b45309,stroke:#78350f,color:#fff;

    class C1,C2 client;
    class T,AUTH,CACHE,SVC,GUARD gateway;
    class K8S,HA,UNIFI,GRAF,GH upstream;
```

The response cache applies to `list_tools` (300s TTL). Each upstream can be switched off with its `*_ENABLED` variable.

## Guardrails

Every tool call is evaluated by the `GuardrailEngine` before it is dispatched upstream. The first failing check rejects the call.

```mermaid
flowchart LR
    REQ([Tool call]) --> C1[Tool allowlist]
    subgraph GE["GuardrailEngine, checked in order"]
        direction LR
        C1 --> C2[Protected namespaces] --> C3[GitHub repos] --> C4[Exec commands]
    end
    C4 --> OK([Dispatch upstream])
    GE -.->|first failing check| X([Rejected])

    classDef check fill:#0f766e,stroke:#134e4a,color:#fff;
    classDef reject fill:#b91c1c,stroke:#7f1d1d,color:#fff;
    classDef pass fill:#15803d,stroke:#14532d,color:#fff;
    classDef entry fill:#64748b,stroke:#334155,color:#fff;

    class C1,C2,C3,C4 check;
    class X reject;
    class OK pass;
    class REQ entry;
```

### Security capabilities
1. **Namespace Isolation**: Protected namespaces like `kube-system` are read-only. Only Kubernetes tools that match a read-only pattern (`*_get`, `*_list`, `*_log`, `*_top`, and similar) may target them, so every other tool, including new or unknown ones, is rejected. The target namespace is read from the `namespace` argument, from the `metadata.namespace` of a `resource` manifest, and from the name of a `Namespace` object. A manifest that cannot be parsed is rejected. Calls that name no namespace use the namespace from your kubeconfig.
2. **Command Exec Filtering**: Commands executed in containers or hosts are parsed via `shlex` and evaluated against regex signatures for destructive operations (`rm -rf /`, `dd if=...`, `mkfs`, fork bombs).
3. **Multi-Tenant Google OIDC Authentication**: Support for Google OAuth / OIDC with email allowlisting to restrict gateway tool execution to verified identities.

## Tool domains

Tool names come straight from each upstream server. Run `gateway_list_tools` (optionally with `upstream="grafana"`, `query="pod"`, and so on) to see what is available in your deployment.

| Domain | Upstream MCP provider | Capabilities | Example tools |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | [`kubernetes-mcp-server`](https://github.com/containers/kubernetes-mcp-server) | Pod and resource inspection, logs, events, node and pod metrics, scaling, applying manifests, exec. | `pods_get`<br/>`pods_log`<br/>`resources_scale`<br/>`resources_create_or_update` |
| **Home Assistant** | [`homeassistant-ai/ha-mcp`](https://github.com/homeassistant-ai/ha-mcp) | Entity state inspection, service calls, automations, areas, helpers, add-ons, configuration. | `ha_get_state`<br/>`ha_call_service`<br/>`ha_set_entity` |
| **UniFi Network** | [`sirkirby/unifi-mcp`](https://github.com/sirkirby/unifi-mcp) | Network topology, clients, devices, switches, APs, firewall, VPN, routing, statistics, support bundles. | `unifi_tool_index`<br/>`unifi_execute`<br/>`unifi_get_support_bundle` |
| **Grafana** | [`grafana/mcp-grafana`](https://github.com/grafana/mcp-grafana) | Dashboards, datasources, and queries against your Grafana instance. | Discover with `gateway_list_tools` |
| **GitHub** | [`github/github-mcp-server`](https://github.com/github/github-mcp-server) | Repository inspection and GitOps pull requests, restricted by an allowlist and denylist of repositories. | Discover with `gateway_list_tools` |
| **Telegram** | Built into the gateway | Send messages and alerts, and set message reactions. | `telegram_send_message`<br/>`telegram_send_alert`<br/>`telegram_set_reaction` |

## Configuration

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
| `GRAFANA_ENABLED` | `true` | Enable Grafana upstream MCP. |
| `GRAFANA_URL` | `http://grafana.monitoring.svc.cluster.local:3000` | Grafana base URL. |
| `GRAFANA_TOKEN` | `""` | Grafana service account or API token. |
| `GRAFANA_COMMAND` | `npx -y @grafana/mcp-server@latest` | Command used to launch the Grafana MCP server. |
| `GITHUB_ENABLED` | `true` | Enable GitHub upstream MCP. |
| `GITHUB_COMMAND` | `github-mcp-server` | Command used to launch the GitHub MCP server. |
| `GITHUB_TOKEN` | `""` | GitHub personal access token. |
| `GITHUB_OWNER` | `""` | Default GitHub owner or organization. |
| `GITHUB_ALLOWED_REPOS` | `["*"]` | Glob patterns of repositories tools may target. |
| `GITHUB_BLOCKED_REPOS` | `[]` | Glob patterns of repositories that are always blocked. |
| `TELEGRAM_ENABLED` | `false` | Enable the built-in Telegram tools. |
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram bot token from `@BotFather`. |
| `TELEGRAM_DEFAULT_CHAT_ID` | `""` | Default chat for alerts and messages. |

## Usage

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

## Testing

```bash
# Run unit and integration tests for homelab-mcp
uv run pytest tests/mcps/homelab_mcp/
```
