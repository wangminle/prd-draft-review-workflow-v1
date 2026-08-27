"""部署文档与 update.sh 版本口径契约测试（DOC-076/DOC-077 收口）。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_packaging_deployment_cn_uses_package_version_file():
    text = _read("docs/packaging-and-deployment.md")

    assert "与脚本内 `NEW_VERSION` 比较" not in text
    assert "解包后优先读取更新包内根目录 `VERSION` 文件" in text
    assert "`NEW_VERSION` 仅在包内读取失败时作为回退值" in text


def test_packaging_deployment_en_uses_package_version_file():
    text = _read("docs/packaging-and-deployment.md")

    assert "compares with the script's `NEW_VERSION`" not in text
    assert "both must be updated together" not in text
    assert "only a fallback when reading the package fails" in text
    assert "reads the package's root `VERSION` file first" in text


def test_packaging_deployment_en_faq_syncs_package_json():
    text = _read("docs/packaging-and-deployment.md")

    assert "`update.sh` doesn't sync `package.json`" not in text
    assert "syncs `package.json` and `package-lock.json` but does not run `npm install` automatically" in text


def test_troubleshooting_cn_uses_version_file_only():
    text = _read("docs/troubleshooting.md")

    assert "未同步 `src/main.py` 的 `version` 与 `update.sh` 的 `NEW_VERSION`" not in text
    assert "发布前未更新根目录 `VERSION` 文件" in text


def test_troubleshooting_en_uses_version_file_only():
    text = _read("docs/troubleshooting.md")

    assert "`NEW_VERSION` in `update.sh` were not bumped together" not in text
    assert "the root `VERSION` file was not bumped before release" in text


def test_troubleshooting_syncs_package_json_but_not_npm_install():
    text = _read("docs/troubleshooting.md")

    assert "不会同步 `package.json`" not in text
    assert "does not sync `package.json`" not in text
    assert "会同步 `package.json` 和 `package-lock.json`" in text
    assert "syncs `package.json` and `package-lock.json` but does not run `npm install` automatically" in text


def test_configuration_jwt_token_hex_is_64_chars_not_128():
    text = _read("docs/configuration.md")

    assert "64 字节十六进制,128 字符" not in text
    assert "64-byte hex, 128 chars" not in text
    assert "128 字符随机串" not in text
    assert "128-char random string" not in text
    assert "64 个十六进制字符" in text
    assert "64 hex characters" in text


def test_configuration_jwt_empty_is_not_hard_fail():
    text = _read("docs/configuration.md")

    assert "1. **空值** —— 未配置或纯空白。" not in text
    assert "1. **Empty** — unset or whitespace-only." not in text
    assert "走官方脚本不会因空值失败" in text
    assert "the official script does not fail on empty" in text
    assert "进程内临时密钥" in text
    assert "in-process ephemeral secret" in text


def test_troubleshooting_jwt_empty_does_not_claim_refuse():
    text = _read("docs/troubleshooting.md")

    assert "空值本身不会拒绝启动" in text
    assert "An empty value does not refuse startup" in text
    assert "且未走 `./start.sh` 的自动写入" not in text
    assert "and you did not start via `./start.sh` which auto-writes it" not in text


def test_security_jwt_empty_matches_start_script():
    text = _read("docs/security.md")

    assert "空值或纯空白" not in text
    assert "empty or whitespace-only value" not in text
    assert "空值不会拒绝启动" in text
    assert "An empty value does not refuse startup" in text


def test_update_script_compares_package_version_not_const():
    script = _read("update.sh")

    assert 'log "目标版本: $NEW_VERSION"' not in script
    assert '[ "$CURRENT_VERSION" = "$PACKAGE_VERSION" ]' in script
    assert '${PACKAGE_VERSION:-$NEW_VERSION}' in script
    assert 'vf = root / "VERSION"' in script


def _version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_user_facing_docs_quote_current_version():
    """发版后 README/健康检查示例/顶栏兜底必须跟 VERSION 走，避免再停在上一版。"""
    ver = _version()
    checks = [
        ("README.md", f"当前版本 V{ver}"),
        ("README.md", f"Current version V{ver}"),
        ("docs/getting-started.md", f'"version":"{ver}"'),
        ("docs/troubleshooting.md", f'"version":"{ver}"'),
        ("docs/api-reference.md", f'"version":"{ver}"'),
        ("docs/packaging-and-deployment.md", f"V{ver}"),
        ("src/static/index.html", f"Ver. {ver}"),
        ("runtime/config/ui-branding.example.yaml", f'app_version: "{ver}"'),
        ("update.sh", f'NEW_VERSION="{ver}"'),
        ("package.json", f'"version": "{ver}"'),
    ]
    for rel, needle in checks:
        assert needle in _read(rel), f"{rel} missing {needle!r}"


def test_configuration_retry_defaults_match_config_yaml():
    text = _read("docs/configuration.md")
    assert "| `max_attempts` | `7` |" in text
    assert "| `max_delay_ms` | `64000` |" in text
    assert "| `max_attempts` | `5` |" not in text
    assert "| `max_delay_ms` | `30000` |" not in text
    troubleshoot = _read("docs/troubleshooting.md")
    assert "max_attempts: 7" in troubleshoot
    assert "max_attempts: 5" not in troubleshoot


def test_pi_agent_docs_cover_unsaved_temp_config():
    admin = _read("docs/admin-guide.md")
    api = _read("docs/api-reference.md")
    assert "config_saved" in admin
    assert "尚未保存" in admin
    assert "config_saved" in api


def test_packaging_docs_pip_not_uv_lock():
    text = _read("docs/packaging-and-deployment.md")
    assert "`uv.lock`" in text
    assert "requirements.txt" in text
    assert "uv sync" in text


def test_user_guide_covers_katex_and_svg():
    text = _read("docs/user-guide.md")
    assert "KaTeX" in text
    assert r"\ce{}" in text
    assert "SVG" in text
