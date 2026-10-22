# SimuladorRemap — imagem única para dev/staging/prod (platform-foundation RF-17; D-02, D-03).
# Multi-arquitetura: docker buildx build --platform linux/amd64,linux/arm64 -t simremap:<versão> .
#   1. frontend : Node 20, npm ci + vite build  -> /fe/dist
#   2. native   : (opcional, feature 003) wheel ABI3 da extensão Rust simremap_rs (maturin)
#   3. backend  : uv (lockfile), venv em /app/.venv sem dependências de desenvolvimento
#   4. runtime  : python:3.12-slim, utilizador não-root 10001, HEALTHCHECK em /api/v1/health
#
# Kernels nativos (003, premissa Q1): --build-arg SIMREMAP_NATIVE_BUILD=0 salta o estágio Rust.
# Se a compilação falhar, o build continua sem wheel e a imagem usa o fallback Python puro
# (SIMREMAP_NATIVE=auto). SIMREMAP_NATIVE_BUILD=require faz a falha do Rust parar o build.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:20-alpine
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.6.16
ARG SIMREMAP_NATIVE_BUILD=1

FROM ${UV_IMAGE} AS uv

# ----------------------------------------------------------------------------- 1. frontend
FROM ${NODE_IMAGE} AS frontend
WORKDIR /fe
ENV CI=1 NPM_CONFIG_FUND=false NPM_CONFIG_AUDIT=false
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ ./
RUN npm run build

# ----------------------------------------------------------------------------- 2. native (opcional)
FROM ${PYTHON_IMAGE} AS native
ARG SIMREMAP_NATIVE_BUILD
ARG RUST_TOOLCHAIN=stable
ARG MATURIN_VERSION=1.15.0
ENV CARGO_HOME=/opt/cargo RUSTUP_HOME=/opt/rustup PATH="/opt/cargo/bin:${PATH}"
WORKDIR /build
COPY backend/rust/simremap_rs/Cargo.toml backend/rust/simremap_rs/Cargo.lock \
     backend/rust/simremap_rs/pyproject.toml ./
COPY backend/rust/simremap_rs/src ./src
COPY backend/rust/simremap_rs/python ./python
RUN --mount=type=cache,target=/opt/cargo/registry \
    set -eu; mkdir -p /wheels; \
    if [ "${SIMREMAP_NATIVE_BUILD}" = "0" ]; then echo "simremap_rs: estágio nativo desligado"; exit 0; fi; \
    find python -name '*.so' -delete; \
    if ( apt-get update \
         && apt-get install -y --no-install-recommends curl ca-certificates gcc libc6-dev \
         && curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
              --default-toolchain "${RUST_TOOLCHAIN}" --no-modify-path \
         && pip install --no-cache-dir "maturin==${MATURIN_VERSION}" \
         && maturin build --release --compatibility linux -i python3.12 -o /wheels ); then \
        ls -l /wheels; \
    elif [ "${SIMREMAP_NATIVE_BUILD}" = "require" ]; then \
        echo "simremap_rs: falha no build nativo (require)" >&2; exit 1; \
    else \
        echo "simremap_rs: build nativo falhou; a imagem usa o fallback Python" >&2; \
        rm -f /wheels/*.whl; \
    fi

# ----------------------------------------------------------------------------- 3. backend
FROM ${PYTHON_IMAGE} AS backend
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev
# Wheel ABI3 da extensão (se o estágio nativo o produziu); sem ele fica o fallback Python.
COPY --from=native /wheels /tmp/wheels
RUN --mount=type=cache,target=/root/.cache/uv \
    if ls /tmp/wheels/*.whl >/dev/null 2>&1; then \
        uv pip install --python /app/.venv/bin/python --no-deps /tmp/wheels/*.whl \
        && /app/.venv/bin/python -c "import simremap_rs; print('simremap_rs', simremap_rs.__version__)"; \
    else echo "simremap_rs ausente: fallback Python"; fi; \
    rm -rf /tmp/wheels

# ----------------------------------------------------------------------------- 4. runtime
FROM ${PYTHON_IMAGE} AS runtime
ARG GIT_SHA=""
ARG BUILD_TIME_UTC=""
LABEL org.opencontainers.image.title="SimuladorRemap" \
      org.opencontainers.image.description="Simulador de remap automotivo em dinamômetro (local-first)" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME_UTC}"
RUN useradd --uid 10001 --user-group --create-home --shell /usr/sbin/nologin simremap \
    && mkdir -p /data \
    && chown 10001:10001 /data
WORKDIR /app
COPY --from=backend --chown=root:root /app /app
COPY --from=frontend --chown=root:root /fe/dist /app/static
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    SIMREMAP_ENV=prod \
    SIMREMAP_STATIC_DIR=/app/static \
    SIMREMAP_DATA_DIR=/data \
    SIMREMAP_GIT_SHA="${GIT_SHA}" \
    SIMREMAP_BUILD_TIME_UTC="${BUILD_TIME_UTC}"
USER 10001
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s --start-period=60s --retries=6 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=2).status==200 else 1)"]
STOPSIGNAL SIGTERM
CMD ["python", "-m", "simremap.api.serve", "--host", "0.0.0.0", "--port", "8000"]
