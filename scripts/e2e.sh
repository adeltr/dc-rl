#!/usr/bin/env bash
# Lance l'API et l'interface sur des ports dédiés, exécute le test navigateur, puis arrête tout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
API_PORT="${E2E_API_PORT:-8010}"
UI_PORT="${E2E_UI_PORT:-5180}"
export TWIN_BASE_SITE="${TWIN_BASE_SITE:-us_ny_jfk}"   # météo du site de base accessible hors réseau
export TWIN_STORE_DIR="$WORK/store" TWIN_SCENARIO_LOG="$WORK/scenarios.jsonl" TWIN_EXPORT_DIR="$WORK/exports"
PIDS=()
# chaque serveur dans son propre groupe de processus : l'arrêt atteint aussi les enfants (npx -> vite)
cleanup() { for pid in "${PIDS[@]}"; do kill -- "-$pid" 2>/dev/null || true; done; rm -rf "$WORK"; }
trap cleanup EXIT

cd "$ROOT"
setsid .venv/bin/uvicorn api.app:app --host 127.0.0.1 --port "$API_PORT" > "$WORK/api.log" 2>&1 &
PIDS+=($!)
(cd web && TWIN_API_URL="http://127.0.0.1:$API_PORT" exec setsid npx vite --port "$UI_PORT" --strictPort > "$WORK/vite.log" 2>&1) &
PIDS+=($!)

for _ in $(seq 1 180); do
  curl -sf "http://127.0.0.1:$API_PORT/health" | grep -q '"base_ready":true' && break
  sleep 1
done
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$UI_PORT/" > /dev/null && break; sleep 1; done

cd web && TWIN_UI_URL="http://127.0.0.1:$UI_PORT/" node e2e/e2e.mjs
