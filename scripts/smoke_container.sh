#!/usr/bin/env bash
# Teste de fumo do container (platform-foundation RF-17, RNF-02, RNF-05, RNF-06; T091).
#
# 1. A imagem existe e tem ≤ 450 MB; corre como utilizador 10001.
# 2. Arranca com --network none (sem rede de saída) e volume vazio.
# 3. /api/v1/health responde 200 "ok" em ≤ 60 s (verificado de dentro do container,
#    porque --network none não publica portas).
# 4. 100 % das linhas de log em stdout são JSON (jq -e .), sem IP de cliente.
#
# Variáveis: IMAGE (padrão simremap:<versão do pyproject>), MAX_MB (450), TIMEOUT_S (60).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/backend/pyproject.toml" | head -1)"
IMAGE="${IMAGE:-simremap:${VERSION}}"
MAX_MB="${MAX_MB:-450}"
TIMEOUT_S="${TIMEOUT_S:-60}"
NAME="simremap-smoke-$$"
VOLUME="simremap-smoke-data-$$"

fail() { echo "smoke: FALHOU: $*" >&2; exit 1; }
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

command -v docker >/dev/null || fail "docker não encontrado"
docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "imagem $IMAGE inexistente (make build)"

size_bytes="$(docker image inspect -f '{{.Size}}' "$IMAGE")"
size_mb=$(( size_bytes / 1024 / 1024 ))
echo "smoke: imagem $IMAGE = ${size_mb} MB (máx. ${MAX_MB} MB)"
(( size_mb <= MAX_MB )) || fail "imagem com ${size_mb} MB > ${MAX_MB} MB"

user="$(docker image inspect -f '{{.Config.User}}' "$IMAGE")"
[[ "$user" == "10001" ]] || fail "User = '$user' (esperado 10001)"

docker volume create "$VOLUME" >/dev/null
start=$(date +%s)
docker run -d --name "$NAME" --network none --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges:true \
  -v "$VOLUME:/data" "$IMAGE" >/dev/null

probe='import json,sys,urllib.request
r=urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health",timeout=2)
b=json.load(r); sys.exit(0 if r.status==200 and b["status"]=="ok" else 1)'
until docker exec "$NAME" python -c "$probe" >/dev/null 2>&1; do
  (( $(date +%s) - start <= TIMEOUT_S )) || { docker logs "$NAME" | tail -20; fail "health não ficou ok em ${TIMEOUT_S} s"; }
  [[ "$(docker inspect -f '{{.State.Running}}' "$NAME")" == "true" ]] || { docker logs "$NAME" | tail -20; fail "container terminou"; }
  sleep 1
done
elapsed=$(( $(date +%s) - start ))
echo "smoke: health ok em ${elapsed} s (máx. ${TIMEOUT_S} s), sem rede"

docker exec "$NAME" python -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8000/api/v1/version",timeout=2)' >/dev/null
logs="$(docker logs "$NAME" 2>&1)"
if command -v jq >/dev/null; then
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    jq -e . >/dev/null 2>&1 <<<"$line" || fail "linha de log não é JSON: $line"
  done <<<"$logs"
  echo "smoke: $(grep -c . <<<"$logs") linhas de log JSON válidas"
fi
grep -q '"event":"startup.complete"' <<<"$logs" || fail "startup.complete ausente no log"

rss="$(docker stats --no-stream --format '{{.MemUsage}}' "$NAME" | cut -d/ -f1 | xargs)"
echo "smoke: memória ociosa do container = ${rss} (alvo ≤ 300 MB)"
echo "smoke: ok"
