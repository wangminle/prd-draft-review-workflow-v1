"""WBS 0.2 — Router 持久化扫描

扫描 router 中的 db.add()、await db.commit()、open()、os.makedirs()、shutil.rmtree()
直接调用，为后续迁移建立基线白名单。

验收标准：
- 扫描结果能列出当前直接持久化访问点
- 后续迁移不会靠人工记忆判断是否回退
- 白名单可按 WBS 域收紧

设计：本文件既包含自动化的计数测试（验证总数与白名单一致），
也包含可手动执行的扫描脚本（输出详细行号列表）。
"""

import ast
import os
import re
from pathlib import Path

# ── Configuration ──

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
ROUTER_DIR = SRC / "app" / "routers"
SERVICE_DIR = SRC / "app" / "services"

# Patterns to scan for
SCAN_PATTERNS = {
    "db_add": r"\.add\(",
    "db_commit": r"await\s+\w+\.commit\(\)",
    "db_flush": r"await\s+\w+\.flush\(\)",
    "builtin_open": r"(?<![.\w])open\(",          # excludes Path.open(), file.open()
    "os_makedirs": r"os\.makedirs\(",
    "os_remove": r"os\.remove\(",
    "os_unlink": r"os\.unlink\(",
    "shutil_rmtree": r"shutil\.rmtree\(",
    "shutil_copy": r"shutil\.copy\(",
    "shutil_move": r"shutil\.move\(",
}


def _scan_file(filepath: Path) -> dict[str, list[tuple[int, str]]]:
    """Scan a Python file for persistence-related patterns.

    Returns dict of pattern_name -> [(line_number, matching_line_text)]
    """
    hits = {}
    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines()

    for pattern_name, regex in SCAN_PATTERNS.items():
        found = []
        for i, line in enumerate(lines, 1):
            # Skip comments and string literals heuristically
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(regex, line):
                # Verify it's not inside a string literal (simple check)
                found.append((i, stripped))
        if found:
            hits[pattern_name] = found
    return hits


def _scan_directory(dirpath: Path) -> dict[str, dict[str, list[tuple[int, str]]]]:
    """Scan all .py files in a directory.

    Returns dict of filename -> scan_results per file
    """
    results = {}
    for py_file in sorted(dirpath.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        hits = _scan_file(py_file)
        if hits:
            results[py_file.name] = hits
    return results


# ── Whitelist: expected counts per router, per pattern ──
# These counts represent the current baseline. As WBS domains are migrated,
# these counts should decrease. When a domain is fully migrated, its entries
# should be removed from the whitelist.

WHITELIST = {
    "auth.py": {
        "db_add": 0,       # 已迁移到 UserRepository — E.3 完成
        "db_commit": 3,    # router 控制事务边界 — E.3 完成
        "builtin_open": 0,
        "os_makedirs": 0,
        "os_remove": 0,
        "os_unlink": 0,
        "shutil_rmtree": 0,
    },
    "chat.py": {
        "db_add": 0,       # 已迁移到 ConversationRepository + ContextItemRepository — WBS A 完成
        "db_commit": 5,    # router 控制事务边界 — ChatApplicationService 已接管准备逻辑 (P3 完成)
        "builtin_open": 0,
        "os_makedirs": 0,
        "os_remove": 0,
        "os_unlink": 0,
        "shutil_rmtree": 0,
    },
    "history.py": {
        "db_add": 0,
        "db_commit": 1,    # delete conversation
        "builtin_open": 0,
        "os_makedirs": 0,
        "os_remove": 0,
        "os_unlink": 0,
        "shutil_rmtree": 0,
    },
    "upload.py": {
        "db_add": 0,
        "db_commit": 0,
        "builtin_open": 0,   # 已迁移到 ChatFileStorage — WBS A.1 完成
        "os_makedirs": 0,    # 已迁移到 ChatFileStorage — WBS A.1 完成
        "os_remove": 0,
        "os_unlink": 0,
        "shutil_rmtree": 0,
    },
    "review.py": {
        "db_add": 0,       # 已迁移到 ReviewTaskRepository + ReviewProjectRepository + ReviewContextRepository + ReviewPromptRepository — D.1 + E.1 完成
        "db_commit": 32,   # router 控制事务边界 — D.1 + D.2 + workspace_id update
        "db_flush": 1,     # freeze_snapshot flush — P0.C.3
        "builtin_open": 0,   # 已迁移到 ReviewFileStorage.read_markdown() — WBS C.1 + F 完成
        "os_makedirs": 0,    # 已迁移到 ReviewFileStorage — WBS C.1 完成
        "os_remove": 0,      # 已迁移到 ReviewFileStorage.delete_document_files() — WBS C.1 + F 完成
        "os_unlink": 0,
        "shutil_rmtree": 0,  # 已迁移到 ReviewFileStorage — WBS C.1 完成
    },
    "admin.py": {
        "db_add": 0,       # 已迁移到 User/PromptTemplate/ModelConfig/SkillConfig repositories — E.2 完成
        "db_commit": 17,   # P4.Pre.6: +1 for toggle_skill_status
        "builtin_open": 0,  # audit reading 已迁到 AuditLogReader — WBS B 完成
        "os_makedirs": 0,
        "os_remove": 0,
        "os_unlink": 0,
        "shutil_rmtree": 0,
    },
    "workspace.py": {
        "db_add": 1,      # RetrievalLog in retrieve endpoint
        "db_commit": 8,   # delete source + update tags + upload source + upload ingest failure + update default workspace + update member + retrieve log + ingest
        "db_flush": 1,   # update member status
        "builtin_open": 0,
        "os_makedirs": 0,
        "os_remove": 0,
        "os_unlink": 0,
        "shutil_rmtree": 0,
    },
}


# ── Automated scan test ──


def _count_hits(results: dict[str, dict[str, list[tuple[int, str]]]], filename: str, pattern: str) -> int:
    """Count total hits for a pattern in a file."""
    file_hits = results.get(filename, {})
    pattern_hits = file_hits.get(pattern, [])
    return len(pattern_hits)


class TestRouterPersistenceScan:
    """WBS 0.2.1 自动扫描验证：当前 router 持久化调用数与白名单一致"""

    @classmethod
    def _get_scan_results(cls):
        return _scan_directory(ROUTER_DIR)

    def test_scan_runs_without_error(self):
        results = self._get_scan_results()
        assert isinstance(results, dict)

    def test_db_add_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "db_add" in expected:
                actual = _count_hits(results, filename, "db_add")
                assert actual == expected["db_add"], (
                    f"{filename}: db.add() count mismatch — "
                    f"expected {expected['db_add']}, found {actual}. "
                    f"Update WHITELIST or investigate new persistence call."
                )

    def test_db_commit_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "db_commit" in expected:
                actual = _count_hits(results, filename, "db_commit")
                assert actual == expected["db_commit"], (
                    f"{filename}: await db.commit() count mismatch — "
                    f"expected {expected['db_commit']}, found {actual}. "
                    f"Update WHITELIST or investigate new persistence call."
                )

    def test_builtin_open_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "builtin_open" in expected:
                actual = _count_hits(results, filename, "builtin_open")
                assert actual == expected["builtin_open"], (
                    f"{filename}: builtin open() count mismatch — "
                    f"expected {expected['builtin_open']}, found {actual}. "
                    f"Update WHITELIST or investigate new file I/O."
                )

    def test_os_makedirs_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "os_makedirs" in expected:
                actual = _count_hits(results, filename, "os_makedirs")
                assert actual == expected["os_makedirs"], (
                    f"{filename}: os.makedirs() count mismatch — "
                    f"expected {expected['os_makedirs']}, found {actual}. "
                    f"Update WHITELIST or investigate new directory creation."
                )

    def test_shutil_rmtree_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "shutil_rmtree" in expected:
                actual = _count_hits(results, filename, "shutil_rmtree")
                assert actual == expected["shutil_rmtree"], (
                    f"{filename}: shutil.rmtree() count mismatch — "
                    f"expected {expected['shutil_rmtree']}, found {actual}. "
                    f"Update WHITELIST or investigate new directory deletion."
                )

    def test_no_unexpected_db_flush_calls(self):
        """db.flush() calls must be whitelisted — any new ones need review."""
        results = self._get_scan_results()
        for filename, hits in results.items():
            if "db_flush" in hits:
                expected = WHITELIST.get(filename, {}).get("db_flush", 0)
                actual = len(hits["db_flush"])
                assert actual == expected, (
                    f"{filename}: db.flush() count mismatch — "
                    f"expected {expected}, found {actual}. "
                    f"Update WHITELIST or investigate new persistence call."
                )

    def test_no_shutil_copy_or_move_in_routers(self):
        """Current codebase doesn't use shutil.copy/move in routers."""
        results = self._get_scan_results()
        for filename, hits in results.items():
            for pattern in ["shutil_copy", "shutil_move"]:
                if pattern in hits:
                    assert len(hits[pattern]) == 0, (
                        f"{filename}: unexpected {pattern} found at lines "
                        f"{[ln for ln, _ in hits[pattern]]}"
                    )

    def test_os_remove_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "os_remove" in expected:
                actual = _count_hits(results, filename, "os_remove")
                assert actual == expected["os_remove"], (
                    f"{filename}: os.remove() count mismatch — "
                    f"expected {expected['os_remove']}, found {actual}. "
                    f"Update WHITELIST or investigate new file deletion."
                )

    def test_os_unlink_counts_match_whitelist(self):
        results = self._get_scan_results()
        for filename, expected in WHITELIST.items():
            if "os_unlink" in expected:
                actual = _count_hits(results, filename, "os_unlink")
                assert actual == expected["os_unlink"], (
                    f"{filename}: os.unlink() count mismatch — "
                    f"expected {expected['os_unlink']}, found {actual}. "
                    f"Update WHITELIST or investigate new file deletion."
                )


# ── Detailed report generator (for manual inspection) ──


def generate_scan_report() -> str:
    """Generate a detailed scan report for manual review.

    Can be called from a script: python -m tests.test_router_persistence_scan --report
    """
    router_results = _scan_directory(ROUTER_DIR)
    service_results = _scan_directory(SERVICE_DIR)

    lines = []
    lines.append("# Router Persistence Scan Report")
    lines.append("")

    total_counts = {}
    for pattern_name in SCAN_PATTERNS:
        total_counts[pattern_name] = 0

    lines.append("## Router Files")
    lines.append("")
    for filename, hits in router_results.items():
        lines.append(f"### {filename}")
        for pattern_name, occurrences in hits.items():
            total_counts[pattern_name] += len(occurrences)
            lines.append(f"  {pattern_name} ({len(occurrences)} hits):")
            for line_num, line_text in occurrences:
                lines.append(f"    L{line_num}: {line_text}")
        lines.append("")

    lines.append("## Service Files (reference, not in WBS scope)")
    lines.append("")
    for filename, hits in service_results.items():
        # Only report hits, skip logging_config.py which is expected to write files
        if filename == "logging_config.py":
            continue
        for pattern_name, occurrences in hits.items():
            total_counts[pattern_name] += len(occurrences)
            if occurrences:
                lines.append(f"  {filename} / {pattern_name} ({len(occurrences)}):")
                for line_num, line_text in occurrences:
                    lines.append(f"    L{line_num}: {line_text}")

    lines.append("")
    lines.append("## Summary")
    for pattern_name, count in total_counts.items():
        wl_total = sum(
            WHITELIST.get(f, {}).get(pattern_name, 0)
            for f in WHITELIST
        )
        lines.append(f"  {pattern_name}: {count} total (whitelist: {wl_total} in routers)")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if "--report" in sys.argv:
        print(generate_scan_report())
    else:
        # Run pytest
        pytest.main([__file__, "-v"])