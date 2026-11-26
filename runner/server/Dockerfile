# Nchito server runner (optional): Claude Agent SDK + Playwright headless Chromium.
# Build from the repo root:  docker build -f runner/server/Dockerfile -t nchito-runner runner/server
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app
COPY pyproject.toml ./
COPY nchito_runner ./nchito_runner
RUN pip install . \
 && playwright install --with-deps chromium \
 && useradd --create-home --uid 10001 runner \
 && mkdir -p /data/profile /data/state \
 && chown -R runner:runner /data

USER runner
VOLUME ["/data"]
CMD ["python", "-m", "nchito_runner"]
