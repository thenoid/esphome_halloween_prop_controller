# syntax=docker/dockerfile:1
FROM python:3.13-slim AS dependencies

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10001 collector \
    && useradd --uid 10001 --gid collector --no-create-home collector \
    && mkdir /data && chown collector:collector /data
COPY --from=dependencies /app/.venv /app/.venv
COPY collector ./collector
USER collector
EXPOSE 8080/tcp 18512/udp
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=8s --start-period=10s --retries=3 \
    CMD ["python", "-m", "collector.healthcheck"]
CMD ["python", "-m", "collector"]
