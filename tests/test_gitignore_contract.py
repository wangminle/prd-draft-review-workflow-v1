"""`.gitignore` 关键规则契约测试。"""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _git_ignores(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def test_gitignore_blocks_runtime_data_and_local_secrets():
    assert _git_ignores("runtime/data/app.db")
    assert _git_ignores("runtime/logs/app.log")
    assert _git_ignores("runtime/uploads/sample.docx")
    assert _git_ignores("runtime/config/ui-branding.yaml")
    assert _git_ignores("runtime/config/ui-branding.scan-report.md")
    assert _git_ignores(".claude/settings.local.json")
    assert _git_ignores(".env.local")
    assert _git_ignores("node_modules/foo")
    assert _git_ignores("htmlcov/index.html")
    assert _git_ignores("poc-a/results/fts5_baseline.db")
    assert _git_ignores("docs/2-discussion/scratch.md_480321")


def test_gitignore_allows_runtime_templates():
    assert not _git_ignores("runtime/README.md")
    assert not _git_ignores("runtime/config/ui-branding.example.yaml")
    assert not _git_ignores(".env.example")
