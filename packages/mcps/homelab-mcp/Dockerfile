FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency definition
COPY pyproject.toml /app/
COPY packages/mcps/homelab-mcp/pyproject.toml /app/packages/mcps/homelab-mcp/

# Install dependencies into virtual environment
RUN uv sync --package homelab-mcp --no-dev --frozen || uv sync --package homelab-mcp --no-dev

# Copy source code
COPY packages/mcps/homelab-mcp/src/ /app/packages/mcps/homelab-mcp/src/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "homelab_mcp.server"]
