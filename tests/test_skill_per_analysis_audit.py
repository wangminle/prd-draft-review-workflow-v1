"""Tests for P1-4.5: prd-per-analysis doc_id injection + follow-up context + cache."""

import json
import os
import sys
from pathlib import Path



ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "skills"
sys.path.insert(0, str(SKILLS / "prd-per-analysis" / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "src" / "config.yaml"))


def test_fill_prompt_placeholders_replaces_all_known_vars():
    import analyze as analyze_mod
    template = """
    - doc_id: {{doc_id}}
    - category: {{category}}
    - version: {{version}}
    - image_descriptions: {{image_descriptions}}
    - md_content: {{md_content}}  # NOT filled (provided via user_msg)
    """
    filled = analyze_mod._fill_prompt_placeholders(
        template, doc_id="doc_123", category="核心策略",
        version="V2.0", image_descriptions="无图片"
    )
    assert "doc_123" in filled
    assert "核心策略" in filled
    assert "V2.0" in filled
    assert "无图片" in filled
    # md_content placeholder must remain unfilled (large content goes in user_msg)
    assert "{{md_content}}" in filled
    # Original placeholders (other than md_content) must be gone
    assert "{{doc_id}}" not in filled
    assert "{{category}}" not in filled
    assert "{{version}}" not in filled
    assert "{{image_descriptions}}" not in filled


def test_fill_prompt_placeholders_handles_empty_template():
    import analyze as analyze_mod
    assert analyze_mod._fill_prompt_placeholders("", "x", "y", "z", "w") == ""


def test_fill_prompt_placeholders_handles_missing_values():
    import analyze as analyze_mod
    filled = analyze_mod._fill_prompt_placeholders(
        "{{doc_id}} {{category}}", "", "", "", ""
    )
    assert "（未提供）" in filled
    assert "未分类" in filled


def test_batch_analyze_cache_key_includes_review_context_version(tmp_path):
    """When review_context_version changes, the cache hash must change."""
    import batch_analyze as ba_mod

    md_path = tmp_path / "doc.md"
    md_path.write_text("hello world", encoding="utf-8")

    hash_v1 = ba_mod.compute_content_hash(md_path, "fake-model", review_context_version="v1")
    hash_v2 = ba_mod.compute_content_hash(md_path, "fake-model", review_context_version="v2")
    hash_empty = ba_mod.compute_content_hash(md_path, "fake-model", review_context_version="")

    assert hash_v1 != hash_v2, "Different review_context_version must produce different hash"
    assert hash_v1 != hash_empty, "Non-empty context version must differ from empty"
    assert hash_v2 != hash_empty


def test_batch_analyze_cache_invalidated_when_review_context_changes(tmp_path):
    """An existing cache file with old review_context_version must be invalid."""
    import batch_analyze as ba_mod

    md_path = tmp_path / "doc.md"
    md_path.write_text("content", encoding="utf-8")

    # Write a cache file with hash for context version "v1"
    old_hash = ba_mod.compute_content_hash(md_path, "fake-model", "v1")
    cache_path = tmp_path / "doc1.json"
    cache_path.write_text(json.dumps({"_cache_hash": old_hash, "doc_id": "doc1"}), encoding="utf-8")

    # With context version "v2", cache must be invalid
    assert not ba_mod.is_cache_valid(cache_path, md_path, "fake-model", "v2")
    # With same context version "v1", cache must be valid
    assert ba_mod.is_cache_valid(cache_path, md_path, "fake-model", "v1")


def test_batch_analyze_cache_invalidated_when_content_changes(tmp_path):
    """When md file content changes, cache must be invalid."""
    import batch_analyze as ba_mod

    md_path = tmp_path / "doc.md"
    md_path.write_text("content v1", encoding="utf-8")

    old_hash = ba_mod.compute_content_hash(md_path, "fake-model", "")
    cache_path = tmp_path / "doc1.json"
    cache_path.write_text(json.dumps({"_cache_hash": old_hash}), encoding="utf-8")

    assert ba_mod.is_cache_valid(cache_path, md_path, "fake-model", "")

    # Change file content
    md_path.write_text("content v2 changed", encoding="utf-8")
    assert not ba_mod.is_cache_valid(cache_path, md_path, "fake-model", "")


def test_batch_analyze_cache_invalidated_when_model_changes(tmp_path):
    """When the LLM model changes, cache must be invalid."""
    import batch_analyze as ba_mod

    md_path = tmp_path / "doc.md"
    md_path.write_text("content", encoding="utf-8")

    old_hash = ba_mod.compute_content_hash(md_path, "model-A", "")
    cache_path = tmp_path / "doc1.json"
    cache_path.write_text(json.dumps({"_cache_hash": old_hash}), encoding="utf-8")

    assert ba_mod.is_cache_valid(cache_path, md_path, "model-A", "")
    assert not ba_mod.is_cache_valid(cache_path, md_path, "model-B", "")


def test_build_context_for_doc_includes_structured_analysis_when_available(tmp_path):
    """build_context_for_doc must inject core_problem/boundary_in from
    existing analysis output (not just metadata).
    """
    import batch_analyze as ba_mod

    # Pretend an analysis of doc2 was already produced
    analysis = {
        "doc_id": "doc2",
        "core_problem": "解决了 doc1 的边界外问题",
        "boundary_in": ["新边界"],
        "boundary_out": [],
        "key_points": {"type": "plan"},
    }
    (tmp_path / "doc2.json").write_text(json.dumps(analysis), encoding="utf-8")

    doc1 = {"doc_id": "doc1", "version": "V1", "title": "t1", "md_path": ""}
    doc2 = {"doc_id": "doc2", "version": "V2", "title": "t2", "md_path": ""}
    all_docs = [doc1, doc2]
    version_chains = [{
        "chain_name": "c1",
        "versions": [
            {"doc_id": "doc1", "version": "V1", "title": "t1"},
            {"doc_id": "doc2", "version": "V2", "title": "t2"},
        ],
    }]

    context = ba_mod.build_context_for_doc(doc1, all_docs, version_chains, tmp_path)
    excerpts = context["other_docs_excerpts"]
    assert len(excerpts) == 1
    entry = excerpts[0]
    assert entry["doc_id"] == "doc2"
    assert entry["core_problem"] == "解决了 doc1 的边界外问题"
    assert entry["boundary_in"] == ["新边界"]
    assert entry["key_points"] == {"type": "plan"}


def test_build_context_for_doc_falls_back_to_metadata_when_no_analysis(tmp_path):
    """When no prior analysis exists, the context should still include
    metadata (doc_id, version, title) plus an empty excerpt.
    """
    import batch_analyze as ba_mod

    doc1 = {"doc_id": "doc1", "version": "V1", "title": "t1", "md_path": ""}
    doc2 = {"doc_id": "doc2", "version": "V2", "title": "t2", "md_path": ""}
    version_chains = [{
        "chain_name": "c1",
        "versions": [
            {"doc_id": "doc1", "version": "V1", "title": "t1"},
            {"doc_id": "doc2", "version": "V2", "title": "t2"},
        ],
    }]

    context = ba_mod.build_context_for_doc(doc1, [doc1, doc2], version_chains, tmp_path)
    excerpts = context["other_docs_excerpts"]
    assert len(excerpts) == 1
    assert excerpts[0]["doc_id"] == "doc2"
    # No prior analysis → fields should be absent or empty
    assert excerpts[0].get("core_problem", "") == ""
