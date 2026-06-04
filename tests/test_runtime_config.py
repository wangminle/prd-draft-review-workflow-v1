"""运行时配置与启动脚本回归测试。"""

import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))
os.environ.setdefault("RUNTIME_ROOT", str(RUNTIME_ROOT))

from app.config import _resolve_env, load_config
from app.logging_config import setup_logging
from app.runtime_paths import get_runtime_root, runtime_path


def test_resolve_env_generates_jwt_secret_when_missing(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)

    resolved = _resolve_env("${JWT_SECRET}")

    assert isinstance(resolved, str)
    assert len(resolved) == 64
    assert os.environ["JWT_SECRET"] == resolved


def test_dotenv_loaded_without_overriding_existing_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "preexisting-test-secret")

    settings = load_config(SRC / "config.yaml")

    assert settings["auth"]["secret_key"] == "preexisting-test-secret"


def test_start_script_sources_env_before_boot():
    script = (ROOT / "start.sh").read_text(encoding="utf-8")

    runtime_idx = script.index("export RUNTIME_ROOT=\"$RUNTIME_DIR\"")
    uvicorn_idx = script.index("PYTHONPATH=src nohup uvicorn src.main:app")

    assert runtime_idx < uvicorn_idx
    # start.sh loads .env from both project root and src/ via a loop
    assert "for env_file in" in script
    assert "$PROJECT_DIR/.env" in script
    assert "$PROJECT_DIR/src/.env" in script
    assert "if [ -z \"$JWT_SECRET\" ]; then" in script
    assert "RUNTIME_DIR=\"${RUNTIME_ROOT:-$PROJECT_DIR/runtime}\"" in script


def test_update_script_is_executable_and_syntax_valid():
    script_path = ROOT / "update.sh"

    assert script_path.exists()
    assert os.stat(script_path).st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(script_path)], check=True)


def test_update_script_never_auto_applies_branding_migration():
    script = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "--auto-apply" not in script
    assert "migrate_branding.py\" apply" not in script
    assert " scan " in script
    assert " plan " in script


def test_update_script_does_not_overwrite_task_list_from_package():
    script = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "task-list.md" not in script


def test_update_script_validates_package_before_replacing_code():
    script = (ROOT / "update.sh").read_text(encoding="utf-8")

    validate_idx = script.index("validate_update_package")
    replace_idx = script.index("更新代码文件")

    assert validate_idx < replace_idx
    assert "tar -tzf" in script
    assert "runtime/data" in script
    assert "runtime/uploads" in script
    assert "runtime/logs" in script


def test_update_script_restores_root_and_src_env_separately():
    script = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "project.env" in script
    assert "src.env" in script
    assert 'cp "$CURRENT_BACKUP_DIR/project.env" "$PROJECT_DIR/.env"' in script
    assert 'cp "$CURRENT_BACKUP_DIR/src.env" "$PROJECT_DIR/src/.env"' in script


def test_runtime_root_defaults_to_project_runtime():
    assert get_runtime_root() == RUNTIME_ROOT.resolve()
    assert runtime_path("logs") == (RUNTIME_ROOT / "logs").resolve()


def test_logging_defaults_to_project_runtime(monkeypatch):
    monkeypatch.setenv("RUNTIME_ROOT", str(RUNTIME_ROOT))

    assert setup_logging() == (RUNTIME_ROOT / "logs").resolve()


def test_load_config_points_runtime_paths_to_project_root(monkeypatch):
    monkeypatch.setenv("RUNTIME_ROOT", str(RUNTIME_ROOT))

    settings = load_config(SRC / "config.yaml")

    assert Path(settings["database"]["path"]) == (RUNTIME_ROOT / "data" / "app.db").resolve()
    assert Path(settings["upload"]["upload_dir"]) == (RUNTIME_ROOT / "uploads").resolve()
    assert Path(settings["review"]["upload"]["upload_dir"]) == (RUNTIME_ROOT / "data" / "review_uploads").resolve()
