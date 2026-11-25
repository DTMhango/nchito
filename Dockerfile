# syntax=docker/dockerfile:1.7
# One image for web and worker. The SPA is built from frontend/ when it exists and served by
# FastAPI at /; without it the image serves the API only.

# ---- SPA (optional) -------------------------------------------------------------------------
FROM node:22-alpine AS spa
# SKIP_SPA=1 builds the API-only image even when frontend/ exists.
ARG SKIP_SPA=0
WORKDIR /build
RUN --mount=type=bind,target=/ctx \
    mkdir -p /build/dist && \
    if [ "$SKIP_SPA" != "1" ] && [ -f /ctx/frontend/package.json ]; then \
      mkdir -p /build/frontend && \
      tar -C /ctx/frontend --exclude=node_modules --exclude=dist -cf - . | tar -C /build/frontend -xf - && \
      cd /build/frontend && \
      if [ -f package-lock.json ]; then npm ci; else npm install; fi && \
      npm run build && cp -r dist/. /build/dist/ ; \
    else \
      echo "frontend/ not present: building the API-only image"; \
    fi

# ---- Python app -----------------------------------------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SPA_DIR=/app/static \
    FILES_DIR=/data/files

WORKDIR /app
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/app ./app
RUN pip install . && useradd --create-home --uid 10001 nchito && mkdir -p /data/files && chown -R nchito /data
COPY --from=spa /build/dist /app/static

USER nchito
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["nchito", "web"]
