import json
from pathlib import Path

import pytest

from app.services.skill_runner import SkillRunner
from app.services.skill_schema import SkillSchemaLoader


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_prompt_level_schema_takes_precedence_over_skill_schema(tmp_path):
    templates = tmp_path / "prd-overview-classify" / "templates"
    _write_json(templates / "output-schema.json", {"title": "generic", "type": "object"})
    _write_json(templates / "output-schema.classify.json", {"title": "classify", "type": "object"})

    loader = SkillSchemaLoader(tmp_path)

    assert loader.load("prd-overview-classify", "classify")["title"] == "classify"
    assert loader.load("prd-overview-classify", "version-chain")["title"] == "generic"


def test_schema_validation_recurses_into_object_and_array_items(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["classifications"],
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["doc_id", "category", "confidence"],
                    "properties": {
                        "doc_id": {"type": "string"},
                        "category": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
            }
        },
    }

    errors = loader.validate({"classifications": [{"doc_id": 1, "confidence": "0.8"}]}, schema)

    assert "classifications[0].category missing required field" in errors
    assert "classifications[0].doc_id has wrong type: expected string, got int" in errors
    assert "classifications[0].confidence has wrong type: expected number, got str" in errors


def test_schema_repair_recurses_into_object_and_array_items(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["chains"],
        "properties": {
            "chains": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["chain_name", "versions"],
                    "properties": {
                        "chain_name": {"type": "string"},
                        "versions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["version", "doc_id", "title"],
                                "properties": {
                                    "version": {"type": "string"},
                                    "doc_id": {"type": "string"},
                                    "title": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            }
        },
    }

    repaired = loader.repair({"chains": [{"versions": [{"version": 1, "doc_id": 2}]}]}, schema)

    assert repaired["chains"][0]["chain_name"] == ""
    assert repaired["chains"][0]["versions"][0]["version"] == "1"
    assert repaired["chains"][0]["versions"][0]["doc_id"] == "2"
    assert repaired["chains"][0]["versions"][0]["title"] == ""
    assert repaired["_schema_valid"] is False


def test_prd_overview_classify_prompt_schemas_exist():
    root = Path(__file__).resolve().parents[1]
    classify_schema = json.loads((root / "skills/prd-overview-classify/templates/output-schema.classify.json").read_text(encoding="utf-8"))
    version_schema = json.loads((root / "skills/prd-overview-classify/templates/output-schema.version-chain.json").read_text(encoding="utf-8"))

    assert "classifications" in classify_schema["required"]
    assert "chains" in version_schema["required"]


@pytest.mark.asyncio
async def test_skill_runner_routes_to_prompt_level_schema(tmp_path, monkeypatch):
    skill_dir = tmp_path / "prd-overview-classify"
    (skill_dir / "prompts").mkdir(parents=True)
    (skill_dir / "prompts" / "classify.md").write_text("classify {{doc_titles_and_excerpts}}", encoding="utf-8")
    _write_json(skill_dir / "templates" / "output-schema.classify.json", {
        "type": "object",
        "required": ["classifications"],
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["doc_id", "category", "confidence"],
                    "properties": {
                        "doc_id": {"type": "string"},
                        "category": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
            }
        },
    })

    async def fake_structured_chat(*args, **kwargs):
        return {"classifications": [{"doc_id": 1, "confidence": "0.8"}]}

    monkeypatch.setattr("app.services.skill_runner.structured_chat", fake_structured_chat)
    runner = SkillRunner(
        model_cfg={"api_base": "http://example.test", "api_key": "fake", "llm_model": "fake", "max_tokens": 4096},
        skills_dir=tmp_path,
    )

    result = await runner.run_skill("classify", {"doc_titles_and_excerpts": "需求A"})

    assert result.schema_valid is False
    assert result.data["classifications"][0] == {"doc_id": "1", "confidence": 0.8, "category": ""}
    assert any("classifications[0].category missing required field" in item for item in result.diagnostics)
