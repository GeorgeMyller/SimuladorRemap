#!/usr/bin/env bash
# E2E Playwright contra o app local, sem Docker (T221–T224, T187).
#
# 1. `npx vite build` do frontend (frontend/dist);
# 2. sobe duas estações do backend (`python -m simremap.api.serve`) em portas livres, cada uma com
#    um diretório de dados vazio: a do instrutor (baseURL) e a do aluno (SIMREMAP_E2E_STUDENT_URL,
#    usada pela jornada do Prof. Marcos);
# 3. espera `/api/v1/health` = ok nas duas;
# 4. corre `npx playwright test --project=chromium` (argumentos extra são repassados);
# 5. para os servidores e apaga os diretórios temporários.
#
# Variáveis: PW_PROJECT (padrão chromium), E2E_KEEP_DATA=1 mantém os dados (diagnóstico).
# Uso: scripts/e2e_local.sh [args do playwright]   (ou `make e2e-local`)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
PW_PROJECT="${PW_PROJECT:-chromium}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/simremap-e2e.XXXXXX")"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && wait "$pid" 2>/dev/null || true
  done
  if [[ "${E2E_KEEP_DATA:-0}" != "1" ]]; then rm -rf "$WORK"; else echo "dados mantidos em $WORK"; fi
}
trap cleanup EXIT INT TERM

free_port() {
  "$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

start_station() {  # $1 = nome, $2 = porta
  local name="$1" port="$2"
  mkdir -p "$WORK/$name"
  (
    cd "$ROOT/backend"
    SIMREMAP_ENV=dev SIMREMAP_DATA_DIR="$WORK/$name" SIMREMAP_STATIC_DIR="$ROOT/frontend/dist" \
      SIMREMAP_LOG_LEVEL=WARNING exec "$PY" -m simremap.api.serve --port "$port"
  ) >"$WORK/$name.log" 2>&1 &
  PIDS+=("$!")
}

wait_health() {  # $1 = URL base
  for _ in $(seq 1 120); do
    if curl -fsS "$1/api/v1/health" 2>/dev/null | grep -q '"status":"ok"'; then return 0; fi
    sleep 0.5
  done
  echo "servidor $1 não ficou saudável em 60 s" >&2
  return 1
}

echo "==> build do frontend"
(cd "$ROOT/frontend" && npx vite build >/dev/null)

INSTRUCTOR_PORT="$(free_port)"
STUDENT_PORT="$(free_port)"
while [[ "$STUDENT_PORT" == "$INSTRUCTOR_PORT" ]]; do STUDENT_PORT="$(free_port)"; done
INSTRUCTOR_URL="http://127.0.0.1:$INSTRUCTOR_PORT"
STUDENT_URL="http://127.0.0.1:$STUDENT_PORT"

echo "==> estações: instrutor $INSTRUCTOR_URL, aluno $STUDENT_URL"
start_station instrutor "$INSTRUCTOR_PORT"
start_station aluno "$STUDENT_PORT"
wait_health "$INSTRUCTOR_URL" || { tail -n 30 "$WORK/instrutor.log" >&2; exit 1; }
wait_health "$STUDENT_URL" || { tail -n 30 "$WORK/aluno.log" >&2; exit 1; }

echo "==> playwright ($PW_PROJECT)"
cd "$ROOT/frontend"
SIMREMAP_E2E_NO_SERVER=1 SIMREMAP_E2E_BASE_URL="$INSTRUCTOR_URL" SIMREMAP_E2E_STUDENT_URL="$STUDENT_URL" \
  npx playwright test --project="$PW_PROJECT" "$@"
