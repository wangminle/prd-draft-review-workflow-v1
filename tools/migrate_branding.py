"""品牌迁移工具 — 从旧项目代码和 runtime 扫描品牌配置并生成 ui-branding.yaml。

用法：
    # scan 模式 — 只扫描不写入
    python3 tools/migrate_branding.py scan \
        --legacy-code-dir /path/to/old/project \
        --legacy-runtime-dir /path/to/old/runtime

    # plan 模式 — 生成标准化建议和差异报告
    python3 tools/migrate_branding.py plan \
        --legacy-code-dir /path/to/old/project \
        --legacy-runtime-dir /path/to/old/runtime \
        --target-runtime-dir ./runtime

    # apply 模式 — 写入配置和资产到目标 runtime（需确认）
    python3 tools/migrate_branding.py apply \
        --legacy-code-dir /path/to/old/project \
        --legacy-runtime-dir /path/to/old/runtime \
        --target-runtime-dir ./runtime

    # 默认 migrate 模式 — scan → plan → apply 一步完成
    python3 tools/migrate_branding.py migrate \
        --legacy-code-dir /path/to/old/project \
        --legacy-runtime-dir /path/to/old/runtime \
        --target-runtime-dir ./runtime

核心行为：
    - scan：从旧代码和 runtime 扫描品牌元素，输出识别结果和三级分类
    - plan：基于 scan 生成标准化建议、差异报告
    - apply：在用户确认后写入配置和资产到目标位置，不覆盖原始配置
    - migrate：scan → plan → apply 一步完成
    - 不覆盖已有配置（除非 --force）
    - 不写入绝对路径或外部 URL
    - 不触碰业务数据（data/、logs/、uploads/ 等）
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

# ── 三级分类标记 ──
CAT_AUTO = "auto"         # 可自动映射：标准个性化字段
CAT_CONFIRM = "confirm"   # 需人工确认：含义不确定
CAT_OUT_OF_SCOPE = "out_of_scope"  # 超出范围：不属于标准个性化配置

# 标准个性化字段 → 分类映射
_BRANDING_FIELD_CATEGORIES = {
    "app_title": CAT_AUTO,
    "app_version": CAT_AUTO,
    "login_title": CAT_AUTO,
    "login_subtitle": CAT_AUTO,
    "login_notice": CAT_AUTO,
    "topbar_title": CAT_AUTO,
    "review_workspace_label": CAT_AUTO,
    "admin_label": CAT_AUTO,
    "theme_primary": CAT_AUTO,
    "theme_primary_hover": CAT_AUTO,
    "theme_primary_meta": CAT_AUTO,
    "theme_primary_svg": CAT_CONFIRM,  # SVG fill 可能不是品牌色
    "theme_accent": CAT_AUTO,
    "login_gradient_colors": CAT_CONFIRM,  # 渐变色不确定是品牌色
    "favicon_file": CAT_AUTO,
    "login_logo_file": CAT_AUTO,
    "topbar_logo_file": CAT_AUTO,
    "logo_file": CAT_CONFIRM,  # 通用 logo 需确认用途
    "asset_candidate": CAT_OUT_OF_SCOPE,
}


def classify_field(field: str) -> str:
    """返回字段的三级分类标记。"""
    return _BRANDING_FIELD_CATEGORIES.get(field, CAT_OUT_OF_SCOPE)


def _can_auto_apply(field: str, confidence: str) -> bool:
    """判断扫描字段是否允许自动进入 apply 写入阶段。"""
    return classify_field(field) == CAT_AUTO and confidence != CONF_LOW


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
                legacy_notice = data.get("login_notice_text")
                if "login_notice" not in findings and legacy_notice and isinstance(legacy_notice, str):
                    findings["login_notice"] = (legacy_notice, CONF_HIGH)
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
                    elif "logo" in name.lower() or "brand" in name.lower():
                        name_lower = name.lower()
                        if any(kw in name_lower for kw in ("topbar", "header", "nav", "icon", "mark", "symbol")):
                            findings.setdefault("topbar_logo_file", (name, CONF_MEDIUM))
                        elif "login" in name_lower or "brand" in name_lower:
                            findings.setdefault("login_logo_file", (name, CONF_HIGH))
                        else:
                            # 通用 logo 优先用于登录页，顶栏仅在无显式命名时回退
                            findings.setdefault("login_logo_file", (name, CONF_MEDIUM))
                            findings.setdefault("topbar_logo_file", (name, CONF_LOW))
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


def discover_assets(project_dir: Path, static_dir: Path) -> dict[str, tuple[Path, str]]:
    """在旧项目中搜索 favicon/logo 等品牌资产文件。

    搜索范围：static_dir 根目录和子目录、项目根目录的 assets/、dist/、public/。
    """
    assets: dict[str, tuple[Path, str]] = {}

    # favicon — 只在 static 目录搜索
    for name in ("favicon.svg", "favicon.ico", "favicon.png"):
        f = static_dir / name
        if f.exists():
            assets["favicon_file"] = (f, CONF_HIGH)
            break

    # Logo 搜索模式（大小写无关）
    logo_keywords = ("logo", "brand")
    image_exts = (".png", ".jpg", ".jpeg", ".svg", ".ico", ".gif", ".webp")

    def _is_logo_file(f: Path) -> bool:
        return f.is_file() and f.suffix.lower() in image_exts and any(kw in f.name.lower() for kw in logo_keywords)

    # static 根目录和子目录
    for f in static_dir.iterdir():
        if _is_logo_file(f) and "logo_file" not in assets:
            assets["logo_file"] = (f, CONF_MEDIUM)

    # static/img 目录
    img_dir = static_dir / "img"
    if img_dir.exists():
        for f in img_dir.iterdir():
            if _is_logo_file(f) and "logo_file" not in assets:
                assets["logo_file"] = (f, CONF_LOW)

    # 项目根目录的 assets/、dist/、public/ — 低置信
    extra_dirs = [
        project_dir / "assets",
        project_dir / "dist",
        project_dir / "public",
    ]
    for extra_dir in extra_dirs:
        if not extra_dir.exists() or extra_dir == static_dir:
            continue
        for f in extra_dir.iterdir():
            if _is_logo_file(f) and "logo_file" not in assets:
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

    if p.is_absolute():
        logger.warning("asset path rejected: absolute path (%s)", path_str)
        return None

    if ".." in p.parts:
        logger.warning("asset path rejected: path traversal (%s)", path_str)
        return None

    return clean


def build_branding_yaml(merged: dict[str, tuple[str, str]]) -> dict:
    """从合并结果构建 ui-branding.yaml 数据结构。只取可自动 apply 的字段。"""
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
            "accent": "",
        },
        "login_logo": "",
        "topbar_logo": "",
        "favicon": "",
    }

    # 字段映射 — 只取可自动 apply 字段
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
        if src_key in merged and _can_auto_apply(src_key, merged[src_key][1]):
            config[yaml_key] = merged[src_key][0]

    # 主题色映射
    theme_map = {
        "theme_primary": "primary",
        "theme_primary_meta": "primary",
        "theme_primary_svg": "primary",
        "theme_primary_hover": "primary_hover",
    }
    for src_key, theme_key in theme_map.items():
        if src_key in merged and _can_auto_apply(src_key, merged[src_key][1]):
            if not config["theme"][theme_key]:
                config["theme"][theme_key] = merged[src_key][0]

    # 资产文件映射
    asset_map = {
        "favicon_file": "favicon",
        "login_logo_file": "login_logo",
        "topbar_logo_file": "topbar_logo",
    }
    for src_key, yaml_key in asset_map.items():
        if src_key in merged and _can_auto_apply(src_key, merged[src_key][1]):
            val = merged[src_key][0]
            validated = _validate_asset_path_safe(val)
            if validated is not None:
                config[yaml_key] = validated
            else:
                config[yaml_key] = ""
                logger.warning("migrate: asset path rejected in build_branding_yaml (%s=%s)", src_key, val)

    return config


def build_scan_report(merged: dict[str, tuple[str, str]], config: dict) -> str:
    """生成扫描报告，标注每个字段的来源、置信度和三级分类。"""
    lines = [
        "# 品牌配置扫描报告",
        "",
        "## 自动映射字段",
        "",
        "以下字段属于标准个性化配置，可自动写入 `ui-branding.yaml`：",
        "",
        "| 字段 | 值 | 置信度 | 分类 |",
        "| --- | --- | --- | --- |",
    ]

    for key in ("app_title", "app_version", "login_title", "login_subtitle", "login_notice",
                "topbar_title", "review_workspace_label", "admin_label"):
        val = config.get(key, "")
        cat = classify_field(key)
        if val:
            conf = merged.get(key, ("", CONF_LOW))[1]
            lines.append(f"| {key} | {val} | {conf} | {cat} |")
        else:
            lines.append(f"| {key} | （未找到） | — | {cat} |")

    lines.extend([
        "",
        "## 主题色",
        "",
        "| 字段 | 值 | 置信度 | 分类 |",
        "| --- | --- | --- | --- |",
    ])
    for tk in ("primary", "primary_hover", "accent"):
        val = config["theme"].get(tk, "")
        src_key = f"theme_{tk}"
        cat = classify_field(src_key)
        conf = merged.get(src_key, ("", CONF_LOW))[1] if src_key in merged else CONF_LOW
        lines.append(f"| {tk} | {val or '（未找到）'} | {conf} | {cat} |")

    lines.extend([
        "",
        "## 资产文件",
        "",
        "| 字段 | 文件名 | 置信度 | 分类 |",
        "| --- | --- | --- | --- |",
    ])
    for ak in ("favicon", "login_logo", "topbar_logo"):
        val = config.get(ak, "")
        src_key = f"{ak}_file"
        cat = classify_field(src_key)
        conf = merged.get(src_key, ("", CONF_LOW))[1] if src_key in merged else CONF_LOW
        lines.append(f"| {ak} | {val or '（未找到）'} | {conf} | {cat} |")

    # 需人工确认字段：分类为 confirm，或虽是 auto 但置信度不足以自动 apply
    confirm_items = [(k, v[0], v[1]) for k, v in merged.items()
                     if classify_field(k) == CAT_CONFIRM
                     or (classify_field(k) == CAT_AUTO and v[1] == CONF_LOW)]
    if confirm_items:
        lines.extend([
            "",
            "## 需人工确认",
            "",
            "以下字段已识别但含义不确定，需要人工确认后再决定是否写入配置：",
            "",
            "| 键 | 值 | 置信度 |",
            "| --- | --- | --- |",
        ])
        for k, v, c in confirm_items:
            lines.append(f"| {k} | {v} | {c} |")

    # 超出范围字段
    out_items = [(k, v[0], v[1]) for k, v in merged.items()
                 if classify_field(k) == CAT_OUT_OF_SCOPE]
    if out_items:
        lines.extend([
            "",
            "## 超出范围",
            "",
            "以下字段不属于标准个性化配置，不会自动映射：",
            "",
            "| 键 | 值 | 置信度 |",
            "| --- | --- | --- |",
        ])
        for k, v, c in out_items:
            lines.append(f"| {k} | {v} | {c} |")

    lines.extend([
        "",
        "## 分类说明",
        "",
        "- `auto`：可自动映射，属于标准个性化字段",
        "- `confirm`：需人工确认，已识别但含义不确定",
        "- `out_of_scope`：超出范围，不属于标准个性化配置",
        "",
        "如需调整，直接编辑 `runtime/config/ui-branding.yaml` 即可。",
    ])
    return "\n".join(lines)


# ── 资产复制 ──

# apply 模式只允许写入的目录白名单
_WRITE_ALLOWED_DIRS = ("config", "assets/branding")


def _check_write_path_allowed(target_dir: Path, write_path: Path) -> bool:
    """检查写入路径是否在允许的目录白名单内，防止误写业务数据。"""
    try:
        rel = write_path.resolve().relative_to(target_dir.resolve())
        rel_str = str(rel)
        for allowed in _WRITE_ALLOWED_DIRS:
            if rel_str.startswith(allowed):
                return True
        return False
    except ValueError:
        return False


def copy_assets(project_dir: Path, static_dir: Path, runtime_dir: Path, target_dir: Path,
                merged: dict, discovered: dict) -> list[str]:
    """复制品牌资产到目标 runtime/assets/branding/。

    所有资产路径必须通过 _validate_asset_path_safe 校验，
    复制目标不得写出 branding 目录边界。
    只写入 target_dir 下白名单允许的目录。
    """
    copied: list[str] = []
    target_branding = target_dir / "assets" / "branding"
    target_branding.mkdir(parents=True, exist_ok=True)
    branding_root = target_branding.resolve()

    # favicon
    favicon_raw, favicon_conf = merged.get("favicon_file", ("", CONF_LOW))
    if favicon_raw and _can_auto_apply("favicon_file", favicon_conf):
        clean_name = _validate_asset_path_safe(favicon_raw)
        if clean_name is None:
            logger.warning("copy_assets: favicon path rejected (%s)", favicon_raw)
        else:
            dest = target_branding / clean_name
            try:
                dest.resolve().relative_to(branding_root)
            except ValueError:
                logger.warning("copy_assets: favicon dest escapes branding dir (%s)", clean_name)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                # 搜索 favicon 来源：static → runtime → discovered
                src = static_dir / clean_name
                if not src.exists():
                    src = runtime_dir / "assets" / "branding" / clean_name
                if not src.exists():
                    # 在项目其他目录搜索
                    for alt_dir in [project_dir / "assets", project_dir / "dist", project_dir / "public"]:
                        alt = alt_dir / clean_name
                        if alt.exists():
                            src = alt
                            break
                if src.exists():
                    shutil.copy2(src, dest)
                    copied.append(clean_name)
                else:
                    runtime_src = runtime_dir / "assets" / "branding" / clean_name
                    if runtime_src.exists():
                        shutil.copy2(runtime_src, dest)
                        copied.append(clean_name)

    # logo：只复制最终 YAML 会引用的自动 apply 资产
    for key in ("login_logo_file", "topbar_logo_file", "logo_file"):
        if key in discovered:
            src_path, conf = discovered[key]
            referenced_by_auto_field = any(
                merged_key in merged
                and merged[merged_key][0] == src_path.name
                and _can_auto_apply(merged_key, merged[merged_key][1])
                for merged_key in ("login_logo_file", "topbar_logo_file")
            )
            if src_path.exists() and referenced_by_auto_field:
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
    return code_dir


# ── 主流程 ──


def scan(
    legacy_code_dir: Path,
    legacy_runtime_dir: Path,
) -> dict:
    """只扫描旧项目，不写入任何文件。返回扫描结果和分类。"""
    static_dir = _discover_static_dir(legacy_code_dir)
    html_path = static_dir / "index.html"
    css_path = static_dir / "css" / "main.css"

    code_findings = scan_html(html_path)
    css_findings = scan_css(css_path)
    runtime_findings = scan_runtime(legacy_runtime_dir)

    merged = merge_findings(code_findings, css_findings, runtime_findings)
    discovered_assets = discover_assets(legacy_code_dir, static_dir)

    # 通用发现的 logo 默认只映射到登录页，避免把大字标直接塞进顶栏。
    if "logo_file" in discovered_assets:
        logo_path, logo_conf = discovered_assets["logo_file"]
        logo_name = logo_path.name
        if "login_logo_file" not in merged:
            merged["login_logo_file"] = (logo_name, logo_conf)

    # 分类汇总
    classified = {}
    for key, val in merged.items():
        classified[key] = {
            "value": val[0],
            "confidence": val[1],
            "category": classify_field(key),
        }

    print(f"[SCAN] 完成：{len(merged)} 项发现")
    for key, info in classified.items():
        print(f"  {key}: {info['value']} ({info['confidence']}, {info['category']})")

    return {
        "merged_findings": {k: (v[0], v[1]) for k, v in merged.items()},
        "classified": classified,
        "discovered_assets": {k: (str(v[0]), v[1]) for k, v in discovered_assets.items()},
    }


def plan(
    legacy_code_dir: Path,
    legacy_runtime_dir: Path,
    target_runtime_dir: Path,
) -> dict:
    """基于 scan 生成标准化建议和差异报告，不写入配置文件（只写报告）。"""
    static_dir = _discover_static_dir(legacy_code_dir)
    html_path = static_dir / "index.html"
    css_path = static_dir / "css" / "main.css"

    code_findings = scan_html(html_path)
    css_findings = scan_css(css_path)
    runtime_findings = scan_runtime(legacy_runtime_dir)

    merged = merge_findings(code_findings, css_findings, runtime_findings)
    discovered_assets = discover_assets(legacy_code_dir, static_dir)

    if "logo_file" in discovered_assets:
        logo_path, logo_conf = discovered_assets["logo_file"]
        logo_name = logo_path.name
        if "login_logo_file" not in merged:
            merged["login_logo_file"] = (logo_name, logo_conf)

    config = build_branding_yaml(merged)
    report = build_scan_report(merged, config)

    # 只写扫描报告，不写配置文件
    report_path = target_runtime_dir / "config" / "ui-branding.scan-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"[PLAN] 报告已写入：{report_path}")

    # 显示建议摘要
    auto_items = [(k, v[0]) for k, v in merged.items() if classify_field(k) == CAT_AUTO and v[0]]
    confirm_items = [(k, v[0]) for k, v in merged.items() if classify_field(k) == CAT_CONFIRM]
    out_items = [(k, v[0]) for k, v in merged.items() if classify_field(k) == CAT_OUT_OF_SCOPE]

    print(f"\n[PLAN] 建议：{len(auto_items)} 项可自动映射，{len(confirm_items)} 项需确认，{len(out_items)} 项超出范围")

    return {
        "report_path": str(report_path),
        "config": config,
        "merged_findings": {k: (v[0], v[1]) for k, v in merged.items()},
        "auto_items": auto_items,
        "confirm_items": confirm_items,
        "out_items": out_items,
    }


def apply(
    legacy_code_dir: Path,
    legacy_runtime_dir: Path,
    target_runtime_dir: Path,
    force: bool = False,
) -> dict:
    """在用户确认后，写入配置和资产到目标 runtime。

    只写入 target_runtime_dir/config/ 和 target_runtime_dir/assets/branding/，
    不触碰业务数据区域（data/、logs/、uploads/）。
    """
    static_dir = _discover_static_dir(legacy_code_dir)
    html_path = static_dir / "index.html"
    css_path = static_dir / "css" / "main.css"

    code_findings = scan_html(html_path)
    css_findings = scan_css(css_path)
    runtime_findings = scan_runtime(legacy_runtime_dir)

    merged = merge_findings(code_findings, css_findings, runtime_findings)
    discovered_assets = discover_assets(legacy_code_dir, static_dir)

    if "logo_file" in discovered_assets:
        logo_path, logo_conf = discovered_assets["logo_file"]
        logo_name = logo_path.name
        if "login_logo_file" not in merged:
            merged["login_logo_file"] = (logo_name, logo_conf)

    config = build_branding_yaml(merged)

    # 写入 ui-branding.yaml
    yaml_path = target_runtime_dir / "config" / "ui-branding.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入路径安全检查
    if not _check_write_path_allowed(target_runtime_dir, yaml_path):
        logger.error("apply: yaml_path not in allowed write dirs (%s)", yaml_path)
        print(f"[ERROR] 写入路径不在白名单内：{yaml_path}")
        return {"yaml_path": "", "report_path": "", "copied_assets": [], "config": config}

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
    copied = copy_assets(legacy_code_dir, static_dir, legacy_runtime_dir, target_runtime_dir,
                         merged, discovered_assets)
    for name in copied:
        print(f"[COPY] {name} → {target_runtime_dir}/assets/branding/{name}")

    return {
        "yaml_path": str(yaml_path),
        "report_path": str(report_path),
        "copied_assets": copied,
        "merged_findings": {k: (v[0], v[1]) for k, v in merged.items()},
        "config": config,
    }


def migrate(
    legacy_code_dir: Path,
    legacy_runtime_dir: Path,
    target_runtime_dir: Path,
    force: bool = False,
) -> dict:
    """scan → plan → apply 一步完成。"""
    scan_result = scan(legacy_code_dir, legacy_runtime_dir)
    plan_result = plan(legacy_code_dir, legacy_runtime_dir, target_runtime_dir)
    apply_result = apply(legacy_code_dir, legacy_runtime_dir, target_runtime_dir, force)
    return apply_result


def main():
    parser = argparse.ArgumentParser(description="品牌迁移工具 — 从旧项目扫描品牌配置")
    subparsers = parser.add_subparsers(dest="command", help="操作模式")

    # scan 子命令
    scan_parser = subparsers.add_parser("scan", help="只扫描，不写入任何文件")
    scan_parser.add_argument("--legacy-code-dir", required=True, help="旧项目代码目录路径")
    scan_parser.add_argument("--legacy-runtime-dir", required=True, help="旧项目 runtime 目录路径")

    # plan 子命令
    plan_parser = subparsers.add_parser("plan", help="生成标准化建议和差异报告")
    plan_parser.add_argument("--legacy-code-dir", required=True, help="旧项目代码目录路径")
    plan_parser.add_argument("--legacy-runtime-dir", required=True, help="旧项目 runtime 目录路径")
    plan_parser.add_argument("--target-runtime-dir", required=True, help="目标 runtime 目录路径")

    # apply 子命令
    apply_parser = subparsers.add_parser("apply", help="写入配置和资产到目标 runtime")
    apply_parser.add_argument("--legacy-code-dir", required=True, help="旧项目代码目录路径")
    apply_parser.add_argument("--legacy-runtime-dir", required=True, help="旧项目 runtime 目录路径")
    apply_parser.add_argument("--target-runtime-dir", required=True, help="目标 runtime 目录路径")
    apply_parser.add_argument("--force", action="store_true", help="覆盖已有的 ui-branding.yaml")

    # migrate 子命令（默认）
    migrate_parser = subparsers.add_parser("migrate", help="scan → plan → apply 一步完成")
    migrate_parser.add_argument("--legacy-code-dir", required=True, help="旧项目代码目录路径（根目录或 static 目录均可）")
    migrate_parser.add_argument("--legacy-runtime-dir", required=True, help="旧项目 runtime 目录路径")
    migrate_parser.add_argument("--target-runtime-dir", required=True, help="目标 runtime 目录路径")
    migrate_parser.add_argument("--force", action="store_true", help="覆盖已有的 ui-branding.yaml")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    common_args = {
        "legacy_code_dir": Path(args.legacy_code_dir),
        "legacy_runtime_dir": Path(args.legacy_runtime_dir),
    }

    if args.command == "scan":
        result = scan(**common_args)
        print(f"\n扫描完成：{len(result['classified'])} 项发现")
    elif args.command == "plan":
        result = plan(**common_args, target_runtime_dir=Path(args.target_runtime_dir))
        print(f"\n规划完成：报告 {result['report_path']}")
    elif args.command == "apply":
        result = apply(**common_args,
                       target_runtime_dir=Path(args.target_runtime_dir),
                       force=args.force)
        print(f"\n应用完成：{len(result['copied_assets'])} 个资产已复制")
        print(f"配置文件：{result['yaml_path']}")
        print(f"扫描报告：{result['report_path']}")
    elif args.command == "migrate":
        result = migrate(**common_args,
                         target_runtime_dir=Path(args.target_runtime_dir),
                         force=args.force)
        print(f"\n迁移完成：{len(result['copied_assets'])} 个资产已复制")
        print(f"配置文件：{result['yaml_path']}")
        print(f"扫描报告：{result['report_path']}")


if __name__ == "__main__":
    main()
