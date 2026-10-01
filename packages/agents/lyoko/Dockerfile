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
COPY packages/agents/lyoko/pyproject.toml /app/packages/agents/lyoko/

# Install dependencies into virtual environment
RUN uv sync --package lyoko --no-dev --frozen || uv sync --package lyoko --no-dev

# Copy source code
COPY packages/agents/lyoko/src/ /app/packages/agents/lyoko/src/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["python", "-m", "lyoko.main"]
