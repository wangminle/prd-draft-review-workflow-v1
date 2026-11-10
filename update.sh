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
set -E

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="${RUNTIME_ROOT:-$PROJECT_DIR/runtime}"
PID_FILE="$RUNTIME_DIR/server.pid"
BACKUP_DIR="$RUNTIME_DIR/update_backups"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-15}"
HEALTH_RETRIES="${HEALTH_RETRIES:-5}"
NEW_VERSION="0.3.19"

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

# BUG-211：备份完成后任何一步失败都必须回滚，不能留下“新版代码 + 停机”。
UPDATE_STARTED=false
SERVICE_STOPPED=false
ROLLBACK_IN_PROGRESS=false
handle_update_error() {
  local code=$?
  if [ "$UPDATE_STARTED" = true ] && [ "$ROLLBACK_IN_PROGRESS" != true ]; then
    ROLLBACK_IN_PROGRESS=true
    trap - ERR
    fail "更新过程中发生错误（exit=$code），开始自动回滚"
    if restore_backup && wait_for_health; then
      ROLLBACK_VERSION="$(get_running_version)"
      log "========== 回滚成功 =========="
      log "回滚到版本: $ROLLBACK_VERSION"
      exit 2
    fi
    fail "回滚后服务也无法启动 — 请手动检查"
    exit 3
  elif [ "$SERVICE_STOPPED" = true ] && [ "$UPDATE_STARTED" != true ]; then
    trap - ERR
    warn "更新前备份或准备阶段失败（exit=$code），旧代码未修改，正在重新启动现有服务..."
    if "$PROJECT_DIR/start.sh" start; then
      SERVICE_STOPPED=false
    else
      fail "旧服务恢复启动失败 — 请手动检查"
    fi
  fi
  exit "$code"
}
trap 'handle_update_error' ERR

read_version_from_main() {
  local project_dir="$1"
  if [ ! -d "$project_dir" ]; then
    echo "unknown"
    return
  fi
  # 唯一事实来源：根目录 VERSION 纯文本文件；回退到 src/app/version.py、src/main.py 兼容旧结构。
  python3 - "$project_dir" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
vf = root / "VERSION"
if vf.exists():
    v = vf.read_text(encoding="utf-8").strip()
    if v:
        print(v); sys.exit(0)
for candidate in (root / "src/app/version.py", root / "src/main.py"):
    if not candidate.exists():
        continue
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', candidate.read_text(encoding="utf-8"))
    if m:
        print(m.group(1)); break
else:
    print("unknown")
PY
}

get_current_version() {
  read_version_from_main "$PROJECT_DIR"
}

get_server_port() {
  local port="${SERVER_PORT:-}"
  if [ -z "$port" ]; then
    PYTHONPATH="$PROJECT_DIR/src" python3 - "$PROJECT_DIR" <<'PY'
import sys
from pathlib import Path
from app.env_file import ensure_canonical_env

_path, warnings = ensure_canonical_env(Path(sys.argv[1]))
for w in warnings:
    print(f"[WARN] {w}", file=sys.stderr)
PY
    if [ -f "$PROJECT_DIR/.env" ]; then
      local value
      value=$(python3 - "$PROJECT_DIR/.env" <<'PY'
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

  # FS-07：拒绝符号链接及设备/管道等特殊条目，避免解压时写到包外。
  local verbose_listing
  verbose_listing="$(tar -tvzf "$package" 2>/dev/null || true)"
  if echo "$verbose_listing" | grep -Eq '^[lhbcps]'; then
    fail "更新包包含符号链接或特殊文件条目，拒绝更新"
    return 1
  fi

  if echo "$listing" | grep -Eq '(^|/)runtime/(data|uploads|logs|results|storage|vector)(/|$)'; then
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

  # BUG-211：旧版本可能缺少可选受管文件（如 CLAUDE.md），只打包实际存在的条目。
  local backup_items=""
  for item in src tools tests docs skills VERSION start.sh update.sh requirements.txt pyproject.toml package.json package-lock.json .env.example README.md CLAUDE.md LICENSE; do
    [ -e "$PROJECT_DIR/$item" ] && backup_items="$backup_items $item"
  done
  if [ -z "$backup_items" ]; then
    fail "没有可备份的受管文件，终止更新"
    return 1
  fi

  if ! tar -czf "$CURRENT_BACKUP_DIR/code.tar.gz" \
    --exclude='runtime' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.tar.gz' \
    -C "$PROJECT_DIR" $backup_items; then
    fail "代码备份失败，终止更新（避免无回滚点）"
    return 1
  fi

  if [ -d "$RUNTIME_DIR/config" ]; then
    if ! cp -R "$RUNTIME_DIR/config" "$CURRENT_BACKUP_DIR/runtime_config"; then
      fail "runtime/config 备份失败，终止更新"
      return 1
    fi
  fi
  if [ -d "$RUNTIME_DIR/assets" ]; then
    if ! cp -R "$RUNTIME_DIR/assets" "$CURRENT_BACKUP_DIR/runtime_assets"; then
      fail "runtime/assets 备份失败，终止更新"
      return 1
    fi
  fi
  if [ -f "$PROJECT_DIR/.env" ]; then
    if ! cp "$PROJECT_DIR/.env" "$CURRENT_BACKUP_DIR/project.env"; then
      fail "项目 .env 备份失败，终止更新"
      return 1
    fi
  fi
  if [ -f "$PROJECT_DIR/src/.env" ]; then
    if ! cp "$PROJECT_DIR/src/.env" "$CURRENT_BACKUP_DIR/src.env"; then
      fail "src/.env 备份失败，终止更新"
      return 1
    fi
  fi

  log "备份完成: $CURRENT_BACKUP_DIR"
}

copy_versioned_files() {
  local extracted_dir="$1"
  local stage_dir
  stage_dir="$(mktemp -d "$PROJECT_DIR/.update-stage.XXXXXX")"
  local stage_items=""
  local stage_files=""

  log "更新代码文件..."
  log "暂存新版本代码..."
  for item in src tools tests docs skills; do
    if [ -d "$extracted_dir/$item" ]; then
      if ! cp -R "$extracted_dir/$item" "$stage_dir/$item"; then
        fail "暂存 $item/ 失败，旧版本保持不变"
        rm -rf "$stage_dir"
        return 1
      fi
      stage_items="$stage_items $item"
    fi
  done

  for file in VERSION start.sh requirements.txt pyproject.toml package.json package-lock.json .env.example README.md CLAUDE.md LICENSE; do
    if [ -f "$extracted_dir/$file" ]; then
      if ! cp "$extracted_dir/$file" "$stage_dir/$file"; then
        fail "暂存 $file 失败，旧版本保持不变"
        rm -rf "$stage_dir"
        return 1
      fi
      stage_files="$stage_files $file"
    fi
  done

  log "原子替换代码目录..."
  local txn_dir="$stage_dir/.txn"
  mkdir -p "$txn_dir"
  local moved_items=""
  local moved_files=""

  # 第一阶段：把所有旧目录/旧文件移入事务目录；任一失败则整体还原。
  for item in src tools tests docs skills; do
    [ -e "$stage_dir/$item" ] || continue
    if [ -e "$PROJECT_DIR/$item" ]; then
      if ! mv "$PROJECT_DIR/$item" "$txn_dir/old-$item"; then
        fail "移出旧 $item/ 失败，开始还原"
        for done_item in $moved_items; do
          [ -e "$txn_dir/old-$done_item" ] && mv "$txn_dir/old-$done_item" "$PROJECT_DIR/$done_item"
        done
        rm -rf "$stage_dir"
        return 1
      fi
      moved_items="$moved_items $item"
    fi
  done
  for file in VERSION start.sh requirements.txt pyproject.toml package.json package-lock.json .env.example README.md CLAUDE.md LICENSE; do
    [ -f "$stage_dir/$file" ] || continue
    if [ -f "$PROJECT_DIR/$file" ]; then
      if ! mv "$PROJECT_DIR/$file" "$txn_dir/old-$file"; then
        fail "移出旧 $file 失败，开始还原"
        for done_item in $moved_items; do
          [ -e "$txn_dir/old-$done_item" ] && mv "$txn_dir/old-$done_item" "$PROJECT_DIR/$done_item"
        done
        for done_file in $moved_files; do
          [ -e "$txn_dir/old-$done_file" ] && mv "$txn_dir/old-$done_file" "$PROJECT_DIR/$done_file"
        done
        rm -rf "$stage_dir"
        return 1
      fi
      moved_files="$moved_files $file"
    fi
  done

  # 第二阶段：把新目录/新文件移入；任一失败则删除已放入的新内容并还原全部旧内容。
  for item in src tools tests docs skills; do
    [ -e "$stage_dir/$item" ] || continue
    if ! mv "$stage_dir/$item" "$PROJECT_DIR/$item"; then
      fail "替换 $item/ 失败，开始整体还原"
      for done_item in $stage_items; do
        [ -e "$PROJECT_DIR/$done_item" ] && rm -rf "$PROJECT_DIR/$done_item"
      done
      for done_item in $moved_items; do
        [ -e "$txn_dir/old-$done_item" ] && mv "$txn_dir/old-$done_item" "$PROJECT_DIR/$done_item"
      done
      for done_file in $moved_files; do
        [ -e "$txn_dir/old-$done_file" ] && mv "$txn_dir/old-$done_file" "$PROJECT_DIR/$done_file"
      done
      rm -rf "$stage_dir"
      return 1
    fi
    log "  更新 $item/"
  done
  for file in VERSION start.sh requirements.txt pyproject.toml package.json package-lock.json .env.example README.md CLAUDE.md LICENSE; do
    [ -f "$stage_dir/$file" ] || continue
    if ! mv -f "$stage_dir/$file" "$PROJECT_DIR/$file"; then
      fail "替换 $file 失败，开始整体还原"
      for done_item in $stage_items; do
        [ -e "$PROJECT_DIR/$done_item" ] && rm -rf "$PROJECT_DIR/$done_item"
      done
      for done_file in $stage_files; do
        [ -e "$PROJECT_DIR/$done_file" ] && rm -f "$PROJECT_DIR/$done_file"
      done
      for done_item in $moved_items; do
        [ -e "$txn_dir/old-$done_item" ] && mv "$txn_dir/old-$done_item" "$PROJECT_DIR/$done_item"
      done
      for done_file in $moved_files; do
        [ -e "$txn_dir/old-$done_file" ] && mv "$txn_dir/old-$done_file" "$PROJECT_DIR/$done_file"
      done
      rm -rf "$stage_dir"
      return 1
    fi
    log "  更新 $file"
  done
  rm -rf "$stage_dir"

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
  # 版本号以包内 src/main.py 实际读出的 PACKAGE_VERSION 为准，避免 NEW_VERSION 忘记同步时写错
  local result
  result=$(python3 - "$yaml_path" "${PACKAGE_VERSION:-$NEW_VERSION}" <<'PY'
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
  ROLLBACK_IN_PROGRESS=true
  trap - ERR
  if [ "$ROLLBACK_ON_FAILURE" != true ] || [ "$SKIP_BACKUP" = true ] || [ ! -d "$CURRENT_BACKUP_DIR" ]; then
    fail "无法回滚（未创建备份或回滚已禁用）— 请手动排查"
    return 1
  fi

  log "自动回滚到旧版本..."
  "$PROJECT_DIR/start.sh" stop 2>/dev/null || true

  if [ ! -f "$CURRENT_BACKUP_DIR/code.tar.gz" ]; then
    fail "备份缺少 code.tar.gz，无法回滚"
    return 1
  fi
  # BUG-211：先解包到临时目录，解包失败时现有代码保持不动。
  local code_stage code_txn
  code_stage="$(mktemp -d "$PROJECT_DIR/.restore-code.XXXXXX")"
  if ! tar -xzf "$CURRENT_BACKUP_DIR/code.tar.gz" -C "$code_stage"; then
    fail "代码备份解包失败，现有代码保持不变"
    rm -rf "$code_stage"
    return 1
  fi
  if [ ! -d "$code_stage/src" ]; then
    fail "代码备份不完整（缺少 src/），拒绝回滚覆盖现有代码"
    rm -rf "$code_stage"
    return 1
  fi
  code_txn="$(mktemp -d "$PROJECT_DIR/.restore-txn.XXXXXX")"
  local restored=""
  local placed=""
  for item in src tools tests docs skills VERSION start.sh update.sh requirements.txt pyproject.toml package.json package-lock.json .env.example README.md CLAUDE.md LICENSE; do
    if [ -e "$PROJECT_DIR/$item" ]; then
      if ! mv "$PROJECT_DIR/$item" "$code_txn/old-$item"; then
        fail "回滚移出旧 $item 失败，正在整体还原已处理条目并保留恢复材料"
        for done_item in $placed; do
          rm -rf "$code_stage/$done_item" 2>/dev/null || true
          mv "$PROJECT_DIR/$done_item" "$code_stage/$done_item" 2>/dev/null || rm -rf "$PROJECT_DIR/$done_item"
        done
        for done_item in $restored; do
          if [ -e "$code_txn/old-$done_item" ]; then
            cp -R "$code_txn/old-$done_item" "$code_txn/recovery-$done_item" 2>/dev/null || true
            mv "$code_txn/old-$done_item" "$PROJECT_DIR/$done_item" 2>/dev/null || true
            if [ -e "$code_txn/recovery-$done_item" ] && [ ! -e "$code_txn/old-$done_item" ]; then
              mv "$code_txn/recovery-$done_item" "$code_txn/old-$done_item" 2>/dev/null || true
            fi
          fi
        done
        warn "已保留恢复副本目录: $code_txn $code_stage"
        return 1
      fi
      restored="$restored $item"
    fi
    if [ ! -e "$code_stage/$item" ]; then
      # BUG-211 / FS-06：旧备份没有的受管条目已暂存至 code_txn，待全部回滚成功后再随事务目录清理。
      continue
    fi
    if ! mv "$code_stage/$item" "$PROJECT_DIR/$item"; then
      fail "回滚放入 $item 失败，正在整体还原现有代码并保留恢复材料"
      for done_item in $placed; do
        rm -rf "$code_stage/$done_item" 2>/dev/null || true
        mv "$PROJECT_DIR/$done_item" "$code_stage/$done_item" 2>/dev/null || rm -rf "$PROJECT_DIR/$done_item"
      done
      for done_item in $restored; do
        if [ -e "$code_txn/old-$done_item" ]; then
          cp -R "$code_txn/old-$done_item" "$code_txn/recovery-$done_item" 2>/dev/null || true
          mv "$code_txn/old-$done_item" "$PROJECT_DIR/$done_item" 2>/dev/null || true
          if [ -e "$code_txn/recovery-$done_item" ] && [ ! -e "$code_txn/old-$done_item" ]; then
            mv "$code_txn/recovery-$done_item" "$code_txn/old-$done_item" 2>/dev/null || true
          fi
        fi
      done
      warn "已保留恢复副本目录: $code_txn $code_stage"
      return 1
    fi
    placed="$placed $item"
  done
  rm -rf "$code_stage" "$code_txn"

  for asset in config assets; do
    backup_dir="$CURRENT_BACKUP_DIR/runtime_$asset"
    [ -d "$backup_dir" ] || continue
    restore_tmp="$(mktemp -d "$RUNTIME_DIR/.restore-$asset.XXXXXX")"
    if ! cp -R "$backup_dir" "$restore_tmp/$asset"; then
      fail "恢复 runtime/$asset 失败：备份复制不完整，保留现有目录"
      rm -rf "$restore_tmp"
      return 1
    fi
    old_dir="$RUNTIME_DIR/.old-$asset.$$"
    if [ -e "$RUNTIME_DIR/$asset" ] && ! mv "$RUNTIME_DIR/$asset" "$old_dir"; then
      fail "恢复 runtime/$asset 失败：无法移走现有目录"
      rm -rf "$restore_tmp"
      return 1
    fi
    if ! mv "$restore_tmp/$asset" "$RUNTIME_DIR/$asset"; then
      # 还原刚移走的现有目录，避免配置丢失
      [ -e "$old_dir" ] && mv "$old_dir" "$RUNTIME_DIR/$asset"
      fail "恢复 runtime/$asset 失败：无法放入备份目录"
      rm -rf "$restore_tmp"
      return 1
    fi
    rm -rf "$old_dir" "$restore_tmp"
  done

  if [ -f "$CURRENT_BACKUP_DIR/project.env" ]; then
    local env_tmp
    env_tmp="$(mktemp "$PROJECT_DIR/.restore-env.XXXXXX")"
    if ! cp "$CURRENT_BACKUP_DIR/project.env" "$env_tmp" || ! cmp -s "$CURRENT_BACKUP_DIR/project.env" "$env_tmp"; then
      rm -f "$env_tmp"
      fail "恢复项目 .env 失败：临时文件内容不完整，正式文件未改动"
      return 1
    fi
    chmod 600 "$env_tmp" 2>/dev/null || true
    if ! mv "$env_tmp" "$PROJECT_DIR/.env"; then
      rm -f "$env_tmp"
      fail "恢复项目 .env 失败：无法替换正式文件"
      return 1
    fi
  fi
  if [ -f "$CURRENT_BACKUP_DIR/src.env" ]; then
    mkdir -p "$PROJECT_DIR/src"
    local src_env_tmp
    src_env_tmp="$(mktemp "$PROJECT_DIR/src/.restore-env.XXXXXX")"
    if ! cp "$CURRENT_BACKUP_DIR/src.env" "$src_env_tmp" || ! cmp -s "$CURRENT_BACKUP_DIR/src.env" "$src_env_tmp"; then
      rm -f "$src_env_tmp"
      fail "恢复 src/.env 失败：临时文件内容不完整，正式文件未改动"
      return 1
    fi
    chmod 600 "$src_env_tmp" 2>/dev/null || true
    if ! mv "$src_env_tmp" "$PROJECT_DIR/src/.env"; then
      rm -f "$src_env_tmp"
      fail "恢复 src/.env 失败：无法替换正式文件"
      return 1
    fi
  fi

  if ! "$PROJECT_DIR/start.sh" start; then
    fail "回滚后启动命令失败"
    return 1
  fi
  return 0
}

log "========== 版本更新开始 =========="
log "回退目标版本(包内读取失败时使用): $NEW_VERSION"

if ! command -v python3 >/dev/null 2>&1; then
  fail "未找到 python3，请先安装 Python 3.10+"
  exit 1
fi

CURRENT_VERSION="$(get_current_version)"
log "当前代码版本: $CURRENT_VERSION"

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
PACKAGE_VERSION="$(read_version_from_main "$EXTRACTED_DIR")"
log "更新包版本: $PACKAGE_VERSION"

# 先解包读取实际版本，再与当前版本比较（避免因 NEW_VERSION 常量未同步而跳过真实更新）
if [ "$CURRENT_VERSION" = "$PACKAGE_VERSION" ] && [ "$FORCE" = false ]; then
  log "当前版本 $CURRENT_VERSION 与更新包版本 $PACKAGE_VERSION 相同，无需更新。使用 --force 强制重新部署。"
  exit 0
fi

stop_service
SERVICE_STOPPED=true
create_backup "$CURRENT_VERSION"
UPDATE_STARTED=true

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
if ! "$PROJECT_DIR/start.sh" start; then
  fail "新版本启动命令返回非零，立即回滚"
  if restore_backup && wait_for_health; then
    ROLLBACK_VERSION="$(get_running_version)"
    log "========== 回滚成功 =========="
    log "回滚到版本: $ROLLBACK_VERSION"
    exit 2
  fi
  fail "回滚后服务也无法启动 — 请手动检查"
  exit 3
fi

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
