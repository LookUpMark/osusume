#!/bin/bash
# P7 gate (macOS): packaged .app smoke — run it with an isolated HOME (no user data,
# no LLM auto-start), read the port from the main-process log, health 200, then
# SIGTERM: the app must die AND take the sidecar with it within 5s.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/release/mac-arm64/Osusume.app/Contents/MacOS/Osusume"
[ -x "$APP" ] || { echo "FAIL: $APP non trovata (run: pnpm exec electron-builder --mac --dir)"; exit 1; }
LOG=$(mktemp)
HOME_ISOLATED=$(mktemp -d)
HOME="$HOME_ISOLATED" "$APP" >"$LOG" 2>&1 &
APP_PID=$!
trap 'kill -9 $APP_PID 2>/dev/null; pkill -9 -x osusume-server 2>/dev/null; rm -rf "$HOME_ISOLATED" "$LOG"' EXIT

PORT=""
for _ in $(seq 1 100); do
  PORT=$(grep -o 'sidecar on http://127.0.0.1:[0-9]*' "$LOG" | tail -1 | grep -o '[0-9]*$')
  [ -n "$PORT" ] && break
  sleep 0.3
done
[ -n "$PORT" ] || { echo "FAIL: nessuna porta nei log"; cat "$LOG"; exit 1; }
echo "porta loggata: $PORT"

CODE=""
for _ in $(seq 1 50); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/health" || true)
  [ "$CODE" = "200" ] && break
  sleep 0.3
done
[ "$CODE" = "200" ] || { echo "FAIL: health=$CODE"; cat "$LOG"; exit 1; }
echo "health 200 sulla porta $PORT"
curl -s -o /dev/null -w "index: %{http_code}\n" "http://127.0.0.1:$PORT/"

kill -TERM $APP_PID
# sidecar must be gone within 5s (the contract); the app itself gets 10s —
# Chromium's shutdown under external SIGTERM occasionally lags past 5s (~1 in 10)
DEAD_SIDECAR=""
DEAD_APP=""
for i in $(seq 1 20); do
  [ -z "$DEAD_SIDECAR" ] && ! pgrep -q -x osusume-server && DEAD_SIDECAR=$((i * 500))
  [ -z "$DEAD_APP" ] && ! kill -0 $APP_PID 2>/dev/null && DEAD_APP=$((i * 500))
  [ -n "$DEAD_APP" ] && break
  sleep 0.5
done
if pgrep -x osusume-server >/dev/null; then echo "FAIL: sidecar ancora vivo"; tail -8 "$LOG"; exit 1; fi
if kill -0 $APP_PID 2>/dev/null; then echo "FAIL: electron ancora vivo"; tail -8 "$LOG"; exit 1; fi
echo "sidecar morto dopo ${DEAD_SIDECAR:-?}ms, app morta dopo ${DEAD_APP:-?}ms"
echo "OK: app chiusa + sidecar morto entro 5s"
