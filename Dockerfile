FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    tectonic fontconfig fonts-liberation \
    curl xvfb procps lsof ca-certificates && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir --no-deps python-jobspy && \
    pip install --no-cache-dir pydantic tls-client requests markdownify regex
ENV CHROME_PATH=/usr/bin/chromium
VOLUME ["/sandbox/nexscout"]
ENV NEXSCOUT_DIR=/sandbox/nexscout
ENTRYPOINT ["nexscout"]
CMD ["doctor"]
