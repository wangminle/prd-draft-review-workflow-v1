"""品牌迁移工具 — 从旧项目代码和 runtime 扫描品牌配置并生成 ui-branding.yaml。

用法：
    python3 tools/migrate_branding.py \
        --legacy-code-dir /path/to/old/project/src/static \
        --legacy-runtime-dir /path/to/old/runtime \
        --target-runtime-dir ./runtime

核心行为：
    - 从旧代码扫描 HTML title、登录页标题/副标题/提示、顶栏标题、favicon、Logo
    - 从旧代码扫描 CSS 主题色变量
    - 从旧 runtime 优先读取已有 ui-branding.yaml 和 branding 资产
    - 生成 runtime/config/ui-branding.yaml（高置信自动写入，低置信进报告）
    - 复制资产到 runtime/assets/branding/
    - 生成 runtime/config/ui-branding.scan-report.md
    - 不覆盖已有配置（除非 --force）
    - 不写入绝对路径或外部 URL
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ── 扫描置信度 ──
CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"


# ── HTML 扫描 ──


def scan_html(html_path: Path) -> dict:
    """从 index.html 扫描品牌元素，返回 {field: (value, confidence)} 映射。"""
    findings: dict[str, tuple[str, str]] = {}

    if not html_path.exists():
        return findings

    text = html_path.read_text(encoding="utf-8")

    # <title>
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.DOTALL)
    if m and m.group(1).strip():
        title = m.group(1).strip()
        findings["app_title"] = (title, CONF_HIGH)
        findings["login_title"] = (title, CONF_MEDIUM)
        findings["topbar_title"] = (title, CONF_MEDIUM)

    # 登录页 brand-title（h1 class="brand-title"）
    m = re.search(r'<h1[^>]*class="brand-title"[^>]*>(.*?)</h1>', text, re.DOTALL)
    if m and m.group(1).strip():
        findings["login_title"] = (m.group(1).strip(), CONF_HIGH)

    # 登录页 brand-desc（p class="brand-desc"）
    m = re.search(r'<p[^>]*class="brand-desc"[^>]*>(.*?)</p>', text, re.DOTALL)
    if m and m.group(1).strip():
        findings["login_subtitle"] = (m.group(1).strip(), CONF_HIGH)

    # 登录页提示框（auth-login-notice）
    m = re.search(r'<div[^>]*class="auth-login-notice"[^>]*>(.*?)</div>', text, re.DOTALL)
    if m:
        notice_html = m.group(1)
        notice_lines = []
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", notice_html, re.DOTALL):
            line = re.sub(r"<[^>]+>", "", pm.group(1)).strip()
            if line:
                notice_lines.append(line)
        if notice_lines:
            findings["login_notice"] = ("\n".join(notice_lines), CONF_MEDIUM)

    # 顶栏 topbar-title（span class="topbar-title"）
    topbar_titles = []
    for m in re.finditer(r'<span[^>]*class="topbar-title"[^>]*>(.*?)</span>', text, re.DOTALL):
        val = m.group(1).strip()
        if val and val not in topbar_titles:
            topbar_titles.append(val)
    if topbar_titles:
        findings["topbar_title"] = (topbar_titles[0], CONF_HIGH)
        # 如果有第二个不同的标题，可能是审查页标题
        if len(topbar_titles) > 1 and topbar_titles[1] != topbar_titles[0]:
            findings["review_workspace_label"] = (topbar_titles[1], CONF_HIGH)
        else:
            findings["review_workspace_label"] = (topbar_titles[0], CONF_LOW)

    # 顶栏审查工作台链接（go-review button text）
    m = re.search(r'<button[^>]*id="go-review"[^>]*>(.*?)</button>', text, re.DOTALL)
    if m and m.group(1).strip():
        findings["review_workspace_label"] = (m.group(1).strip(), CONF_HIGH)

    # 管理后台标签（go-admin button text）
    m = re.search(r'<button[^>]*id="go-admin"[^>]*>(.*?)</button>', text, re.DOTALL)
    if m and m.group(1).strip():
        findings["admin_label"] = (m.group(1).strip(), CONF_HIGH)

    # favicon 引用
    m = re.search(r'<link[^>]*rel="icon"[^>]*href="([^"]+)"', text)
    if m:
        favicon_href = m.group(1)
        findings["favicon_file"] = (favicon_href, CONF_HIGH)

    # theme-color meta
    m = re.search(r'<meta[^>]*name="theme-color"[^>]*content="([^"]+)"', text)
    if m:
        findings["theme_primary_meta"] = (m.group(1), CONF_HIGH)

    # SVG brand-mark 中的 fill 色
    svg_fills = []
    for m in re.finditer(r'<svg[^>]*>.*?<rect[^>]*fill="([^"#]+)"', text, re.DOTALL):
        if m.group(1) and not m.group(1).startswith("var("):
            svg_fills.append(m.group(1))
    if svg_fills:
        findings["theme_primary_svg"] = (svg_fills[0], CONF_MEDIUM)

    return findings


# ── CSS 扫描 ──


def scan_css(css_path: Path) -> dict:
    """从 main.css 扫描主题色变量，返回 {field: (value, confidence)} 映射。"""
    findings: dict[str, tuple[str, str]] = {}

    if not css_path.exists():
        return findings

    text = css_path.read_text(encoding="utf-8")

    # --color-brand: var(--xxx) or direct hex
    m = re.search(r"--color-brand:\s*([^;]+);", text)
    if m:
        brand_val = m.group(1).strip()
        if brand_val.startswith("var("):
            # 解析引用的变量名
            ref = re.search(r"var\(([^)]+)\)", brand_val)
            if ref:
                ref_var = ref.group(1)
                m2 = re.search(rf"{ref_var}:\s*([^;]+);", text)
                if m2:
                    findings["theme_primary"] = (m2.group(1).strip(), CONF_HIGH)
        elif brand_val.startswith("#"):
            findings["theme_primary"] = (brand_val, CONF_HIGH)

    # --color-brand-hover
    m = re.search(r"--color-brand-hover:\s*([^;]+);", text)
    if m:
        hover_val = m.group(1).strip()
        if hover_val.startswith("var("):
            ref = re.search(r"var\(([^)]+)\)", hover_val)
            if ref:
                m2 = re.search(rf"{ref.group(1)}:\s*([^;]+);", text)
                if m2:
                    findings["theme_primary_hover"] = (m2.group(1).strip(), CONF_HIGH)
        elif hover_val.startswith("#"):
            findings["theme_primary_hover"] = (hover_val, CONF_HIGH)

    # 登录页背景渐变
    m = re.search(r"background:\s*linear-gradient\([^)]*\)", text)
    if m:
        gradient = m.group(0)
        colors = re.findall(r"#([0-9a-fA-F]{6})", gradient)
        if colors:
            findings["login_gradient_colors"] = ("#" + ",#".join(colors), CONF_LOW)

    return findings


# ── Runtime 扫描 ──


def scan_runtime(runtime_dir: Path) -> dict:
    """从旧 runtime 扫描已有配置和资产，返回 {field: (value, confidence)} 映射。"""
    findings: dict[str, tuple[str, str]] = {}

    # 已有 ui-branding.yaml — 最高优先级
    branding_yaml = runtime_dir / "config" / "ui-branding.yaml"
    if branding_yaml.exists():
        try:
            data = yaml.safe_load(branding_yaml.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("app_title", "app_version", "login_title", "login_subtitle", "login_notice",
                            "topbar_title", "review_workspace_label", "admin_label"):
                    val = data.get(key)
                    if val and isinstance(val, str):
                        findings[key] = (val, CONF_HIGH)
                theme = data.get("theme")
                if isinstance(theme, dict):
                    for tk in ("primary", "primary_hover", "accent"):
                        tv = theme.get(tk)
                        if tv and isinstance(tv, str):
                            findings[f"theme_{tk}"] = (tv, CONF_HIGH)
                for key in ("login_logo", "topbar_logo", "favicon"):
                    val = data.get(key)
                    if val and isinstance(val, str):
                        findings[f"{key}_file"] = (val, CONF_HIGH)
        except Exception:
            logger.warning("failed to parse existing ui-branding.yaml")

    # 已有 branding 资产文件
    branding_dir = runtime_dir / "assets" / "branding"
    if branding_dir.exists():
        for f in branding_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                ext = f.suffix.lower()
                if ext in (".png", ".jpg", ".jpeg", ".svg", ".ico", ".gif", ".webp"):
                    name = f.name
                    if "favicon" in name.lower():
                        findings["favicon_file"] = (name, CONF_HIGH)
                    elif "logo" in name.lower():
                        if "login" in name.lower() or "brand" in name.lower():
                            findings["login_logo_file"] = (name, CONF_HIGH)
                        findings["topbar_logo_file"] = (name, CONF_MEDIUM)
                    # 通用资产也记录为候选
                    findings.setdefault("asset_candidate", (name, CONF_LOW))

    # favicon 文件直接在 runtime 根或 static 目录
    for candidate in [
        runtime_dir / "data" / "favicon.svg",
        runtime_dir / "favicon.svg",
        runtime_dir / "static" / "favicon.svg",
    ]:
        if candidate.exists():
            findings["favicon_file"] = (candidate.name, CONF_HIGH)

    return findings


# ── 资产发现 ──


def discover_assets(static_dir: Path) -> dict[str, tuple[Path, str]]:
    """在旧项目的 static 目录中搜索 favicon/logo 等品牌资产文件。"""
    assets: dict[str, tuple[Path, str]] = {}

    # favicon
    for name in ("favicon.svg", "favicon.ico", "favicon.png"):
        f = static_dir / name
        if f.exists():
            assets["favicon_file"] = (f, CONF_HIGH)
            break

    # logo — 在 static 根目录和子目录搜索
    logo_patterns = ("logo*", "brand*", "*logo*")
    for pattern in logo_patterns:
        for f in static_dir.glob(pattern):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".ico", ".gif", ".webp"):
                key = "logo_file"
                if key not in assets:
                    assets[key] = (f, CONF_MEDIUM)

    # img 目录下的 logo
    img_dir = static_dir / "img"
    if img_dir.exists():
        for pattern in logo_patterns:
            for f in img_dir.glob(pattern):
                if f.is_file():
                    if "logo_file" not in assets:
                        assets["logo_file"] = (f, CONF_LOW)

    return assets


# ── 合并与生成 ──


def merge_findings(code_findings: dict, css_findings: dict, runtime_findings: dict) -> dict[str, tuple[str, str]]:
    """合并三路扫描结果，runtime 最高优先级。

    优先级：runtime > code > css。后写入的同置信或更高置信覆盖前面的。
    """
    merged = {}
    for source in (css_findings, code_findings, runtime_findings):
        for key, val in source.items():
            if key not in merged:
                merged[key] = val
            else:
                existing_conf = merged[key][1]
                new_conf = val[1]
                # 高置信覆盖低置信；同置信时后写入覆盖前面（runtime > code > css）
                if new_conf == CONF_HIGH and existing_conf != CONF_HIGH:
                    merged[key] = val
                elif new_conf == existing_conf and source is runtime_findings:
                    merged[key] = val
                elif new_conf == existing_conf and source is code_findings:
                    merged[key] = val
    return merged


def _validate_asset_path_safe(path_str: str) -> str | None:
    """校验资产路径，与 branding_config._validate_asset_path 同等约束。

    拒绝外部 URL、绝对文件路径（多个 / 前缀段）、.. 穿越。
    允许 URL 前缀斜杠（如 /favicon.svg），去掉后保留文件名。
    返回通过校验的路径，或 None 表示非法。
    """
    if not path_str:
        return None

    # 拒绝 URL
    if path_str.startswith(("http://", "https://", "ftp://", "//")):
        logger.warning("asset path rejected: external URL (%s)", path_str)
        return None

    # 去掉 URL 前缀斜杠后再做路径校验
    clean = path_str.lstrip("/")

    if not clean:
        return None

    # 多段绝对路径在去掉前缀斜杠后仍含 / 分隔符，应当拒绝；
    # 只允许单段前缀斜杠路径（如 HTML 中的 href="/favicon.svg"）
    if path_str.startswith("/") and "/" in clean:
        logger.warning("asset path rejected: multi-segment absolute path (%s)", path_str)
        return None

    p = Path(clean)

    # 拒绝绝对路径（去掉 URL 前缀 / 后不应再是绝对路径）
    if p.is_absolute():
        logger.warning("asset path rejected: absolute path (%s)", path_str)
        return None

    # 拒绝 .. 穿越
    if ".." in p.parts:
        logger.warning("asset path rejected: path traversal (%s)", path_str)
        return None

    return clean


def build_branding_yaml(merged: dict[str, tuple[str, str]]) -> dict:
    """从合并结果构建 ui-branding.yaml 数据结构。"""
    config = {
        "app_title": "",
        "app_version": "",
        "login_title": "",
        "login_subtitle": "",
        "login_notice": "",
        "topbar_title": "",
        "review_workspace_label": "",
        "admin_label": "",
        "theme": {
            "primary": "",
            "primary_hover": "",
            "accent": "#23C343",
        },
        "login_logo": "",
        "topbar_logo": "",
        "favicon": "",
    }

    # 字段映射
    field_map = {
        "app_title": "app_title",
        "app_version": "app_version",
        "login_title": "login_title",
        "login_subtitle": "login_subtitle",
        "login_notice": "login_notice",
        "topbar_title": "topbar_title",
        "review_workspace_label": "review_workspace_label",
        "admin_label": "admin_label",
    }
    for src_key, yaml_key in field_map.items():
        if src_key in merged:
            config[yaml_key] = merged[src_key][0]

    # 主题色映射
    theme_map = {
        "theme_primary": "primary",
        "theme_primary_meta": "primary",
        "theme_primary_svg": "primary",
        "theme_primary_hover": "primary_hover",
    }
    for src_key, theme_key in theme_map.items():
        if src_key in merged and not config["theme"][theme_key]:
            config["theme"][theme_key] = merged[src_key][0]

    # 资产文件映射
    asset_map = {
        "favicon_file": "favicon",
        "login_logo_file": "login_logo",
        "topbar_logo_file": "topbar_logo",
    }
    for src_key, yaml_key in asset_map.items():
        if src_key in merged:
            val = merged[src_key][0]
            # 路径安全校验：拒绝外部 URL、绝对路径、.. 穿越
            validated = _validate_asset_path_safe(val)
            if validated is not None:
                config[yaml_key] = validated
            else:
                config[yaml_key] = ""
                logger.warning("migrate: asset path rejected in build_branding_yaml (%s=%s)", src_key, val)

    return config


def build_scan_report(merged: dict[str, tuple[str, str]], config: dict) -> str:
    """生成扫描报告，标注每个字段的来源和置信度。"""
    lines = [
        "# 品牌配置扫描报告",
        "",
        "## 自动生成的配置",
        "",
        "以下字段已写入 `ui-branding.yaml`：",
        "",
        "| 字段 | 值 | 置信度 |",
        "| --- | --- | --- |",
    ]

    for key in ("app_title", "app_version", "login_title", "login_subtitle", "login_notice",
                "topbar_title", "review_workspace_label", "admin_label"):
        val = config.get(key, "")
        if val:
            conf = merged.get(key, ("", CONF_LOW))[1]
            lines.append(f"| {key} | {val} | {conf} |")
        else:
            lines.append(f"| {key} | （未找到） | — |")

    lines.extend([
        "",
        "## 主题色",
        "",
        "| 字段 | 值 | 置信度 |",
        "| --- | --- | --- |",
    ])
    for tk in ("primary", "primary_hover", "accent"):
        val = config["theme"].get(tk, "")
        src_key = f"theme_{tk}"
        conf = merged.get(src_key, ("", CONF_LOW))[1] if src_key in merged else CONF_LOW
        lines.append(f"| {tk} | {val} | {conf} |")

    lines.extend([
        "",
        "## 资产文件",
        "",
        "| 字段 | 文件名 | 置信度 |",
        "| --- | --- | --- |",
    ])
    for ak in ("favicon", "login_logo", "topbar_logo"):
        val = config.get(ak, "")
        src_key = f"{ak}_file"
        conf = merged.get(src_key, ("", CONF_LOW))[1] if src_key in merged else CONF_LOW
        lines.append(f"| {ak} | {val or '（未找到）'} | {conf} |")

    # 低置信候选
    low_items = [(k, v[0], v[1]) for k, v in merged.items() if v[1] == CONF_LOW]
    if low_items:
        lines.extend([
            "",
            "## 低置信候选（需人工确认）",
            "",
            "| 键 | 值 |",
            "| --- | --- |",
        ])
        for k, v, _ in low_items:
            lines.append(f"| {k} | {v} |")

    lines.extend([
        "",
        "## 说明",
        "",
        "- 置信度 `high`：从明确 HTML 元素或已有 runtime 配置提取",
        "- 置信度 `medium`：从间接 HTML 元素或 CSS 变量推断",
        "- 置信度 `low`：需要人工确认后再手动编辑 YAML",
        "",
        "如需调整，直接编辑 `runtime/config/ui-branding.yaml` 即可。",
    ])
    return "\n".join(lines)


# ── 资产复制 ──


def copy_assets(static_dir: Path, runtime_dir: Path, target_dir: Path, merged: dict, discovered: dict) -> list[str]:
    """复制品牌资产到目标 runtime/assets/branding/。

    所有资产路径必须通过 _validate_asset_path_safe 校验，
    复制目标不得写出 branding 目录边界。
    """
    copied: list[str] = []
    target_branding = target_dir / "assets" / "branding"
    target_branding.mkdir(parents=True, exist_ok=True)
    branding_root = target_branding.resolve()

    # favicon
    favicon_raw = merged.get("favicon_file", ("", CONF_LOW))[0]
    if favicon_raw:
        clean_name = _validate_asset_path_safe(favicon_raw)
        if clean_name is None:
            logger.warning("copy_assets: favicon path rejected (%s)", favicon_raw)
        else:
            dest = target_branding / clean_name
            # 安全检查：dest 必须在 branding 目录内
            try:
                dest.resolve().relative_to(branding_root)
            except ValueError:
                logger.warning("copy_assets: favicon dest escapes branding dir (%s)", clean_name)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                src = static_dir / clean_name
                if src.exists():
                    shutil.copy2(src, dest)
                    copied.append(clean_name)
                else:
                    runtime_src = runtime_dir / "assets" / "branding" / clean_name
                    if runtime_src.exists():
                        shutil.copy2(runtime_src, dest)
                        copied.append(clean_name)

    # logo
    for key in ("login_logo_file", "topbar_logo_file", "logo_file"):
        if key in discovered:
            src_path, conf = discovered[key]
            if src_path.exists():
                dest = target_branding / src_path.name
                try:
                    dest.resolve().relative_to(branding_root)
                except ValueError:
                    logger.warning("copy_assets: logo dest escapes branding dir (%s)", src_path.name)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest)
                    copied.append(src_path.name)

    # 已有 runtime 资产
    src_branding = runtime_dir / "assets" / "branding"
    if src_branding.exists():
        for f in src_branding.iterdir():
            if f.is_file() and not f.name.startswith("."):
                dest = target_branding / f.name
                try:
                    dest.resolve().relative_to(branding_root)
                except ValueError:
                    continue
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    copied.append(f.name)

    return copied


def _discover_static_dir(code_dir: Path) -> Path:
    """从旧项目代码目录自动发现 static 目录。

    搜索顺序：传入目录本身（如果含 index.html）、src/static/、static/。
    """
    candidates = [
        code_dir,
        code_dir / "src" / "static",
        code_dir / "static",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    # 回退到传入目录（即使没有 index.html，扫描会返回空结果）
    return code_dir


# ── 主流程 ──


def migrate(
    legacy_code_dir: Path,
    legacy_runtime_dir: Path,
    target_runtime_dir: Path,
    force: bool = False,
) -> dict:
    """执行品牌迁移，返回结果摘要。

    legacy_code_dir 可以传旧项目根目录或 static 目录：
    - 如果传根目录，自动在 src/static/ 和 static/ 中寻找前端文件。
    - 如果传 static 目录，直接使用。
    """
    # 自动发现 static 目录
    static_dir = _discover_static_dir(legacy_code_dir)
    html_path = static_dir / "index.html"
    css_path = static_dir / "css" / "main.css"

    code_findings = scan_html(html_path)
    css_findings = scan_css(css_path)
    runtime_findings = scan_runtime(legacy_runtime_dir)

    merged = merge_findings(code_findings, css_findings, runtime_findings)
    discovered_assets = discover_assets(static_dir)

    # 将 discovered_assets 中的 logo 信息写入 merged（低置信，不覆盖已有高置信值）
    if "logo_file" in discovered_assets:
        logo_path, logo_conf = discovered_assets["logo_file"]
        logo_name = logo_path.name
        if "login_logo_file" not in merged:
            merged["login_logo_file"] = (logo_name, logo_conf)
        if "topbar_logo_file" not in merged:
            merged["topbar_logo_file"] = (logo_name, logo_conf)

    # 构建配置
    config = build_branding_yaml(merged)

    # 写入 ui-branding.yaml
    yaml_path = target_runtime_dir / "config" / "ui-branding.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    if yaml_path.exists() and not force:
        logger.warning("ui-branding.yaml already exists, skipping (use --force to overwrite)")
        print(f"[SKIP] {yaml_path} already exists — use --force to overwrite")
    else:
        # 清空空值字段
        clean_config = {}
        for k, v in config.items():
            if isinstance(v, dict):
                clean_v = {}
                for sk, sv in v.items():
                    if sv:
                        clean_v[sk] = sv
                if clean_v:
                    clean_config[k] = clean_v
            elif v:
                clean_config[k] = v

        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(clean_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print(f"[WRITE] {yaml_path}")

    # 写入扫描报告
    report_path = target_runtime_dir / "config" / "ui-branding.scan-report.md"
    report = build_scan_report(merged, config)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"[WRITE] {report_path}")

    # 复制资产
    copied = copy_assets(static_dir, legacy_runtime_dir, target_runtime_dir, merged, discovered_assets)
    for name in copied:
        print(f"[COPY] {name} → {target_runtime_dir}/assets/branding/{name}")

    return {
        "yaml_path": str(yaml_path),
        "report_path": str(report_path),
        "copied_assets": copied,
        "merged_findings": {k: (v[0], v[1]) for k, v in merged.items()},
        "config": config,
    }


def main():
    parser = argparse.ArgumentParser(description="品牌迁移工具 — 从旧项目扫描品牌配置")
    parser.add_argument("--legacy-code-dir", required=True, help="旧项目代码目录路径（根目录或 static 目录均可）")
    parser.add_argument("--legacy-runtime-dir", required=True, help="旧项目 runtime 目录路径")
    parser.add_argument("--target-runtime-dir", required=True, help="目标 runtime 目录路径")
    parser.add_argument("--force", action="store_true", help="覆盖已有的 ui-branding.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    result = migrate(
        legacy_code_dir=Path(args.legacy_code_dir),
        legacy_runtime_dir=Path(args.legacy_runtime_dir),
        target_runtime_dir=Path(args.target_runtime_dir),
        force=args.force,
    )

    print(f"\n迁移完成：{len(result['copied_assets'])} 个资产已复制")
    print(f"配置文件：{result['yaml_path']}")
    print(f"扫描报告：{result['report_path']}")


if __name__ == "__main__":
    main()