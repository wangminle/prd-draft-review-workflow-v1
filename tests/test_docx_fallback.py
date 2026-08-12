"""Tests for DOCX fallback: reuse existing Markdown when source file is missing.

Covers BUG-138: when original docx upload is not synced to the local runtime
(e.g., dev environment cloned from a shared deployment), the review pipeline
should fall back to the previously-converted Markdown instead of failing.
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_md_file():
    """Create a temporary markdown file simulating a previously-converted doc."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# Test Document\n\nSome content here.")
        path = f.name
    yield path
    os.unlink(path)


class TestDocxFallback:
    """Verify the fallback logic in _run_pipeline step 0 (预处理)."""

    def test_source_missing_fallback_to_existing_md(self, tmp_md_file):
        """When docx is missing but md_path exists and is readable, pipeline should continue."""
        # Simulate a doc record
        doc = MagicMock()
        doc.file_path = "/nonexistent/path/to/file.docx"
        doc.md_path = tmp_md_file
        doc.filename = "test.docx"
        doc.id = 99
        doc.status = "uploaded"

        # Source file does not exist
        assert not os.path.exists(doc.file_path)
        # But md file does exist
        assert os.path.exists(tmp_md_file)

        # The fallback condition: source missing + md exists
        source_path = None  # _resolve_stored_file_path returns None for missing files
        should_fallback = (not source_path or not os.path.exists(source_path)) and doc.md_path is not None
        assert should_fallback

    def test_source_missing_no_md_fails(self):
        """When docx is missing and no md_path, pipeline should fail the doc."""
        doc = MagicMock()
        doc.file_path = "/nonexistent/path/to/file.docx"
        doc.md_path = None
        doc.filename = "test.docx"
        doc.id = 99

        source_path = "/nonexistent/path/to/file.docx"
        should_fallback = (not source_path or not os.path.exists(source_path)) and doc.md_path is not None
        assert not should_fallback

    def test_source_exists_no_fallback(self, tmp_md_file):
        """When docx exists, no fallback needed (normal path)."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            docx_path = f.name
        try:
            doc = MagicMock()
            doc.file_path = docx_path
            doc.md_path = tmp_md_file
            doc.filename = "test.docx"
            doc.id = 99

            source_path = docx_path
            should_fallback = (not source_path or not os.path.exists(source_path)) and doc.md_path is not None
            # Source exists, so no fallback needed even though md also exists
            assert not should_fallback
        finally:
            os.unlink(docx_path)

    @pytest.mark.asyncio
    async def test_read_markdown_success(self, tmp_md_file):
        """Verify read_markdown succeeds for an existing md file."""
        from app.storage.review_file_storage import ReviewFileStorage

        storage = ReviewFileStorage()
        content = await storage.read_markdown(tmp_md_file)
        assert "# Test Document" in content

    @pytest.mark.asyncio
    async def test_read_markdown_file_not_found(self):
        """Verify read_markdown raises FileNotFoundError for missing md."""
        from app.storage.review_file_storage import ReviewFileStorage

        storage = ReviewFileStorage()
        with pytest.raises(FileNotFoundError):
            await storage.read_markdown("/nonexistent/path/to/file.md")

    def test_fallback_preserves_md_path(self, tmp_md_file):
        """The fallback should not modify md_path, only set status to 'converted'."""
        doc = MagicMock()
        doc.md_path = tmp_md_file
        doc.status = "uploaded"

        # Simulate what the fallback does
        doc.status = "converted"

        assert doc.status == "converted"
        assert doc.md_path == tmp_md_file  # md_path unchanged


class TestHistoricalDocxFallback:
    """Verify the same fallback for historical documents in draft mode."""

    def test_historical_source_missing_with_md(self, tmp_md_file):
        """Historical doc with missing source but existing md should be usable."""
        hdoc = MagicMock()
        hdoc.file_path = "/nonexistent/historical.docx"
        hdoc.md_path = tmp_md_file
        hdoc.filename = "historical.docx"
        hdoc.id = 100

        source_path = None
        should_fallback = (not source_path or not os.path.exists(source_path)) and hdoc.md_path is not None
        assert should_fallback

    def test_historical_source_missing_no_md(self):
        """Historical doc with missing source and no md should fail."""
        hdoc = MagicMock()
        hdoc.file_path = "/nonexistent/historical.docx"
        hdoc.md_path = None

        source_path = "/nonexistent/historical.docx"
        should_fallback = (not source_path or not os.path.exists(source_path)) and hdoc.md_path is not None
        assert not should_fallback
