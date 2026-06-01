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

    def load(self, skill_name: str) -> dict | None:
        """Load output-schema.json from skills/{skill_name}/templates/.

        Returns None if the file doesn't exist.
        """
        if skill_name in self._cache:
            return self._cache[skill_name]

        path = self.skills_dir / skill_name / "templates" / "output-schema.json"
        if not path.exists():
            logger.info("No output schema for skill %s", skill_name)
            return None

        with open(path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        self._cache[skill_name] = schema
        return schema

    def validate(self, data: dict, schema: dict) -> list[str]:
        """Validate data against a JSON Schema, returning a list of error strings.

        Only checks required fields and basic type matching — not a full
        JSON Schema validator, but sufficient for LLM output verification.
        """
        errors: list[str] = []

        # Check required fields
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                errors.append(f"missing required field: {field}")

        # Check property types
        props = schema.get("properties", {})
        for field, field_schema in props.items():
            if field not in data:
                continue
            expected_type = field_schema.get("type")
            if not expected_type:
                continue
            value = data[field]
            type_ok = _check_type(value, expected_type)
            if not type_ok:
                errors.append(f"field {field} has wrong type: expected {expected_type}, got {type(value).__name__}")

        return errors

    def repair(self, data: dict, schema: dict) -> dict:
        """Attempt to repair data that doesn't match the schema.

        Strategy:
        1. Fill missing required fields with type-appropriate defaults
        2. Try type conversion for mismatched fields
        3. Mark _schema_valid=False if any repair was needed
        """
        repaired = False
        result = dict(data)

        # Fill missing required fields
        required = schema.get("required", [])
        props = schema.get("properties", {})
        for field in required:
            if field not in result:
                default = _field_default(props.get(field, {}))
                result[field] = default
                repaired = True
                logger.info("Repaired missing field %s → default: %s", field, default)

        # Try type conversion
        for field, field_schema in props.items():
            if field not in result:
                continue
            expected_type = field_schema.get("type")
            if not expected_type:
                continue
            if not _check_type(result[field], expected_type):
                converted = _try_convert(result[field], expected_type)
                if converted is not None:
                    result[field] = converted
                    repaired = True
                    logger.info("Repaired field %s type → %s", field, expected_type)

        result["_schema_valid"] = not repaired
        return result


def _field_default(field_schema: dict):
    """Get a default value for a field based on its JSON Schema type."""
    type_name = field_schema.get("type", "string")
    return _TYPE_DEFAULTS.get(type_name, "")


def _check_type(value, expected_type: str) -> bool:
    """Check if value matches the expected JSON Schema type."""
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
    return True


def _try_convert(value, target_type: str):
    """Try to convert a value to the target JSON Schema type."""
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