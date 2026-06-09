#!/bin/bash
# AI产品需求初审 — 保守版本更新脚本
# 用法：./update.sh [选项]
#
# 核心原则：
#   - 只替换代码与随版本交付的配置模板，不改写 runtime 业务数据
#   - 品牌迁移只执行 scan/plan，生成报告后由人工决定是否单独 apply
#   - 更新包必须先通过路径与必要文件校验，再进入替换步骤
#   - 失败时优先从本次备份回滚代码与本地配置

set -e

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="${RUNTIME_ROOT:-$PROJECT_DIR/runtime}"
PID_FILE="$RUNTIME_DIR/server.pid"
BACKUP_DIR="$RUNTIME_DIR/update_backups"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-15}"
HEALTH_RETRIES="${HEALTH_RETRIES:-5}"
NEW_VERSION="0.2.12"

SKIP_MIGRATE=false
SKIP_BACKUP=false
FORCE=false
ROLLBACK_ON_FAILURE=true
CODE_PACKAGE=""
CURRENT_BACKUP_DIR=""
MIGRATE_REPORT=""

usage() {
  cat <<'EOF'
用法: ./update.sh [选项]

选项:
  --package PATH    指定更新包路径，默认查找当前目录下 *code-config*.tar.gz
  --skip-migrate   跳过迁移工具 scan/plan 检查
  --skip-backup    跳过备份步骤（风险：失败时无法自动回滚）
  --force          强制更新，跳过版本相同确认
  --no-rollback    失败时不自动回滚
  -h, --help       显示帮助

说明:
  本脚本不会自动执行品牌迁移 apply；如需写入 runtime/config/ui-branding.yaml，
  请先阅读 scan/plan 生成的报告，再单独手动执行迁移工具 apply。
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --package)
      shift
      if [ -z "${1:-}" ]; then
        echo "[FAIL] --package 需要路径参数"
        exit 1
      fi
      CODE_PACKAGE="$1"
      ;;
    --skip-migrate) SKIP_MIGRATE=true ;;
    --skip-backup) SKIP_BACKUP=true ;;
    --force) FORCE=true ;;
    --no-rollback) ROLLBACK_ON_FAILURE=false ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[FAIL] 未知参数: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

log() { echo "[UPDATE] $1"; }
warn() { echo "[WARN] $1"; }
fail() { echo "[FAIL] $1"; }

read_version_from_main() {
  local main_py="$1"
  if [ ! -f "$main_py" ]; then
    echo "unknown"
    return
  fi
  python3 - "$main_py" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'version\s*=\s*"([^"]+)"', text)
print(match.group(1) if match else "unknown")
PY
}

get_current_version() {
  read_version_from_main "$PROJECT_DIR/src/main.py"
}

get_server_port() {
  local port="${SERVER_PORT:-}"
  if [ -z "$port" ]; then
    for env_file in "$PROJECT_DIR/.env" "$PROJECT_DIR/src/.env"; do
      if [ -f "$env_file" ]; then
        local value
        value=$(python3 - "$env_file" <<'PY'
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() == "SERVER_PORT":
        print(value.strip().strip('"').strip("'"))
        break
PY
)
        if [ -n "$value" ]; then
          port="$value"
        fi
      fi
    done
  fi
  echo "${port:-17957}"
}

get_running_version() {
  local port
  port="$(get_server_port)"
  curl -s "http://localhost:$port/api/health" 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null || echo "not_running"
}

wait_for_health() {
  local port
  port="$(get_server_port)"
  local attempt=0
  while [ "$attempt" -lt "$HEALTH_RETRIES" ]; do
    attempt=$((attempt + 1))
    local resp
    resp=$(curl -s "http://localhost:$port/api/health" 2>/dev/null || true)
    if echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='ok' else 1)" 2>/dev/null; then
      local version
      version=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null)
      log "健康检查通过 — 版本 $version (尝试 $attempt/$HEALTH_RETRIES)"
      return 0
    fi
    log "健康检查未通过，等待 ${HEALTH_TIMEOUT}s... (尝试 $attempt/$HEALTH_RETRIES)"
    sleep "$HEALTH_TIMEOUT"
  done
  return 1
}

find_code_package() {
  if [ -n "$CODE_PACKAGE" ]; then
    echo "$CODE_PACKAGE"
    return
  fi
  if [ -f "$PROJECT_DIR/prd-draft-review-workflow-v1-code-config.tar.gz" ]; then
    echo "$PROJECT_DIR/prd-draft-review-workflow-v1-code-config.tar.gz"
    return
  fi
  find "$PROJECT_DIR" -maxdepth 1 -name "*code-config*.tar.gz" -type f | sort | head -1
}

validate_update_package() {
  local package="$1"
  if [ ! -f "$package" ]; then
    fail "更新包不存在: $package"
    return 1
  fi

  local listing
  listing="$(tar -tzf "$package")"

  if echo "$listing" | grep -Eq '(^|/)\.\.(/|$)|^/'; then
    fail "更新包包含不安全路径"
    return 1
  fi

  if echo "$listing" | grep -Eq '(^|/)runtime/data(/|$)|(^|/)runtime/uploads(/|$)|(^|/)runtime/logs(/|$)|(^|/)runtime/results(/|$)|(^|/)runtime/storage(/|$)'; then
    fail "更新包包含 runtime 业务数据目录，拒绝更新"
    return 1
  fi

  if ! echo "$listing" | grep -Eq '(^|/)src/main\.py$'; then
    fail "更新包缺少 src/main.py"
    return 1
  fi

  if ! echo "$listing" | grep -Eq '(^|/)start\.sh$'; then
    warn "更新包缺少 start.sh，将保留当前启动脚本"
  fi

  return 0
}

safe_extract_package() {
  local package="$1"
  local temp_dir="$2"
  tar -xzf "$package" -C "$temp_dir"

  local direct_main="$temp_dir/src/main.py"
  if [ -f "$direct_main" ]; then
    echo "$temp_dir"
    return
  fi

  local candidate
  candidate=$(find "$temp_dir" -mindepth 1 -maxdepth 2 -type f -path "*/src/main.py" | head -1)
  if [ -n "$candidate" ]; then
    dirname "$(dirname "$candidate")"
    return
  fi

  fail "解压后未找到 src/main.py"
  return 1
}

stop_service() {
  log "停止当前服务..."
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    "$PROJECT_DIR/start.sh" stop
    sleep 2
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      warn "服务未正常停止，强制终止..."
      kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    log "服务已停止"
  else
    log "服务未在运行"
    rm -f "$PID_FILE"
  fi
}

create_backup() {
  if [ "$SKIP_BACKUP" = true ]; then
    warn "跳过备份 — 失败时将无法自动回滚"
    return
  fi

  local current_version="$1"
  local timestamp
  timestamp=$(date +%Y%m%d-%H%M%S)
  CURRENT_BACKUP_DIR="$BACKUP_DIR/backup-${current_version}-${timestamp}"

  log "创建备份: $CURRENT_BACKUP_DIR"
  mkdir -p "$CURRENT_BACKUP_DIR"

  tar -czf "$CURRENT_BACKUP_DIR/code.tar.gz" \
    --exclude='runtime' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.tar.gz' \
    -C "$PROJECT_DIR" \
    src tools tests docs skills start.sh update.sh requirements.txt pyproject.toml README.md CLAUDE.md AGENTS.md 2>/dev/null || true

  if [ -d "$RUNTIME_DIR/config" ]; then
    cp -R "$RUNTIME_DIR/config" "$CURRENT_BACKUP_DIR/runtime_config" 2>/dev/null || true
  fi
  if [ -d "$RUNTIME_DIR/assets" ]; then
    cp -R "$RUNTIME_DIR/assets" "$CURRENT_BACKUP_DIR/runtime_assets" 2>/dev/null || true
  fi
  if [ -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env" "$CURRENT_BACKUP_DIR/project.env"
  fi
  if [ -f "$PROJECT_DIR/src/.env" ]; then
    cp "$PROJECT_DIR/src/.env" "$CURRENT_BACKUP_DIR/src.env"
  fi

  log "备份完成: $CURRENT_BACKUP_DIR"
}

copy_versioned_files() {
  local extracted_dir="$1"

  log "更新代码文件..."
  for item in src tools tests docs skills; do
    if [ -d "$extracted_dir/$item" ]; then
      rm -rf "$PROJECT_DIR/$item"
      cp -R "$extracted_dir/$item" "$PROJECT_DIR/$item"
      log "  更新 $item/"
    fi
  done

  for file in start.sh requirements.txt pyproject.toml README.md CLAUDE.md AGENTS.md LICENSE; do
    if [ -f "$extracted_dir/$file" ]; then
      cp "$extracted_dir/$file" "$PROJECT_DIR/$file"
      log "  更新 $file"
    fi
  done

  if [ -d "$extracted_dir/runtime/config" ]; then
    mkdir -p "$RUNTIME_DIR/config"
    for f in "$extracted_dir/runtime/config/"*; do
      if [ -f "$f" ]; then
        local fname
        fname=$(basename "$f")
        if echo "$fname" | grep -Eq 'example|template'; then
          if [ ! -f "$RUNTIME_DIR/config/$fname" ]; then
            cp "$f" "$RUNTIME_DIR/config/$fname"
            log "  新增 runtime/config/$fname"
          else
            log "  保留已有 runtime/config/$fname"
          fi
        fi
      fi
    done
  fi
}

sync_yaml_version() {
  # 确保 ui-branding.yaml 中的 app_version 与新代码版本一致，
  # 避免"旧 yaml 版本号覆盖新代码版本号"导致前端显示版本滞后。
  local yaml_path="$RUNTIME_DIR/config/ui-branding.yaml"
  if [ ! -f "$yaml_path" ]; then
    log "ui-branding.yaml 不存在，版本号将由代码默认值提供"
    return
  fi

  # 用 python3 做 YAML 行级替换（保留注释、格式和其他字段）
  local result
  result=$(python3 - "$yaml_path" "$NEW_VERSION" <<'PY'
import sys
from pathlib import Path

yaml_path = Path(sys.argv[1])
new_version = sys.argv[2]
text = yaml_path.read_text(encoding="utf-8")

lines = text.splitlines()
replaced = False
old_val = ""
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("#"):
        continue
    if ":" not in stripped:
        continue
    key, _sep, val = stripped.partition(":")
    if key.strip() == "app_version":
        indent = line[:len(line) - len(line.lstrip())]
        old_val = val.strip().strip('"').strip("'")
        lines[i] = f"{indent}app_version: \"{new_version}\""
        replaced = True
        break

if replaced:
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"app_version updated from '{old_val}' to '{new_version}'")
else:
    lines.insert(0, f"app_version: \"{new_version}\"")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"app_version inserted as '{new_version}'")
PY
)
  log "版本号同步: $result"
}

run_migration_plan() {
  if [ "$SKIP_MIGRATE" = true ] || [ ! -f "$PROJECT_DIR/tools/migrate_branding.py" ]; then
    log "跳过迁移工具检查"
    return
  fi

  # 注意：此函数在代码替换之前调用，scan_html 读取的是旧版 HTML，
  # 能正确提取 login_notice 等文本配置。代码替换后再读 HTML 就是新版了。
  log "运行迁移工具 scan 检查旧配置兼容性..."
  if ! python3 "$PROJECT_DIR/tools/migrate_branding.py" scan \
      --legacy-code-dir "$PROJECT_DIR" \
      --legacy-runtime-dir "$RUNTIME_DIR"; then
    warn "scan 执行异常，跳过迁移检查"
    return
  fi
  log "scan 完成"

  log "运行迁移工具 plan 生成差异报告..."
  python3 "$PROJECT_DIR/tools/migrate_branding.py" plan \
    --legacy-code-dir "$PROJECT_DIR" \
    --legacy-runtime-dir "$RUNTIME_DIR" \
    --target-runtime-dir "$RUNTIME_DIR"

  MIGRATE_REPORT="$RUNTIME_DIR/config/ui-branding.scan-report.md"
  if [ -f "$MIGRATE_REPORT" ]; then
    log "差异报告: $MIGRATE_REPORT"
    if [ "$FORCE" = false ]; then
      echo ""
      echo "===== 迁移差异报告 ====="
      cat "$MIGRATE_REPORT"
      echo ""
      echo "更新脚本只生成品牌迁移报告，不自动写入 runtime/config/ui-branding.yaml。"
      echo "如需应用报告中的配置，请人工确认后单独执行 migrate_branding.py apply。"
      echo ""
    fi
    warn "未自动 apply 品牌迁移，已保留 scan/plan 报告供人工确认"
    warn "后续可手动运行: python3 tools/migrate_branding.py apply --legacy-code-dir . --legacy-runtime-dir runtime --target-runtime-dir runtime"
  fi
}

restore_backup() {
  if [ "$ROLLBACK_ON_FAILURE" != true ] || [ "$SKIP_BACKUP" = true ] || [ ! -d "$CURRENT_BACKUP_DIR" ]; then
    fail "无法回滚（未创建备份或回滚已禁用）— 请手动排查"
    return 1
  fi

  log "自动回滚到旧版本..."
  "$PROJECT_DIR/start.sh" stop 2>/dev/null || true

  if [ -f "$CURRENT_BACKUP_DIR/code.tar.gz" ]; then
    tar -xzf "$CURRENT_BACKUP_DIR/code.tar.gz" -C "$PROJECT_DIR"
  fi

  if [ -d "$CURRENT_BACKUP_DIR/runtime_config" ]; then
    rm -rf "$RUNTIME_DIR/config"
    cp -R "$CURRENT_BACKUP_DIR/runtime_config" "$RUNTIME_DIR/config"
  fi
  if [ -d "$CURRENT_BACKUP_DIR/runtime_assets" ]; then
    rm -rf "$RUNTIME_DIR/assets"
    cp -R "$CURRENT_BACKUP_DIR/runtime_assets" "$RUNTIME_DIR/assets"
  fi

  if [ -f "$CURRENT_BACKUP_DIR/project.env" ]; then
    cp "$CURRENT_BACKUP_DIR/project.env" "$PROJECT_DIR/.env"
  fi
  if [ -f "$CURRENT_BACKUP_DIR/src.env" ]; then
    mkdir -p "$PROJECT_DIR/src"
    cp "$CURRENT_BACKUP_DIR/src.env" "$PROJECT_DIR/src/.env"
  fi

  "$PROJECT_DIR/start.sh" start
}

log "========== 版本更新开始 =========="
log "目标版本: $NEW_VERSION"

if ! command -v python3 >/dev/null 2>&1; then
  fail "未找到 python3，请先安装 Python 3.10+"
  exit 1
fi

CURRENT_VERSION="$(get_current_version)"
log "当前代码版本: $CURRENT_VERSION"

if [ "$CURRENT_VERSION" = "$NEW_VERSION" ] && [ "$FORCE" = false ]; then
  log "代码已经是 $NEW_VERSION，无需更新。使用 --force 强制重新部署。"
  exit 0
fi

PACKAGE_PATH="$(find_code_package)"
if [ -z "$PACKAGE_PATH" ]; then
  fail "未找到更新包，请使用 --package 指定"
  exit 1
fi

validate_update_package "$PACKAGE_PATH"

TEMP_EXTRACT="$(mktemp -d)"
trap 'rm -rf "$TEMP_EXTRACT"' EXIT
tar -tzf "$PACKAGE_PATH" >/dev/null
EXTRACTED_DIR="$(safe_extract_package "$PACKAGE_PATH" "$TEMP_EXTRACT")"
PACKAGE_VERSION="$(read_version_from_main "$EXTRACTED_DIR/src/main.py")"
log "更新包版本: $PACKAGE_VERSION"

stop_service
create_backup "$CURRENT_VERSION"

# ── 关键：迁移 scan/plan 必须在代码替换之前 ──
# 迁移工具 scan_html 需要读取旧项目 HTML 中的文本配置（login_notice 等），
# 代码替换后旧 HTML 不存在，这些文本配置会丢失。
# 本脚本只生成报告，不自动 apply；写入 runtime yaml 需人工确认后单独执行。

run_migration_plan

# 迁移完成后，替换代码文件
copy_versioned_files "$EXTRACTED_DIR"

# 同步 ui-branding.yaml 中的 app_version 与代码版本号
sync_yaml_version

if ! python3 -c "import fastapi, uvicorn, sqlalchemy, aiosqlite, cryptography, dotenv, httpx, openai, lancedb, pyarrow, numpy" 2>/dev/null; then
  warn "当前 Python 环境缺少依赖，请手动执行: python3 -m pip install -r requirements.txt"
fi

# Pi Agent 可选依赖检测（缺失不影响主应用，仅 Agent 模式不可用）
LOCAL_PI_BIN="$PROJECT_DIR/node_modules/.bin/pi"
if [ -x "$LOCAL_PI_BIN" ]; then
  log "Pi Agent CLI: $($LOCAL_PI_BIN --version 2>/dev/null) ($LOCAL_PI_BIN)"
elif command -v pi &>/dev/null; then
  warn "使用全局 pi CLI: $(pi --version 2>/dev/null) ($(command -v pi))；建议执行 npm install 使用项目本地 node_modules/.bin/pi"
else
  warn "pi CLI 未找到 — Agent 模式不可用"
fi
if ! command -v node &>/dev/null; then
  warn "Node.js 未找到 — Pi Agent Extension 不可用"
fi
if ! command -v npm &>/dev/null; then
  warn "npm 未找到 — 无法安装 Pi Agent 项目依赖"
fi

log "启动新版本服务..."
"$PROJECT_DIR/start.sh" start

log "等待服务健康检查..."
if wait_for_health; then
  RUNNING_VERSION="$(get_running_version)"
  log "========== 更新成功 =========="
  log "旧版本: $CURRENT_VERSION → 新版本: $RUNNING_VERSION"
  if [ -n "$CURRENT_BACKUP_DIR" ]; then
    log "备份位置: $CURRENT_BACKUP_DIR"
  fi
  if [ -n "$MIGRATE_REPORT" ] && [ -f "$MIGRATE_REPORT" ]; then
    log "迁移报告: $MIGRATE_REPORT"
  fi
  if [ -f "$EXTRACTED_DIR/update.sh" ]; then
    cp "$EXTRACTED_DIR/update.sh" "$PROJECT_DIR/update.sh"
    chmod +x "$PROJECT_DIR/update.sh"
    log "update.sh 已更新为新版本"
  fi
  exit 0
fi

fail "健康检查失败，服务未正常启动"
if restore_backup && wait_for_health; then
  ROLLBACK_VERSION="$(get_running_version)"
  log "========== 回滚成功 =========="
  log "回滚到版本: $ROLLBACK_VERSION"
  exit 2
fi

fail "回滚后服务也无法启动 — 请手动检查"
exit 3
