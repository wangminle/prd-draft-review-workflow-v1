"""版本号单一事实来源测试。

版本号的唯一事实来源是项目根目录的 VERSION 纯文本文件：
  VERSION  ←  唯一事实来源（纯文本，发版只改这一个文件）
    ↑
  src/app/version.py  ←  读取入口，暴露 APP_VERSION
    ↑
  src/main.py / branding_config.py / mcp_adapter.py  ←  from app.version import APP_VERSION

shell 脚本（package.sh / update.sh）直接读 VERSION 文件（带旧结构回退）。
本测试锁死这条链路，防止版本号重新散落成多处硬编码。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"


def test_version_file_exists_and_pure():
    """VERSION 文件存在、非空、且只含版本号（无 APP_VERSION = 之类的赋值语法）。"""
    assert VERSION_FILE.exists(), "根目录缺少 VERSION 文件"
    content = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert content, "VERSION 文件为空"
    assert "=" not in content, f"VERSION 文件应只含版本号，不应有赋值语法: {content!r}"


def test_version_file_value():
    content = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert content == "0.3.11", f"VERSION 当前应为 0.3.11，实际 {content!r}"


def test_version_py_reads_version_file():
    """version.py 必须从 VERSION 文件读取，不得自带版本字面量。"""
    py = (ROOT / "src/app/version.py").read_text(encoding="utf-8")
    assert '"VERSION"' in py or "'VERSION'" in py, "version.py 应引用 VERSION 文件"
    # version.py 自身不得硬编码版本字面量
    import re
    assert not re.search(r'APP_VERSION\s*=\s*"\d', py), "version.py 不应硬编码版本号"


def test_main_imports_from_version_module():
    main_py = (ROOT / "src/main.py").read_text(encoding="utf-8")
    assert "from app.version import APP_VERSION" in main_py
    # main.py 不应再有 APP_VERSION 的字面量定义
    assert 'APP_VERSION = "' not in main_py, "main.py 不应硬编码 APP_VERSION 字面量"


def test_branding_uses_app_version():
    branding_py = (ROOT / "src/app/services/branding_config.py").read_text(encoding="utf-8")
    assert "from app.version import APP_VERSION" in branding_py
    assert '"app_version": APP_VERSION' in branding_py
    assert '"app_version": "0.' not in branding_py, "branding_config 不应硬编码版本号"


def test_mcp_adapter_uses_app_version():
    mcp_py = (ROOT / "src/app/services/mcp_adapter.py").read_text(encoding="utf-8")
    assert "from app.version import APP_VERSION" in mcp_py
    assert '"version": APP_VERSION' in mcp_py
    assert '"version": "0.' not in mcp_py, "mcp_adapter 不应硬编码版本号"


def test_runtime_app_version_constant_matches_version_file():
    """运行时从 version.py 读到的值必须与 VERSION 文件一致。"""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from app.version import APP_VERSION
    file_val = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert APP_VERSION == file_val, f"version.py({APP_VERSION!r}) != VERSION文件({file_val!r})"


def test_shell_scripts_read_version_file():
    """package.sh / update.sh 的版本提取应优先读 VERSION 文件。"""
    package_sh = (ROOT / "package.sh").read_text(encoding="utf-8")
    update_sh = (ROOT / "update.sh").read_text(encoding="utf-8")
    assert '"VERSION"' in package_sh or "'VERSION'" in package_sh, "package.sh 应读取 VERSION 文件"
    assert '"VERSION"' in update_sh or "'VERSION'" in update_sh, "update.sh 应读取 VERSION 文件"
