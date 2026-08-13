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

load_canonical_env() {
  # OPT-002: 只认项目根目录 .env；src/.env 仅在根文件缺失时迁移一次
  PYTHONPATH="$PROJECT_DIR/src" python3 - "$PROJECT_DIR" <<'PY'
import sys
from pathlib import Path
from app.env_file import ensure_canonical_env

_path, warnings = ensure_canonical_env(Path(sys.argv[1]))
for w in warnings:
    print(f"[WARN] {w}", file=sys.stderr)
PY
  local root_env="$PROJECT_DIR/.env"
  if [ -f "$root_env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$root_env"
    set +a
    echo "Loaded $root_env"
  fi
}

ensure_persistent_jwt_secret() {
  if [ -n "$JWT_SECRET" ]; then
    return 0
  fi
  JWT_SECRET="$(python3 -c "import secrets; print(secrets.token_hex(32))")"
  export JWT_SECRET
  PYTHONPATH="$PROJECT_DIR/src" python3 - "$PROJECT_DIR/.env" "$JWT_SECRET" <<'PY'
import sys
from pathlib import Path
from app.env_file import persist_jwt_secret

persist_jwt_secret(Path(sys.argv[1]), sys.argv[2])
PY
  echo "Generated JWT_SECRET and saved to $PROJECT_DIR/.env"
}

case "${1:-start}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Server already running (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    cd "$PROJECT_DIR"
    load_canonical_env
    PORT="${SERVER_PORT:-17957}"
    # 监听地址：默认只绑定回环（经反向代理对外暴露），直连部署设 SERVER_HOST=0.0.0.0
    HOST="${SERVER_HOST:-127.0.0.1}"
    echo "Starting server on $HOST:$PORT..."
    ensure_persistent_jwt_secret
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
    # 子路径反代部署（如 https://host/prd-review/ -> 本服务）时设置 ROOT_PATH=/prd-review
    ROOT_PATH_ARG=()
    if [ -n "$ROOT_PATH" ]; then
      ROOT_PATH_ARG=(--root-path "$ROOT_PATH")
      echo "Mounting under root-path: $ROOT_PATH"
    fi
    PYTHONPATH=src nohup uvicorn src.main:app \
      --host "$HOST" \
      --port "$PORT" \
      "${ROOT_PATH_ARG[@]}" \
      --access-log \
      >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Server started (PID $(cat "$PID_FILE"))"
    sleep 2
    curl -s --max-time 5 http://localhost:$PORT/api/health && echo " — health check OK" || echo " — health check FAILED"
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
      load_canonical_env
      PORT="${SERVER_PORT:-17957}"
      echo "Server running (PID $(cat "$PID_FILE"))"
      curl -s --max-time 5 http://localhost:$PORT/api/health && echo "" || echo "Health check failed"
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
