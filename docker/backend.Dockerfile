# NexScout backend: api, worker and migrations (verified with compose --profile full; see ROADMAP).
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

# Headless Chromium renders application documents to PDF (worker). JavaScript and network are
# disabled while rendering; see infrastructure/render.py.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN /app/.venv/bin/playwright install --with-deps chromium-headless-shell     && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --home /app nexscout \
    && mkdir -p /data/storage && chown -R nexscout /data
USER nexscout
ENV PATH="/app/.venv/bin:$PATH"
ARG NEXSCOUT_VERSION=""
ENV NEXSCOUT_VERSION=${NEXSCOUT_VERSION} NEXSCOUT_ENV=production
EXPOSE 8000
CMD ["nexscout", "serve", "--host", "0.0.0.0", "--port", "8000"]
