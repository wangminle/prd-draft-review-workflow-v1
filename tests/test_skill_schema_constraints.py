"""Tests for SkillSchemaLoader business constraint enforcement (P1-4.2)."""



from app.services.skill_schema import SkillSchemaLoader


def test_enum_violation_is_reported(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"type": "string", "enum": ["resolved", "partial", "unresolved"]},
        },
    }
    errors = loader.validate({"status": "weird"}, schema)
    assert any("not in enum" in e for e in errors)


def test_minimum_maximum_enforced(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    errors = loader.validate(
        {"quality_score": 99, "confidence": -3}, schema
    )
    assert any("quality_score" in e and "< minimum" not in e and "> maximum" in e for e in errors)
    assert any("confidence" in e and "< minimum" in e for e in errors)


def test_min_items_enforced(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "checks": {"type": "array", "minItems": 6, "items": {"type": "object"}},
        },
    }
    errors = loader.validate({"checks": [{"a": 1}, {"b": 2}]}, schema)
    assert any("too few items" in e and "minItems" in e for e in errors)


def test_additional_properties_false_rejects_unknown_fields(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["doc_id"],
        "properties": {"doc_id": {"type": "string"}},
        "additionalProperties": False,
    }
    errors = loader.validate({"doc_id": "1", "rogue": "x"}, schema)
    assert any("rogue" in e and "additionalProperties" in e for e in errors)


def test_local_ref_is_resolved(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["score"],
        "properties": {
            "score": {"$ref": "#/definitions/score"},
        },
        "definitions": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
        },
    }
    errors = loader.validate({"score": 99}, schema)
    assert any("> maximum" in e for e in errors)

    # Valid ref data passes
    assert loader.validate({"score": 3}, schema) == []


def test_unresolvable_ref_is_reported(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {"x": {"$ref": "#/definitions/missing"}},
    }
    errors = loader.validate({"x": 1}, schema)
    assert any("unresolvable $ref" in e for e in errors)


def test_repair_clamps_out_of_range_numeric(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
        },
    }
    repaired = loader.repair({"quality_score": 99}, schema)
    assert repaired["quality_score"] == 5
    assert repaired["_schema_valid"] is False
    # quality_score is a critical field; repair should flag critical
    assert repaired.get("_schema_critical") is True


def test_repair_enum_case_insensitive_correction(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["resolved", "partial", "unresolved"]},
        },
    }
    repaired = loader.repair({"status": "RESOLVED"}, schema)
    assert repaired["status"] == "resolved"
    # status is a critical field — even a successful correction counts as repair
    assert repaired["_schema_valid"] is False


def test_repair_drops_unknown_properties_when_additional_properties_false(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["doc_id"],
        "properties": {"doc_id": {"type": "string"}},
        "additionalProperties": False,
    }
    repaired = loader.repair({"doc_id": "1", "rogue": "x"}, schema)
    assert "rogue" not in repaired
    assert repaired["_schema_valid"] is False


def test_critical_field_missing_marks_schema_critical(tmp_path):
    """A missing doc_id cannot be silently defaulted to success."""
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["doc_id", "quality_score"],
        "properties": {
            "doc_id": {"type": "string"},
            "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
        },
    }
    repaired = loader.repair({"quality_score": 3}, schema)
    assert repaired["_schema_valid"] is False
    assert repaired["_schema_critical"] is True
    # doc_id is filled with default ("") but flagged
    assert repaired["doc_id"] == ""


def test_non_critical_repair_does_not_mark_critical(tmp_path):
    """A missing non-critical optional field should not set _schema_critical."""
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "required": ["doc_id"],
        "properties": {
            "doc_id": {"type": "string"},
            "summary": {"type": "string"},  # non-critical, missing
        },
    }
    repaired = loader.repair({"doc_id": "1"}, schema)
    assert repaired["_schema_valid"] is True  # nothing was actually repaired
    assert repaired.get("_schema_critical") is False


def test_nested_critical_violation_propagates(tmp_path):
    """quality_score inside an array item is still critical when out of range."""
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["quality_score"],
                    "properties": {
                        "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                },
            },
        },
    }
    repaired = loader.repair({"items": [{"quality_score": 999}]}, schema)
    assert repaired["items"][0]["quality_score"] == 5
    assert repaired["_schema_valid"] is False
    assert repaired["_schema_critical"] is True


def test_min_length_max_length_enforced(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "minLength": 2, "maxLength": 4},
        },
    }
    errors = loader.validate({"code": "a"}, schema)
    assert any("minLength" in e for e in errors)
    errors = loader.validate({"code": "abcdef"}, schema)
    assert any("maxLength" in e for e in errors)


def test_pattern_enforced(tmp_path):
    loader = SkillSchemaLoader(tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "pattern": r"^doc_\d+$"},
        },
    }
    errors = loader.validate({"doc_id": "weird"}, schema)
    assert any("does not match pattern" in e for e in errors)
    assert loader.validate({"doc_id": "doc_123"}, schema) == []
