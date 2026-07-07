#!/bin/bash
# AI产品需求初审 — 代码-配置打包脚本
# 用法：./package.sh [选项]
#
# 生成代码-配置分发包，供目标服务器手动解压首次部署，或通过 ./update.sh 更新。
#
# 默认输出 zip 格式；--format tar.gz 产出可被 update.sh 自动识别的包；--format both 同时产出。
#
# 核心原则（与 update.sh / CLAUDE.md 对齐）：
#   - 只打包代码与配置模板，绝不包含 runtime 业务数据（数据库、上传文件、日志、结果）
#   - 不含密钥文件 .env（目标服务器自行配置），仅附带 .env.example 模板
#   - 不含 node_modules（151M+，目标服务器执行 npm install 自行安装）
#   - 不含 .git、.venv、__pycache__、POC/eval 实验目录等非生产产物
#   - 打包后自检：复用 update.sh validate_update_package 的规则，
#     确保产出的包内容可信（含 src/main.py、无危险路径、无业务数据/密钥/依赖目录）
#
# 与 update.sh 的关系：
#   update.sh 自动查找 *code-config*.tar.gz 并执行 备份→校验→替换→健康检查→回滚。
#   走自动更新流程请用 --format tar.gz；zip 适用于手动解压首次部署或跨平台分发。
#   两种格式内容清单完全一致，仅压缩格式不同。

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/dist}"

FORMAT="${FORMAT:-zip}"
SHOW_LIST=false
BUILD_NO="${BUILD_NO:-$(date +%Y%m%d%H%M)}"

while [ $# -gt 0 ]; do
  case "$1" in
    --format)
      shift
      [ -z "${1:-}" ] && { echo "[FAIL] --format 需要参数 (zip|tar.gz|both)"; exit 1; }
      case "$1" in
        zip|tar.gz|both) FORMAT="$1" ;;
        *) echo "[FAIL] --format 仅支持 zip|tar.gz|both"; exit 1 ;;
      esac
      ;;
    --output)
      shift
      [ -z "${1:-}" ] && { echo "[FAIL] --output 需要路径参数"; exit 1; }
      OUTPUT_DIR="$1"
      ;;
    --build-no)
      shift
      [ -z "${1:-}" ] && { echo "[FAIL] --build-no 需要参数"; exit 1; }
      BUILD_NO="$1"
      ;;
    --list)
      SHOW_LIST=true
      ;;
    -h|--help)
      cat <<'EOF'
用法: ./package.sh [选项]

默认生成 zip 分发包；--format tar.gz 产出可被 update.sh 自动识别的包。

选项:
  --format FMT     输出格式：zip（默认）| tar.gz | both
  --output PATH    输出目录，默认 ./dist
  --build-no N     构建号，默认当前时间戳 YYYYMMDDHHMM
  --list           打包后打印各包内文件清单
  -h, --help       显示帮助

环境变量:
  FORMAT           同 --format（默认 zip）
  OUTPUT_DIR       同 --output
  BUILD_NO         同 --build-no

产物命名: prd-draft-review-workflow-v1-code-config-v{版本}-build{构建号}.{zip|tar.gz}

说明:
  - update.sh 自动查找 *code-config*.tar.gz；走自动备份/回滚更新流程请用 --format tar.gz
  - zip 适用于手动解压首次部署或跨平台（含 Windows）分发
EOF
      exit 0
      ;;
    *)
      echo "[FAIL] 未知参数: $1"
      exit 1
      ;;
  esac
  shift
done

log() { echo "[PACKAGE] $1"; }
warn() { echo "[WARN] $1"; }
fail() { echo "[FAIL] $1"; }

# ── 从 src/main.py 读取版本号（与 update.sh read_version_from_main 同源）──
VERSION="$(python3 - "$PROJECT_DIR/src/main.py" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r'version\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "unknown")
PY
)"

mkdir -p "$OUTPUT_DIR"

# ── 必要前置文件校验 ──
if [ ! -f "$PROJECT_DIR/src/main.py" ]; then
  fail "缺少 src/main.py，无法打包"
  exit 1
fi
if [ ! -f "$PROJECT_DIR/start.sh" ]; then
  warn "缺少 start.sh，包内将不含启动脚本（update.sh 仅给出 warning）"
fi

# ── 待打包成员（相对 PROJECT_DIR 的路径）──
# 目录对齐 update.sh copy_versioned_files；package.json 仅供首次部署 npm install。
MEMBERS=(
  src tools tests docs skills
  start.sh update.sh
  requirements.txt pyproject.toml package.json
  README.md CLAUDE.md LICENSE
  .env.example
  runtime/config/ui-branding.example.yaml
)

FINAL_MEMBERS=()
for m in "${MEMBERS[@]}"; do
  if [ -e "$PROJECT_DIR/$m" ]; then
    FINAL_MEMBERS+=("$m")
  else
    warn "跳过不存在的成员: $m"
  fi
done

# ── 打包：zip（用 Python zipfile，而非 Info-ZIP CLI）──
# 原因：macOS 自带的 Info-ZIP 不支持 -UN=u（Apple 编译版禁用了 Unicode 选项），
# 无法给文件名设 UTF-8 标志位，导致 zipinfo 显示乱码、Windows 解压中文乱码。
# Python zipfile 对非 ASCII 文件名自动设置 UTF-8 标志位（bit 11），
# 跨平台（Linux/macOS/Windows）解压均能正确还原中文文件名。
build_zip() {
  local out="$1"
  rm -f "$out"
  python3 - "$PROJECT_DIR" "$out" "${FINAL_MEMBERS[@]}" <<'PY'
import os, sys, zipfile
from pathlib import Path

project = Path(sys.argv[1])
out = Path(sys.argv[2])
members = sys.argv[3:]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".swp", ".swo")

def excluded(p: Path) -> bool:
    name = p.name
    if p.is_dir() and name in EXCLUDE_DIRS:
        return True
    if name == ".DS_Store":
        return True
    if name.endswith(EXCLUDE_SUFFIX):
        return True
    if name == ".env":  # 裸 .env 密钥；.env.example 不受影响（name 不同）
        return True
    return False

count = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for m in members:
        base = project / m
        if not base.exists():
            continue
        if base.is_file():
            if not excluded(base):
                zf.write(base, m)
                count += 1
            continue
        for root, dirs, files in os.walk(base):
            # 原地裁剪 dirs，避免递归进入被排除的目录
            dirs[:] = [d for d in dirs if not excluded(Path(root) / d)]
            for f in files:
                fp = Path(root) / f
                if excluded(fp):
                    continue
                arc = fp.relative_to(project).as_posix()
                zf.write(fp, arc)
                count += 1
print(f"[zip] {count} 个文件 -> {out}")
PY
}

# ── 打包：tar.gz（GNU tar / bsdtar 通用）──
# COPYFILE_DISABLE=1：禁用 macOS bsdtar 生成 ._ AppleDouble 资源叉文件，
# 否则包内会混入 ._CLAUDE.md 这类垃圾文件污染 Linux 部署目录。
# --exclude='._*' 双保险，防止源目录本身残留 AppleDouble 文件。
build_targz() {
  local out="$1"
  rm -f "$out"
  COPYFILE_DISABLE=1 tar -czf "$out" \
    -C "$PROJECT_DIR" \
    --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='*.pyo' \
    --exclude='.DS_Store' \
    --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' \
    --exclude='*.swp' --exclude='*.swo' \
    --exclude='src/.env' \
    --exclude='._*' \
    "${FINAL_MEMBERS[@]}"
}

# ── 自检：复用 update.sh validate_update_package 的规则 ──
# 入参：$1 包路径  $2 包内文件清单（每行一个路径，由 zipinfo -1 或 tar -tzf 产生）
self_check() {
  local pkg="$1"
  local listing="$2"
  local check_fail=0

  if echo "$listing" | grep -Eq '(^|/)\.\.(/|$)|^/'; then
    fail "自检失败：包内含不安全路径（绝对路径或 ..）"; check_fail=1
  fi
  if echo "$listing" | grep -Eq '(^|/)runtime/(data|uploads|logs|results|storage|vector)(/|$)'; then
    fail "自检失败：包内含 runtime 业务数据目录"; check_fail=1
  fi
  # 允许 .env.example；禁止任意层级的裸 .env（如 .env、src/.env）
  if echo "$listing" | grep -Eq '(^|/)\.env($|/)'; then
    fail "自检失败：包内包含裸 .env（可能含密钥）；仅允许 .env.example"; check_fail=1
  fi
  # 禁止 macOS AppleDouble 资源叉文件（._*），避免污染 Linux 部署目录
  if echo "$listing" | grep -Eq '(^|/)\._'; then
    fail "自检失败：包内含 macOS AppleDouble 文件（._*）；tar 打包请设 COPYFILE_DISABLE=1"; check_fail=1
  fi
  if echo "$listing" | grep -Eq '(^|/)node_modules(/|$)'; then
    fail "自检失败：包内含 node_modules"; check_fail=1
  fi
  if echo "$listing" | grep -Eq '(^|/)\.git(/|$)'; then
    fail "自检失败：包内含 .git"; check_fail=1
  fi
  if ! echo "$listing" | grep -Eq '(^|/)src/main\.py$'; then
    fail "自检失败：缺少 src/main.py"; check_fail=1
  fi

  if [ "$check_fail" -ne 0 ]; then
    rm -f "$pkg"
    fail "自检未通过，已删除 $pkg"
    return 1
  fi
  log "自检通过：含 src/main.py，无密钥/业务数据/缓存/依赖目录"
  return 0
}

# ── 主流程 ──
case "$FORMAT" in
  zip)    FORMATS=(zip) ;;
  tar.gz) FORMATS=(tar.gz) ;;
  both)   FORMATS=(zip tar.gz) ;;
esac

log "项目目录: $PROJECT_DIR"
log "代码版本: $VERSION"
log "构建号:   $BUILD_NO"
log "输出目录: $OUTPUT_DIR"
log "输出格式: ${FORMATS[*]}"

PACKAGES=()
for fmt in "${FORMATS[@]}"; do
  PKG_NAME="prd-draft-review-workflow-v1-code-config-v${VERSION}-build${BUILD_NO}.${fmt}"
  PKG_PATH="$OUTPUT_DIR/$PKG_NAME"

  log "----- 打包 ${fmt} -----"
  log "产物: $PKG_PATH"
  case "$fmt" in
    zip)    build_zip "$PKG_PATH" ;;
    tar.gz) build_targz "$PKG_PATH" ;;
  esac

  case "$fmt" in
    zip)    LISTING="$(zipinfo -1 "$PKG_PATH")" ;;
    tar.gz) LISTING="$(tar -tzf "$PKG_PATH")" ;;
  esac

  self_check "$PKG_PATH" "$LISTING" || exit 1
  PACKAGES+=("$PKG_PATH:$fmt")
done

# ── 摘要 ──
log "========== 打包成功 =========="
for entry in "${PACKAGES[@]}"; do
  p="${entry%:*}"
  fmt="${entry##*:}"
  case "$p" in
    *.zip)    fcount="$(zipinfo -1 "$p" | wc -l | tr -d ' ')" ;;
    *.tar.gz) fcount="$(tar -tzf "$p" | wc -l | tr -d ' ')" ;;
  esac
  size="$(du -h "$p" | cut -f1)"
  log "[$fmt] $p  (${fcount} 文件, ${size})"
done
log ""
log "部署方式（目标服务器）："
log "  zip    : unzip *.zip -d <目录>，按 docs/4-deployment/2026-07-07-打包与部署指南.md 首次部署"
log "  tar.gz : 放到项目根目录执行 ./update.sh（自动备份/校验/回滚）；或 tar -xzf 手动首次部署"

if [ "$SHOW_LIST" = true ]; then
  for entry in "${PACKAGES[@]}"; do
    p="${entry%:*}"
    fmt="${entry##*:}"
    echo ""
    echo "===== [$fmt] $p 包内清单 ====="
    case "$p" in
      *.zip)    zipinfo -1 "$p" ;;
      *.tar.gz) tar -tzf "$p" ;;
    esac
  done
fi
