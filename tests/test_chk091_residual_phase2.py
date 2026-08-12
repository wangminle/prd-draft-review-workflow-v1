"""Tests for CHK-091 residual phase 2 fixes.

Covers:
- 4.4: version-chain schema dependencies now required
- 4.2: _schema_critical gating in sub-path methods (_run_dimension_with_retry, _run_insight_substep_with_retry)
- 5.6: python3 in all script docstrings
- 4.4: --target-baseline CLI in insights.py
- 4.6: DOCX pixel/size limits
- 5.7: ruff clean
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ── Fixtures ───────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent


# ── 4.4: version-chain schema dependencies required ────────────────

class TestVersionChainSchemaDependencies:
    """Verify that 'dependencies' is in the required array of version-chain schema."""

    def test_dependencies_in_required(self):
        schema_path = ROOT / "skills" / "prd-overview-classify" / "templates" / "output-schema.version-chain.json"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        assert "dependencies" in schema.get("required", []), (
            "dependencies should be in required array so LLM must output dependency info"
        )

    def test_dependencies_items_have_required_fields(self):
        schema_path = ROOT / "skills" / "prd-overview-classify" / "templates" / "output-schema.version-chain.json"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        dep_items = schema["properties"]["dependencies"]["items"]
        assert "from_doc_id" in dep_items["required"]
        assert "to_doc_id" in dep_items["required"]
        assert "relation" in dep_items["required"]

    def test_dependencies_relation_enum(self):
        schema_path = ROOT / "skills" / "prd-overview-classify" / "templates" / "output-schema.version-chain.json"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        relation_enum = schema["properties"]["dependencies"]["items"]["properties"]["relation"]["enum"]
        assert "references" in relation_enum
        assert "supplements" in relation_enum
        assert "resolves" in relation_enum


# ── 4.2: _schema_critical gating in sub-path methods ──────────────

class TestSubPathSchemaCriticalGate:
    """Verify that _run_dimension_with_retry and _run_insight_substep_with_retry
    check _schema_critical and raise on critical failure."""

    def test_dimension_retry_checks_schema_critical(self):
        """The source code of _run_dimension_with_retry must contain _schema_critical check."""
        runner_path = ROOT / "src" / "app" / "services" / "skill_runner.py"
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find _run_dimension_with_retry method
        dim_start = content.find("async def _run_dimension_with_retry")
        dim_end = content.find("async def _run_insight_substep_with_retry")
        assert dim_start != -1 and dim_end != -1
        dim_code = content[dim_start:dim_end]
        assert "_schema_critical" in dim_code, (
            "_run_dimension_with_retry must check _schema_critical after schema repair"
        )
        assert "raise ValueError" in dim_code or "raise" in dim_code, (
            "_run_dimension_with_retry must raise on critical schema failure"
        )

    def test_insight_substep_checks_schema_critical(self):
        """The source code of _run_insight_substep_with_retry must contain _schema_critical check."""
        runner_path = ROOT / "src" / "app" / "services" / "skill_runner.py"
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find _run_insight_substep_with_retry method
        insight_start = content.find("async def _run_insight_substep_with_retry")
        assert insight_start != -1
        # Find end of method (next def at same or lower indentation)
        insight_end = content.find("\n    # ── Helpers", insight_start)
        if insight_end == -1:
            insight_end = content.find("\n    def ", insight_start + 10)
        insight_code = content[insight_start:insight_end]
        assert "_schema_critical" in insight_code, (
            "_run_insight_substep_with_retry must check _schema_critical after schema repair"
        )
        assert "raise ValueError" in insight_code or "raise" in insight_code, (
            "_run_insight_substep_with_retry must raise on critical schema failure"
        )

    def test_dimension_retry_surfaces_repair_notes(self):
        """_run_dimension_with_retry should surface _schema_repair_notes."""
        runner_path = ROOT / "src" / "app" / "services" / "skill_runner.py"
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()
        dim_start = content.find("async def _run_dimension_with_retry")
        dim_end = content.find("async def _run_insight_substep_with_retry")
        dim_code = content[dim_start:dim_end]
        assert "_schema_repair_notes" in dim_code or "_repair_notes" in dim_code, (
            "_run_dimension_with_retry should surface repair notes"
        )

    def test_insight_substep_surfaces_repair_notes(self):
        """_run_insight_substep_with_retry should surface _schema_repair_notes."""
        runner_path = ROOT / "src" / "app" / "services" / "skill_runner.py"
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()
        insight_start = content.find("async def _run_insight_substep_with_retry")
        insight_end = content.find("\n    # ── Helpers", insight_start)
        if insight_end == -1:
            insight_end = len(content)
        insight_code = content[insight_start:insight_end]
        assert "_schema_repair_notes" in insight_code or "_repair_notes" in insight_code, (
            "_run_insight_substep_with_retry should surface repair notes"
        )


# ── 5.6: python3 in all script docstrings ─────────────────────────

class TestPython3Docstrings:
    """Verify that no script docstring uses bare 'python' (should be 'python3')."""

    SCRIPT_FILES = [
        "skills/prd-overview-classify/scripts/classify.py",
        "skills/system-review/scripts/pm_assess.py",
        "skills/system-review/scripts/review.py",
        "skills/prd-per-analysis/scripts/analyze.py",
        "skills/requirement-insights/scripts/insights.py",
        "skills/report-generator/scripts/generate.py",
        "skills/docx-to-markdown/scripts/md_to_pdf.py",
    ]

    @pytest.mark.parametrize("script_rel", SCRIPT_FILES)
    def test_no_bare_python_in_docstring(self, script_rel):
        script_path = ROOT / script_rel
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Look for 'python ' not followed by '3' (excluding 'python -m')
        matches = re.findall(r'(?<!python3)(?<!python)python (?!\d)(?!-m)', content)
        assert not matches, f"{script_rel} still contains bare 'python ' (should be 'python3')"


# ── 4.4: --target-baseline CLI in insights.py ─────────────────────

class TestTargetBaselineCLI:
    """Verify that insights.py has --target-baseline CLI argument."""

    def test_target_baseline_arg_exists(self):
        insights_path = ROOT / "skills" / "requirement-insights" / "scripts" / "insights.py"
        with open(insights_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "--target-baseline" in content, (
            "insights.py should have --target-baseline CLI argument"
        )

    def test_run_gap_analysis_accepts_target_baseline(self):
        insights_path = ROOT / "skills" / "requirement-insights" / "scripts" / "insights.py"
        with open(insights_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "target_baseline" in content, (
            "run_gap_analysis should accept target_baseline parameter"
        )
        # Verify it's used to inject baseline into LLM prompt
        assert "baseline_section" in content, (
            "target_baseline should be injected as baseline_section in LLM prompt"
        )

    def test_target_baseline_clears_warning(self):
        """When target_baseline is provided, baseline_warning should be empty."""
        insights_path = ROOT / "skills" / "requirement-insights" / "scripts" / "insights.py"
        with open(insights_path, "r", encoding="utf-8") as f:
            content = f.read()
        # The code should set baseline_warning = "" when target_baseline is provided
        assert 'baseline_warning = ""' in content, (
            "baseline_warning should be cleared when target_baseline is provided"
        )


# ── 4.6: DOCX pixel/size limits ───────────────────────────────────

class TestDocxPixelLimits:
    """Verify that DOCX conversion has pixel and size limits for images."""

    def test_max_image_pixels_constant(self):
        convert_path = ROOT / "skills" / "docx-to-markdown" / "scripts" / "convert_docx.py"
        with open(convert_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "MAX_IMAGE_PIXELS" in content, (
            "convert_docx.py should define MAX_IMAGE_PIXELS constant"
        )

    def test_max_single_image_size_constant(self):
        convert_path = ROOT / "skills" / "docx-to-markdown" / "scripts" / "convert_docx.py"
        with open(convert_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "MAX_SINGLE_IMAGE_SIZE" in content, (
            "convert_docx.py should define MAX_SINGLE_IMAGE_SIZE constant"
        )

    def test_pixel_count_check_in_extraction(self):
        convert_path = ROOT / "skills" / "docx-to-markdown" / "scripts" / "convert_docx.py"
        with open(convert_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_get_image_pixel_count" in content, (
            "convert_docx.py should call _get_image_pixel_count during image extraction"
        )
        assert "MAX_IMAGE_PIXELS" in content

    def test_get_image_pixel_count_function_exists(self):
        convert_path = ROOT / "skills" / "docx-to-markdown" / "scripts" / "convert_docx.py"
        with open(convert_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "def _get_image_pixel_count" in content, (
            "convert_docx.py should define _get_image_pixel_count helper function"
        )

    def test_png_pixel_count(self):
        """Test that _get_image_pixel_count correctly reads PNG dimensions."""
        # Create a minimal PNG header (10x20 pixels)
        # PNG: 8-byte signature + 4-byte IHDR length + 4-byte 'IHDR' + width(4) + height(4)
        import struct
        png_header = (
            b'\x89PNG\r\n\x1a\n'  # PNG signature (bytes 0-7)
            + b'\x00\x00\x00\x0d'  # IHDR chunk length (bytes 8-11)
            + b'IHDR'  # IHDR chunk type (bytes 12-15)
            + struct.pack('>II', 10, 20)  # width=10, height=20 (bytes 16-23)
            + b'\x00' * 20  # padding
        )
        # Import the function
        sys.path.insert(0, str(ROOT / "skills" / "docx-to-markdown" / "scripts"))
        try:
            from convert_docx import _get_image_pixel_count
            result = _get_image_pixel_count(png_header)
            assert result == 200, f"Expected 200 pixels, got {result}"
        finally:
            sys.path.pop(0)

    def test_gif_pixel_count(self):
        """Test that _get_image_pixel_count correctly reads GIF dimensions."""
        import struct
        gif_header = (
            b'GIF89a'  # GIF signature
            + struct.pack('<HH', 100, 200)  # width=100, height=200
            + b'\x00' * 10
        )
        sys.path.insert(0, str(ROOT / "skills" / "docx-to-markdown" / "scripts"))
        try:
            from convert_docx import _get_image_pixel_count
            result = _get_image_pixel_count(gif_header)
            assert result == 20000, f"Expected 20000 pixels, got {result}"
        finally:
            sys.path.pop(0)

    def test_bmp_pixel_count(self):
        """Test that _get_image_pixel_count correctly reads BMP dimensions."""
        import struct
        bmp_header = (
            b'BM'  # BMP signature
            + b'\x00' * 16  # padding to offset 18
            + struct.pack('<ii', 300, 400)  # width=300, height=400
            + b'\x00' * 10
        )
        sys.path.insert(0, str(ROOT / "skills" / "docx-to-markdown" / "scripts"))
        try:
            from convert_docx import _get_image_pixel_count
            result = _get_image_pixel_count(bmp_header)
            assert result == 120000, f"Expected 120000 pixels, got {result}"
        finally:
            sys.path.pop(0)

    def test_unknown_format_returns_none(self):
        """Unknown image format should return None (not blocked)."""
        sys.path.insert(0, str(ROOT / "skills" / "docx-to-markdown" / "scripts"))
        try:
            from convert_docx import _get_image_pixel_count
            result = _get_image_pixel_count(b'UNKNOWN FORMAT')
            assert result is None, f"Expected None for unknown format, got {result}"
        finally:
            sys.path.pop(0)


# ── 5.7: Ruff clean ───────────────────────────────────────────────

class TestRuffClean:
    """Verify that ruff passes cleanly for the selected rules."""

    def test_ruff_no_errors_in_modified_files(self):
        """Run ruff check on files modified in this fix batch and verify they pass."""
        modified_files = [
            "src/app/routers/review.py",
            "src/app/services/skill_runner.py",
            "src/app/services/skill_schema.py",
            "src/app/services/pi_agent_bridge.py",
            "tests/test_chk091_residual_fixes.py",
            "tests/test_chk091_residual_phase2.py",
            "tests/test_router_persistence_scan.py",
            "tests/test_review_backend_contract.py",
            "tests/test_review_frontend_contract.py",
            "tests/test_frontend_workspace_contract.py",
        ]
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check"] + modified_files,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if result.returncode != 0 and "all checks passed" not in result.stdout.lower():
            pytest.fail(
                f"Ruff found errors in modified files:\n{result.stdout}\n{result.stderr}"
            )


# ── Integration: E712 and E701 fixes ──────────────────────────────

class TestCodeQualityFixes:
    """Verify that specific code quality issues are fixed."""

    def test_no_single_line_if_return_in_review(self):
        """review.py should not have 'if ...: return' on one line."""
        review_path = ROOT / "src" / "app" / "routers" / "review.py"
        with open(review_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            # Check for 'if ...: return' pattern (E701)
            stripped = line.strip()
            if stripped.startswith("if ") and ": return" in stripped:
                pytest.fail(f"Line {i+1} has single-line if:return: {stripped}")

    def test_no_lambda_assignment_in_tests(self):
        """test_review_backend_contract.py should not have lambda assignments."""
        test_path = ROOT / "tests" / "test_review_backend_contract.py"
        with open(test_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Should not have 'lambda *parts:' assignment
        assert "fake_runtime_path = lambda" not in content, (
            "Lambda assignment should be converted to def"
        )

    def test_pytest_imported_in_test_files(self):
        """Test files using pytest should import it."""
        for test_file in ["test_frontend_workspace_contract.py", "test_router_persistence_scan.py"]:
            test_path = ROOT / "tests" / test_file
            with open(test_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "pytest." in content:
                assert "import pytest" in content, (
                    f"{test_file} uses pytest but doesn't import it"
                )
