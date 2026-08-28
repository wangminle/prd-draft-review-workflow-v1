"""Tests for CHK-091 residual phase 3 fixes (sub-agent review residuals).

Covers 4 issues identified in the sub-agent re-review:
- P1: DOCX security rejection must not fall back to mammoth (DocxSecurityError)
- P1: Classification failure must abort the pipeline
- P1: Cached SystemReview must restore review_dimensions_meta (partial status)
- P2: Cache without _source_content_hash must be invalidated (fail-closed)
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
SRC_DIR = ROOT / "src"


# ── P1: DocxSecurityError ──────────────────────────────────────────

class TestDocxSecurityError:
    """Verify that DocxSecurityError exists and is used for security rejections."""

    def test_docx_security_error_class_exists(self):
        """DocxSecurityError should be defined in convert_docx.py."""
        convert_path = SKILLS_DIR / "docx-to-markdown" / "scripts" / "convert_docx.py"
        with open(convert_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "class DocxSecurityError" in content, (
            "DocxSecurityError class should be defined in convert_docx.py"
        )

    def test_docx_security_error_inherits_value_error(self):
        """DocxSecurityError should inherit from ValueError for backward compat."""
        sys.path.insert(0, str(SKILLS_DIR / "docx-to-markdown" / "scripts"))
        try:
            from convert_docx import DocxSecurityError
            assert issubclass(DocxSecurityError, ValueError)
        finally:
            sys.path.pop(0)

    def test_security_checks_raise_docx_security_error(self):
        """validate_docx_zip_security should raise DocxSecurityError, not plain ValueError."""
        sys.path.insert(0, str(SKILLS_DIR / "docx-to-markdown" / "scripts"))
        try:
            from convert_docx import DocxSecurityError

            assert issubclass(DocxSecurityError, ValueError)

            src = (SKILLS_DIR / "docx-to-markdown" / "scripts" / "convert_docx.py").read_text()
            # The zip security checks (entry size / compression ratio / total
            # uncompressed size) must raise DocxSecurityError, never a plain
            # ValueError. ResourceLimitExceeded raises are also DocxSecurityError.
            assert src.count("raise DocxSecurityError(") >= 3, (
                "validate_docx_zip_security should raise DocxSecurityError for all security checks"
            )
        finally:
            sys.path.pop(0)

    def test_storage_maps_worker_security_rejection_to_failure(self):
        """存储层必须把工作进程的安全拒绝映射为失败，而不是发布产物。"""
        storage_path = SRC_DIR / "app" / "storage" / "review_file_storage.py"
        content = storage_path.read_text(encoding="utf-8")
        assert 'error_type == "DocxSecurityError"' in content
        assert "DOCX 安全拒绝" in content

    def test_storage_has_conversion_timeout(self):
        """review_file_storage.py should have a timeout on the conversion call."""
        storage_path = SRC_DIR / "app" / "storage" / "review_file_storage.py"
        content = storage_path.read_text(encoding="utf-8")
        assert "asyncio.wait_for" in content, (
            "Should use asyncio.wait_for to set a conversion timeout"
        )
        assert "timeout=120" in content or "timeout=" in content, (
            "Should specify a timeout value"
        )

    def test_security_error_is_serialized_by_worker(self):
        """工作进程必须保留异常类型，供主进程识别安全拒绝。"""
        worker_path = SRC_DIR / "app" / "storage" / "docx_conversion_worker.py"
        content = worker_path.read_text(encoding="utf-8")
        assert '"error_type": type(exc).__name__' in content


# ── P1: Classification failure aborts pipeline ─────────────────────

class TestClassifyFailureAborts:
    """Verify that classification and version-chain failures abort the pipeline."""

    def test_review_py_checks_classify_is_error(self):
        """review.py should check classify_result.is_error after run_skill."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        assert "classify_result.is_error" in content, (
            "Should check classify_result.is_error to detect classification failure"
        )

    def test_review_py_checks_version_chain_is_error(self):
        """review.py should check version_chain_result.is_error."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        assert "version_chain_result.is_error" in content, (
            "Should check version_chain_result.is_error to detect version chain failure"
        )

    def test_review_py_raises_on_classify_failure(self):
        """review.py should raise RuntimeError when classification fails."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        assert "分类步骤失败" in content or "classify" in content.lower(), (
            "Should raise RuntimeError with classification failure message"
        )

    def test_review_py_raises_on_version_chain_failure(self):
        """review.py should raise RuntimeError when version chain fails."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        assert "版本链分析失败" in content, (
            "Should raise RuntimeError with version chain failure message"
        )

    def test_classify_error_check_before_classifications_extract(self):
        """The is_error check must come BEFORE extracting classifications."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        error_check_pos = content.find("classify_result.is_error")
        classifications_pos = content.find('classify_result.data.get("classifications"')
        assert error_check_pos > 0, "is_error check not found"
        assert classifications_pos > 0, "classifications extraction not found"
        assert error_check_pos < classifications_pos, (
            "is_error check must come BEFORE extracting classifications from result"
        )

    def test_empty_classification_list_is_rejected(self):
        from app.routers.review import _require_classification_coverage

        with pytest.raises(RuntimeError, match="未返回任何有效分类结果"):
            _require_classification_coverage([], [101])

    def test_missing_doc_classification_is_rejected(self):
        from app.routers.review import _require_classification_coverage

        with pytest.raises(RuntimeError, match="102"):
            _require_classification_coverage(
                [{"doc_id": "101", "category": "需求池", "confidence": 0.9}],
                [101, 102],
            )


# ── P1: Cached SystemReview restores dimensions_meta ───────────────

class TestCachedDimensionsMeta:
    """Verify that cached SystemReview restores review_dimensions_meta."""

    def test_system_review_model_has_dimensions_meta(self):
        """SystemReview model should have a dimensions_meta column."""
        review_model_path = SRC_DIR / "app" / "models" / "review.py"
        content = review_model_path.read_text(encoding="utf-8")
        assert "dimensions_meta" in content, (
            "SystemReview model should have dimensions_meta column"
        )

    def test_system_review_payload_has_dimensions_meta(self):
        """SystemReviewPayload should have a dimensions_meta field."""
        repo_path = SRC_DIR / "app" / "repositories" / "review_task_repository.py"
        content = repo_path.read_text(encoding="utf-8")
        assert "dimensions_meta" in content, (
            "SystemReviewPayload should include dimensions_meta field"
        )

    def test_database_migration_adds_dimensions_meta(self):
        """database.py should have migration for dimensions_meta column."""
        db_path = SRC_DIR / "app" / "database.py"
        content = db_path.read_text(encoding="utf-8")
        assert "dimensions_meta" in content, (
            "database.py should have ALTER TABLE migration for dimensions_meta"
        )

    def test_save_system_review_passes_dimensions_meta(self):
        """save_system_review should pass dimensions_meta from payload to model."""
        repo_path = SRC_DIR / "app" / "repositories" / "review_task_repository.py"
        content = repo_path.read_text(encoding="utf-8")
        assert "dimensions_meta=payload.dimensions_meta" in content, (
            "save_system_review should map dimensions_meta from payload"
        )

    def test_review_py_saves_dimensions_meta_on_fresh_run(self):
        """review.py should persist dimensions_meta when saving fresh SystemReview."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        assert "dimensions_meta=_sr_meta_json" in content, (
            "Fresh SystemReview save should include dimensions_meta"
        )

    def test_review_py_restores_dimensions_meta_from_cache(self):
        """Cache helper should restore persisted meta verbatim when present."""
        from app.routers.review import _restore_cached_review_dimensions_meta

        cached_sr = SimpleNamespace(
            dimensions_meta=json.dumps({
                "dimensions_executed": ["business-value"],
                "dimensions_failed": ["competition"],
                "total": 7,
                "success_count": 1,
                "failed_count": 1,
                "status": "partial",
            }, ensure_ascii=False)
        )

        meta = _restore_cached_review_dimensions_meta(cached_sr, {"competition": {"error": "boom"}})

        assert meta["status"] == "partial"
        assert meta["dimensions_failed"] == ["competition"]
        assert meta["dimensions_executed"] == ["business-value"]

    def test_review_py_cached_sr_passes_dimensions_meta(self):
        """Cached SystemReview save should forward dimensions_meta from cached source."""
        review_path = SRC_DIR / "app" / "routers" / "review.py"
        content = review_path.read_text(encoding="utf-8")
        assert "dimensions_meta=(" in content, (
            "Cached SR save should pass dimensions_meta from cached_sr"
        )

    def test_review_py_has_fallback_meta_reconstruction(self):
        """Cache helper should reconstruct partial meta from cached error dicts."""
        from app.routers.review import _restore_cached_review_dimensions_meta

        cached_sr = SimpleNamespace(dimensions_meta=None)
        meta = _restore_cached_review_dimensions_meta(
            cached_sr,
            {
                "business-value": {"summary": "ok"},
                "competition": {"error": "timeout"},
            },
        )

        assert meta["status"] == "partial"
        assert meta["dimensions_failed"] == ["competition"]
        assert meta["dimensions_executed"] == ["business-value"]


# ── P2: Cache without hash is fail-closed ──────────────────────────

class TestCacheHashFailClosed:
    """Verify that missing _source_content_hash invalidates the cache."""

    def test_review_py_checks_missing_hash(self):
        from app.routers.review import _analysis_cache_is_stale

        is_stale, reason = _analysis_cache_is_stale({"core_problem": "old"}, "abc123")

        assert is_stale is True
        assert "missing _source_content_hash" in reason

    def test_missing_hash_triggers_reanalyze(self):
        from app.routers.review import _analysis_cache_is_stale

        is_stale, reason = _analysis_cache_is_stale(
            {"_source_content_hash": "abc123"},
            None,
        )

        assert is_stale is True
        assert "missing current content_hash" in reason

    def test_hash_mismatch_still_works(self):
        from app.routers.review import _analysis_cache_is_stale

        is_stale, reason = _analysis_cache_is_stale(
            {"_source_content_hash": "abc123"},
            "xyz789",
        )

        assert is_stale is True
        assert "content hash changed" in reason

    def test_old_fail_open_logic_removed(self):
        from app.routers.review import _analysis_cache_is_stale

        is_stale, reason = _analysis_cache_is_stale(
            {"_source_content_hash": "abc123"},
            "abc123",
        )

        assert is_stale is False
        assert reason == ""
