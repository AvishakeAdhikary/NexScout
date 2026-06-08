FROM python:3.11-slim

# System dependencies: chromium for undetected_chromedriver, plus a handful of
# utilities used by the browser pool & doctor. Tectonic isn't in Debian trixie
# repos, so we fetch the upstream static binary in a separate layer below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fontconfig \
        fonts-liberation \
        ca-certificates \
        curl \
        xvfb \
        procps \
        lsof \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Tectonic: LaTeX engine used by the resume renderer. Upstream publishes a
# static x86_64 musl binary on GitHub releases — fetch and drop it onto PATH.
ARG TECTONIC_VERSION=0.15.0
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64) tarball="tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" ;; \
        aarch64) tarball="tectonic-${TECTONIC_VERSION}-aarch64-unknown-linux-musl.tar.gz" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@${TECTONIC_VERSION}/${tarball}"; \
    curl -fsSL "$url" -o /tmp/tectonic.tar.gz; \
    tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic; \
    rm /tmp/tectonic.tar.gz; \
    chmod +x /usr/local/bin/tectonic; \
    tectonic --version

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# Two-step install: editable install of nexscout first (resolves its deps),
# then python-jobspy without its (over-pinned) deps, then the runtime libs
# python-jobspy actually uses at import time. See plan.md §24.
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir --no-deps python-jobspy \
    && pip install --no-cache-dir pydantic tls-client requests markdownify regex

ENV CHROME_PATH=/usr/bin/chromium \
    LMSTUDIO_URL=http://host.docker.internal:1234/v1 \
    NEXSCOUT_DIR=/sandbox/nexscout

VOLUME ["/sandbox/nexscout"]

ENTRYPOINT ["nexscout"]
CMD ["doctor"]
