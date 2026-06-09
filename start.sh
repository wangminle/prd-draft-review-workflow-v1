#!/bin/bash
# AI产品需求初审 — 启动脚本
# Usage: ./start.sh [stop|restart|status]

set -e

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="${RUNTIME_ROOT:-$PROJECT_DIR/runtime}"
PID_FILE="$RUNTIME_DIR/server.pid"
LOG_FILE="$RUNTIME_DIR/logs/app.log"

mkdir -p "$RUNTIME_DIR/logs"

case "${1:-start}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Server already running (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    cd "$PROJECT_DIR"
    # Load .env first (preserves existing env vars), then resolve PORT
    for env_file in "$PROJECT_DIR/.env" "$PROJECT_DIR/src/.env"; do
      if [ -f "$env_file" ]; then
        set -a; source "$env_file"; set +a
        echo "Loaded $env_file"
      fi
    done
    PORT="${SERVER_PORT:-17957}"
    echo "Starting server on port $PORT..."
    if [ -z "$JWT_SECRET" ]; then
      export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
      echo "Generated JWT_SECRET for this session"
    fi
    export RUNTIME_ROOT="$RUNTIME_DIR"
    # 可选依赖检测（Pi Agent 功能需要，主应用不受影响）
    LOCAL_PI_BIN="$PROJECT_DIR/node_modules/.bin/pi"
    if [ -x "$LOCAL_PI_BIN" ]; then
      echo "Pi Agent CLI: $($LOCAL_PI_BIN --version 2>/dev/null) ($LOCAL_PI_BIN)"
    elif command -v pi &>/dev/null; then
      echo "Pi Agent CLI: $(pi --version 2>/dev/null) ($(command -v pi))"
      echo "[WARN] Using global pi CLI; run npm install to use project-local node_modules/.bin/pi"
    else
      echo "[WARN] pi CLI not found — Pi Agent features will be unavailable"
    fi
    if ! command -v node &>/dev/null; then
      echo "[WARN] node not found — Pi Agent extensions will be unavailable"
    fi
    if ! command -v npm &>/dev/null; then
      echo "[WARN] npm not found — Pi Agent project dependencies cannot be installed"
    fi
    PYTHONPATH=src nohup uvicorn src.main:app \
      --host 0.0.0.0 \
      --port $PORT \
      --access-log \
      >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Server started (PID $(cat "$PID_FILE"))"
    sleep 2
    curl -s http://localhost:$PORT/api/health && echo " — health check OK" || echo " — health check FAILED"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      PID="$(cat "$PID_FILE")"
      echo "Stopping server (PID $PID)..."
      kill "$PID" 2>/dev/null || true
      sleep 2
      kill -9 "$PID" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Server stopped"
    else
      echo "No PID file found, server not running"
    fi
    ;;
  restart)
    "$SCRIPT_PATH" stop
    sleep 1
    "$SCRIPT_PATH" start
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      PORT="${SERVER_PORT:-17957}"
      echo "Server running (PID $(cat "$PID_FILE"))"
      curl -s http://localhost:$PORT/api/health && echo "" || echo "Health check failed"
    else
      echo "Server not running"
      rm -f "$PID_FILE"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
