# Quick Start Guide

This guide walks you through setting up, configuring, and running `homelab-aiops` in your local environment or cluster.

---

## 1. Prerequisites

Before starting, ensure you have the following tools installed and accessible:

- **[Python 3.13+](https://www.python.org/downloads/)**
- **[`uv`](https://docs.astral.sh/uv/)**: Ultra-fast Python package installer and workspace resolver.
- **[PostgreSQL](https://www.postgresql.org/) with [`pgvector`](https://github.com/pgvector/pgvector)**: Required for LYOKO's episodic memory and vector similarity search.
- **`kubectl`**: Configured with a valid cluster context (or running within an in-cluster `ServiceAccount`).
- **OpenAI API Key**: For LLM reasoning and dense vector embeddings (`text-embedding-3-small`).

---

## 2. Installation & Workspace Setup

Clone the repository and install all workspace package dependencies deterministically using `uv`:

```bash
# 1. Clone the repository
git clone https://github.com/csp33/homelab-aiops.git
cd homelab-aiops

# 2. Synchronize workspace dependencies
uv sync

# 3. Create your environment configuration file
cp .env.example .env
```

---

## 3. Environment Configuration

Edit `.env` to supply credentials and endpoints for your infrastructure. Below is a documented configuration template:

```ini
# ==============================================================================
# Environment & LLM Provider
# ==============================================================================
ENVIRONMENT=local
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini

# ==============================================================================
# homelab-mcp Gateway Configuration
# ==============================================================================
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_TRANSPORT=http
AUTH_ENABLED=false
SERVICE_TOKEN=""

# ==============================================================================
# LYOKO Autonomous Agent Configuration
# ==============================================================================
LYOKO_HOST=0.0.0.0
LYOKO_PORT=9000
MCP_SERVER_URL=http://localhost:8000/mcp
MCP_FAIL_FAST=true

# ==============================================================================
# Persistent Storage & Episodic Vector Memory (PostgreSQL + pgvector)
# ==============================================================================
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=lyoko
POSTGRES_USER=lyoko
POSTGRES_PASSWORD=your-postgres-password
POSTGRES_CHECKPOINTER_URL=postgresql://lyoko:your-postgres-password@localhost:5432/lyoko

# ==============================================================================
# Telegram Operator & HITL Approvals (Optional)
# ==============================================================================
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_ALLOWED_USER_IDS=[]
TELEGRAM_ALLOWED_CHAT_IDS=[]
TELEGRAM_DEFAULT_CHAT_ID=""

# ==============================================================================
# Upstream Integrations (Optional)
# ==============================================================================
# Home Assistant
HASS_ENABLED=true
HASS_URL=http://homeassistant.local:8123
HASS_TOKEN=your-long-lived-access-token

# UniFi Network Controller
UNIFI_ENABLED=true
UNIFI_URL=https://192.168.1.1
UNIFI_USER=admin
UNIFI_PASSWORD=your-unifi-password

# Grafana / Prometheus
GRAFANA_ENABLED=true
GRAFANA_URL=http://grafana.monitoring.svc.cluster.local:3000
GRAFANA_TOKEN=your-grafana-service-account-token

# GitHub MCP
GITHUB_ENABLED=true
GITHUB_TOKEN=your-github-personal-access-token
```

---

## 4. Running the Platform

Run both services in separate terminal sessions:

### Step 1: Start `homelab-mcp` Tool Gateway
```bash
uv run --package homelab-mcp python -m homelab_mcp.server
```
The gateway initializes upstream connections and listens on `http://localhost:8000/mcp`.

### Step 2: Start `lyoko` Autonomous Remediation Agent
```bash
uv run --package lyoko python -m lyoko.main
```
The agent starts the FastAPI webhook receiver on `http://localhost:9000` and establishes the Telegram polling worker if enabled.

---

## 5. Verification & Health Checks

Verify that both components are running and healthy:

```bash
# Check LYOKO agent health
curl http://localhost:9000/health
# Response: {"status": "ok"}

# Run test suite across all monorepo packages
uv run pytest

# Run linting and code quality checks
uv run ruff check .
```

---

## Next Steps & Deep Dives

- [System Architecture & Incident Lifecycle](architecture.md): Explore multi-agent coordination and sequence flows.
- [Security & Guardrails](security-guardrails.md): Learn about namespace isolation and human-in-the-loop policies.
- [homelab-mcp Package Guide](../packages/mcps/homelab-mcp/README.md): Configure tools for local IDEs (Claude Desktop, Cursor).
- [LYOKO Agent Guide](../packages/agents/lyoko/README.md): Configure Alertmanager webhooks and Telegram alerts.
