# syntax=docker/dockerfile:1
FROM node:24.18.0-bookworm-slim AS web-builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/next.config.mjs ./
COPY web/src ./src
COPY web/public ./public
COPY web/scripts ./scripts
RUN npm run build

FROM node:24.18.0-bookworm-slim AS web-runtime
RUN groupadd --gid 10001 theos && useradd --uid 10001 --gid theos --create-home theos
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=web-builder --chown=theos:theos /app/.next/standalone ./
COPY --from=web-builder --chown=theos:theos /app/.next/static ./.next/static
COPY --from=web-builder --chown=theos:theos /app/public ./public
USER theos
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/ready').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]

FROM python:3.13-slim-trixie AS builder
ARG TARGETARCH
ARG TARGETVARIANT
# Less common targets build native dependencies when PyPI has no matching wheel.
RUN if [ "$TARGETARCH" != amd64 ] && [ "$TARGETARCH" != arm64 ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        build-essential cargo pkg-config libssl-dev libffi-dev libjpeg62-turbo-dev zlib1g-dev \
      && rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.9.26
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=uv-${TARGETARCH}-${TARGETVARIANT},target=/root/.cache/uv uv sync --locked --no-install-project --no-dev --extra server
COPY src/theos ./src/theos
COPY src/harness ./src/harness
COPY src/renderer ./src/renderer
COPY src/config ./src/config
COPY LICENSE README.md ./
RUN --mount=type=cache,id=uv-${TARGETARCH}-${TARGETVARIANT},target=/root/.cache/uv uv sync --locked --no-editable --no-dev --extra server

FROM python:3.13-slim-trixie AS runtime
ARG TARGETARCH
# Source-built Pillow links to these libraries instead of bundling them in a wheel.
RUN if [ "$TARGETARCH" != amd64 ] && [ "$TARGETARCH" != arm64 ]; then \
      apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
      && rm -rf /var/lib/apt/lists/*; \
    fi
RUN groupadd --gid 10001 theos && useradd --uid 10001 --gid theos --create-home theos \
    && mkdir -p /data && chown theos:theos /data
WORKDIR /app
COPY --from=builder --chown=theos:theos /app /app
ENV VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AGENT_HOST=0.0.0.0 AGENT_PORT=8080 AGENT_DATA_DIR=/data
USER theos
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"]
CMD ["python", "-m", "theos.server"]
