"""Skill JSON Schema loader, validator, and repair utility."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default values for missing fields by JSON type
_TYPE_DEFAULTS = {
    "string": "",
    "integer": 0,
    "number": 0.0,
    "boolean": False,
    "array": [],
    "object": {},
}


class SkillSchemaLoader:
    """Load, validate, and repair JSON outputs against skill schemas."""

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self._cache: dict[str, dict] = {}

    def load(self, skill_name: str, prompt_name: str | None = None) -> dict | None:
        """Load output schema from skills/{skill_name}/templates/.

        Prompt-specific schemas named output-schema.{prompt_name}.json take
        precedence over the skill-level output-schema.json.

        Returns None if the file doesn't exist.
        """
        cache_key = f"{skill_name}:{prompt_name or '*'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        templates_dir = self.skills_dir / skill_name / "templates"
        paths = []
        if prompt_name:
            paths.append(templates_dir / f"output-schema.{prompt_name}.json")
        paths.append(templates_dir / "output-schema.json")

        path = next((candidate for candidate in paths if candidate.exists()), None)
        if path is None:
            logger.info("No output schema for skill %s prompt %s", skill_name, prompt_name or "*")
            return None

        with open(path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        self._cache[cache_key] = schema
        return schema

    def load_prompt_schema(self, skill_name: str, prompt_name: str) -> dict | None:
        """Backward-compatible explicit API for prompt-specific schema loading."""
        return self.load(skill_name, prompt_name)

    def validate(self, data: dict, schema: dict) -> list[str]:
        """Validate data against a JSON Schema, returning a list of error strings.

        Only checks required fields and basic type matching — not a full
        JSON Schema validator, but sufficient for LLM output verification.
        """
        return _validate_node(data, schema)

    def repair(self, data: dict, schema: dict) -> dict:
        """Attempt to repair data that doesn't match the schema.

        Strategy:
        1. Fill missing required fields with type-appropriate defaults
        2. Try type conversion for mismatched fields
        3. Mark _schema_valid=False if any repair was needed
        """
        result, repaired = _repair_node(data, schema)
        if not isinstance(result, dict):
            result = _field_default(schema)
            repaired = True
        result["_schema_valid"] = not repaired
        return result


def _field_default(field_schema: dict):
    """Get a default value for a field based on its JSON Schema type."""
    type_name = field_schema.get("type", "string")
    if isinstance(type_name, list):
        type_name = next((item for item in type_name if item != "null"), "string")
    return _TYPE_DEFAULTS.get(type_name, "")


def _format_path(path: str) -> str:
    return path or "root"


def _expected_type_label(expected_type) -> str:
    if isinstance(expected_type, list):
        return "|".join(expected_type)
    return str(expected_type)


def _validate_node(value, schema: dict, path: str = "") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and not _check_type(value, expected_type):
        errors.append(f"{_format_path(path)} has wrong type: expected {_expected_type_label(expected_type)}, got {type(value).__name__}")
        return errors

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in value:
                field_path = f"{path}.{field}" if path else field
                errors.append(f"{field_path} missing required field")
        for field, field_schema in props.items():
            if field not in value:
                continue
            field_path = f"{path}.{field}" if path else field
            errors.extend(_validate_node(value[field], field_schema, field_path))
    elif isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(value):
                errors.extend(_validate_node(item, item_schema, f"{path}[{idx}]"))

    return errors


def _repair_node(value, schema: dict):
    repaired = False
    expected_type = schema.get("type")
    if expected_type and not _check_type(value, expected_type):
        converted = _try_convert(value, expected_type)
        if converted is not None:
            value = converted
            repaired = True
        else:
            return _field_default(schema), True

    if isinstance(value, dict):
        result = dict(value)
        props = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in result:
                result[field] = _field_default(props.get(field, {}))
                repaired = True
                logger.info("Repaired missing field %s → default: %s", field, result[field])
        for field, field_schema in props.items():
            if field not in result:
                continue
            repaired_value, child_repaired = _repair_node(result[field], field_schema)
            if child_repaired:
                result[field] = repaired_value
                repaired = True
        return result, repaired

    if isinstance(value, list) and schema.get("items"):
        items = []
        for item in value:
            repaired_item, child_repaired = _repair_node(item, schema["items"])
            items.append(repaired_item)
            repaired = repaired or child_repaired
        return items, repaired

    return value, repaired


def _check_type(value, expected_type) -> bool:
    """Check if value matches the expected JSON Schema type."""
    if isinstance(expected_type, list):
        return any(_check_type(value, item) for item in expected_type)
    if expected_type == "string":
        return isinstance(value, str)
    elif expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    elif expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected_type == "boolean":
        return isinstance(value, bool)
    elif expected_type == "array":
        return isinstance(value, list)
    elif expected_type == "object":
        return isinstance(value, dict)
    elif expected_type == "null":
        return value is None
    return True


def _try_convert(value, target_type):
    """Try to convert a value to the target JSON Schema type."""
    if isinstance(target_type, list):
        for candidate in target_type:
            if candidate == "null":
                continue
            converted = _try_convert(value, candidate)
            if converted is not None:
                return converted
        return None
    try:
        if target_type == "string":
            return str(value)
        elif target_type == "integer":
            return int(float(value))
        elif target_type == "number":
            return float(value)
        elif target_type == "boolean":
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        elif target_type == "array":
            if isinstance(value, str):
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            return list(value) if isinstance(value, (tuple, set)) else None
        elif target_type == "object":
            if isinstance(value, str):
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return None
