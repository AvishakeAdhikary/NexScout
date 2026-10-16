# NexScout backend (api + migrations). UNVERIFIED until Docker is available. See docs/ROADMAP.md.
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first for layer caching.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --home /app nexscout \
    && mkdir -p /data/storage && chown -R nexscout /data
USER nexscout
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["nexscout", "serve", "--host", "0.0.0.0", "--port", "8000"]
