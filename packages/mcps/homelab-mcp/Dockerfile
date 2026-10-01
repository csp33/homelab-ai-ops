FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install kubernetes-mcp-server binary
RUN curl -fsSL -o /usr/local/bin/kubernetes-mcp-server \
    https://github.com/containers/kubernetes-mcp-server/releases/latest/download/kubernetes-mcp-server-linux-amd64 \
    && chmod +x /usr/local/bin/kubernetes-mcp-server

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy root workspace and manifests + lockfile
COPY pyproject.toml uv.lock README.md ./
COPY packages/mcps/homelab-mcp/pyproject.toml packages/mcps/homelab-mcp/README.md packages/mcps/homelab-mcp/
COPY packages/agents/lyoko/pyproject.toml packages/agents/lyoko/README.md packages/agents/lyoko/

# Install dependencies into virtual environment
RUN uv sync --package homelab-mcp --no-dev --no-install-workspace --frozen

# Copy source code
COPY packages/mcps/homelab-mcp/src/ packages/mcps/homelab-mcp/src/

# Install package into venv
RUN uv sync --package homelab-mcp --no-dev --frozen

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "homelab_mcp.server"]
