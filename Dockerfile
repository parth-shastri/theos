# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.9.26
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev --extra server
COPY src/theos ./src/theos
COPY src/harness ./src/harness
COPY src/renderer ./src/renderer
COPY src/config ./src/config
COPY LICENSE README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-editable --no-dev --extra server

FROM python:3.13-slim AS runtime
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
