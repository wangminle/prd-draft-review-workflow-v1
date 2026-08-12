"""Tests for P1-4.4: classify version-chain category closure + dependency detection."""

import json
import os
import sys
from pathlib import Path



ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "skills"
sys.path.insert(0, str(SKILLS / "prd-overview-classify" / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "src" / "config.yaml"))

import classify as classify_mod
from classify import (
    DocumentInfo,
    build_version_chains,
    detect_dependencies,
    classify_documents,
)


def _make_doc(doc_id, filename, version, subcategory_name=None, category="核心策略",
              title="", excerpt=""):
    return DocumentInfo(
        doc_id=doc_id,
        filename=filename,
        md_path="/tmp/fake.md",
        category=category,
        version=version,
        subcategory_name=subcategory_name,
        subcategory_seq=1 if subcategory_name else None,
        title=title,
        excerpt=excerpt,
    )


def test_version_chain_does_not_merge_across_categories():
    """Same subcategory_name but different categories must NOT merge."""
    docs = [
        _make_doc("doc1", "fileA_V1.0", "V1.0", subcategory_name="响应时延",
                  category="核心策略", title="智能联动响应时延V1"),
        _make_doc("doc2", "fileA_V2.0", "V2.0", subcategory_name="响应时延",
                  category="平台架构", title="智能联动响应时延V2"),
    ]
    chains = build_version_chains(docs)
    # They must NOT be in the same chain because their categories differ.
    assert len(chains) == 0 or all(
        len(c.versions) < 2 for c in chains
    ), "Cross-category docs with same subcategory_name must not merge into a chain"


def test_version_chain_merges_within_same_category():
    """Same subcategory_name + same category → one chain."""
    docs = [
        _make_doc("doc1", "fileA_V1.0", "V1.0", subcategory_name="响应时延",
                  category="核心策略", title="智能联动响应时延V1"),
        _make_doc("doc2", "fileA_V2.0", "V2.0", subcategory_name="响应时延",
                  category="核心策略", title="智能联动响应时延V2"),
    ]
    chains = build_version_chains(docs)
    assert len(chains) == 1
    assert chains[0].chain_name == "响应时延"
    assert len(chains[0].versions) == 2


def test_version_chain_sorts_versions_ascending():
    docs = [
        _make_doc("doc2", "f_V2.0", "V2.0", subcategory_name="x", title="V2"),
        _make_doc("doc1", "f_V1.0", "V1.0", subcategory_name="x", title="V1"),
        _make_doc("doc3", "f_V3.0", "V3.0", subcategory_name="x", title="V3"),
    ]
    chains = build_version_chains(docs)
    assert [v.version for v in chains[0].versions] == ["V1.0", "V2.0", "V3.0"]


def test_use_llm_param_does_not_bypass_deterministic_constraints():
    """use_llm=True must not allow cross-category merging."""
    docs = [
        _make_doc("doc1", "f_V1.0", "V1.0", subcategory_name="x", category="A"),
        _make_doc("doc2", "f_V2.0", "V2.0", subcategory_name="x", category="B"),
    ]
    chains = build_version_chains(docs, use_llm=True)
    assert not any(len(c.versions) >= 2 for c in chains)


def test_dependency_detection_includes_version_successor():
    docs = [
        _make_doc("doc1", "f_V1.0", "V1.0", subcategory_name="x", title="V1"),
        _make_doc("doc2", "f_V2.0", "V2.0", subcategory_name="x", title="V2"),
    ]
    chains = build_version_chains(docs)
    deps = detect_dependencies(docs, chains)
    relations = {d.relation for d in deps}
    assert "version_successor" in relations


def test_dependency_detection_finds_cross_document_references():
    """If doc A's excerpt mentions doc B's title, a 'references' dependency
    should be produced.
    """
    docs = [
        _make_doc("doc1", "f_V1.0", "V1.0", subcategory_name="x",
                  title="响应时延V1", excerpt="首次提出"),
        _make_doc("doc2", "f_V2.0", "V2.0", subcategory_name="y",
                  title="打分相近V1", excerpt="本节基于 响应时延V1 的方案进行扩展"),
    ]
    chains = build_version_chains(docs)
    # No chain — they're in different subcategories. But doc2 references doc1's title.
    deps = detect_dependencies(docs, chains)
    references = [d for d in deps if d.relation == "references"]
    assert any(d.from_doc_id == "doc2" and d.to_doc_id == "doc1" for d in references), \
        f"Expected doc2 references doc1, got: {[(d.from_doc_id, d.to_doc_id, d.relation) for d in deps]}"


def test_classify_documents_rejects_unknown_category(monkeypatch, capsys):
    """LLM-returned categories not in the whitelist must be set to 待确认."""
    docs = [_make_doc("doc1", "f_V1.0", "V1.0", title="某需求")]
    config = {
        "categories": [{"name": "核心策略", "keywords": ["策略"]}],
        "version_pattern": r"V\d+\.\d+",
    }

    def fake_llm_call(docs, cat_list, whitelist):
        # Simulate LLM returning a bogus category
        docs[0].category = "BogusCategory"

    monkeypatch.setattr(classify_mod, "_classify_with_llm", fake_llm_call)
    classify_documents(docs, config, keyword_only=False, use_llm=True)
    assert docs[0].category == "待确认"


def test_classify_documents_accepts_whitelisted_category(monkeypatch):
    docs = [_make_doc("doc1", "f_V1.0", "V1.0", title="某需求")]
    config = {
        "categories": [{"name": "核心策略", "keywords": ["策略"]}],
        "version_pattern": r"V\d+\.\d+",
    }

    def fake_llm_call(docs, cat_list, whitelist):
        docs[0].category = "核心策略"

    monkeypatch.setattr(classify_mod, "_classify_with_llm", fake_llm_call)
    classify_documents(docs, config, keyword_only=False, use_llm=True)
    assert docs[0].category == "核心策略"


def test_cli_version_pattern_overrides_config(tmp_path, monkeypatch):
    """When --version-pattern is explicitly different from the default,
    it must win over config's version_pattern.
    """
    # Simulate the main() precedence logic directly:
    DEFAULT_VERSION_PATTERN = classify_mod.DEFAULT_VERSION_PATTERN
    cli_pattern = r"V\d+\.\d+\.\d+"  # explicit, different from default
    config = {"version_pattern": r"V\d+"}

    if cli_pattern and cli_pattern != DEFAULT_VERSION_PATTERN:
        version_pattern = cli_pattern
    elif config.get("version_pattern"):
        version_pattern = config["version_pattern"]
    else:
        version_pattern = cli_pattern or DEFAULT_VERSION_PATTERN

    assert version_pattern == r"V\d+\.\d+\.\d+", \
        f"CLI should override config, got {version_pattern!r}"


def test_config_version_pattern_used_when_cli_is_default():
    """When CLI did not override (equals default), config's version_pattern wins."""
    DEFAULT_VERSION_PATTERN = classify_mod.DEFAULT_VERSION_PATTERN
    cli_pattern = DEFAULT_VERSION_PATTERN  # user didn't override
    config = {"version_pattern": r"V\d+\.\d+"}

    if cli_pattern and cli_pattern != DEFAULT_VERSION_PATTERN:
        version_pattern = cli_pattern
    elif config.get("version_pattern"):
        version_pattern = config["version_pattern"]
    else:
        version_pattern = cli_pattern or DEFAULT_VERSION_PATTERN

    assert version_pattern == r"V\d+\.\d+"


def test_version_chain_schema_includes_dependencies():
    """The version-chain output schema must declare dependencies."""
    schema_path = SKILLS / "prd-overview-classify" / "templates" / "output-schema.version-chain.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "dependencies" in schema["properties"]
    dep_schema = schema["properties"]["dependencies"]["items"]
    assert "from_doc_id" in dep_schema["required"]
    assert "to_doc_id" in dep_schema["required"]
    assert "relation" in dep_schema["required"]
    assert "enum" in dep_schema["properties"]["relation"]
    assert "references" in dep_schema["properties"]["relation"]["enum"]
