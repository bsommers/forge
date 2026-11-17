# Stage 1: Deterministic dependency build via uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-install-project --no-dev

COPY forge-manifest.json README.md ./
COPY respx ./respx
COPY forge ./forge
COPY src ./src
RUN uv sync --no-dev

# Stage 2: Hardened non-root runtime
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 nonroot \
    && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin nonroot

WORKDIR /app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
COPY --from=builder --chown=root:root /app/forge-manifest.json /app/forge-manifest.json
COPY --from=builder --chown=root:root /app/respx /app/respx
COPY --from=builder --chown=root:root /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT="stdio"

USER 65532:65532
ENTRYPOINT ["mcp-server"]
