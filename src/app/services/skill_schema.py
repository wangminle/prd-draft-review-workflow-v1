"""Skill JSON Schema loader, validator, and repair utility."""

from __future__ import annotations

import json
import logging
import re
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

# Fields whose missing/invalid values cannot be safely defaulted to a "success"
# state. Repair will still fill them, but the result stays schema_valid=False
# and a critical error is recorded in diagnostics.
_CRITICAL_FIELD_HINTS = {
    "doc_id",
    "category",
    "quality_score",
    "score",
    "confidence",
    "severity",
    "status",
    "feature_id",
    "issue_id",
    "version",
    "chain_name",
    "classifications",
    "chains",
    "feature_dimensions",
    "action_plan",
    "action_items",
    "recommendations",
}


class SkillSchemaLoader:
    """Load, validate, and repair JSON outputs against skill schemas.

    Supports a meaningful subset of JSON Schema draft-07:
      - type (incl. type arrays with null)
      - required
      - properties / nested objects
      - items (array element schema)
      - enum
      - minimum / maximum / exclusiveMinimum / exclusiveMaximum
      - minItems / maxItems
      - minLength / maxLength
      - additionalProperties: false
      - $ref to local definitions (#/definitions/...)

    This is NOT a full jsonschema implementation, but it enforces the business
    constraints declared in skill output schemas (score ranges, status enums,
    minimum check counts, etc.) so that LLM format errors cannot silently pass
    through as "success" with bogus values.
    """

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

        Enforces type, required, enum, minimum/maximum, minItems/maxItems,
        minLength/maxLength, additionalProperties: false, and local $ref.
        """
        resolver = _RefResolver(schema)
        return _validate_node(data, schema, "", resolver)

    def repair(self, data: dict, schema: dict) -> dict:
        """Attempt to repair data that doesn't match the schema.

        Strategy:
        1. Fill missing required fields with type-appropriate defaults
        2. Try type conversion for mismatched fields
        3. Try enum correction (case-insensitive match to nearest enum value)
        4. Clamp numeric values to [minimum, maximum] when feasible
        5. Drop properties when additionalProperties: false
        6. Mark _schema_valid=False if any repair was needed
        7. Mark _schema_critical=True when a repair substantively rewrote a
           value (uncorrectable enum fallback, unconvertible type, numeric
           clamping, minItems shortfall) or when a critical business field
           was missing/invalid (callers MUST NOT treat critical repairs as
           success)
        8. Collect _schema_repair_notes listing every repair action so
           callers can surface non-critical repairs in diagnostics (4.2 fix)
        """
        resolver = _RefResolver(schema)
        repair_notes: list[str] = []
        result, repaired, critical = _repair_node(data, schema, "", resolver, repair_notes)
        if not isinstance(result, dict):
            result = _field_default(schema)
            repaired = True
            critical = True
        result["_schema_valid"] = not repaired
        result["_schema_critical"] = critical or _has_critical_invalid_field(result, schema, resolver)
        result["_schema_repair_notes"] = repair_notes
        return result


def _has_critical_invalid_field(data: dict, schema: dict, resolver: "_RefResolver") -> bool:
    """Re-check whether any critical business field is missing/invalid after repair."""
    if not isinstance(data, dict):
        return True
    errors = _validate_node(data, schema, "", resolver)
    if not errors:
        return False
    # Treat any error touching a critical field path as critical.
    for err in errors:
        for hint in _CRITICAL_FIELD_HINTS:
            if hint in err:
                return True
    return False


class _RefResolver:
    """Minimal $ref resolver for local #/definitions/... references."""

    def __init__(self, root_schema: dict):
        self.root = root_schema or {}

    def resolve(self, ref: str) -> dict | None:
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return None
        node: object = self.root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return None
        return node if isinstance(node, dict) else None


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


def _validate_node(value, schema: dict, path: str, resolver: _RefResolver) -> list[str]:
    errors: list[str] = []

    # Resolve $ref
    ref = schema.get("$ref")
    if ref:
        resolved = resolver.resolve(ref)
        if resolved is None:
            errors.append(f"{_format_path(path)} has unresolvable $ref: {ref}")
            return errors
        return _validate_node(value, resolved, path, resolver)

    expected_type = schema.get("type")
    if expected_type and not _check_type(value, expected_type):
        errors.append(f"{_format_path(path)} has wrong type: expected {_expected_type_label(expected_type)}, got {type(value).__name__}")
        return errors

    # enum constraint
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{_format_path(path)} value {value!r} not in enum {schema['enum']}")
        # Don't return early — still validate nested structure if applicable

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
            errors.extend(_validate_node(value[field], field_schema, field_path, resolver))

        # additionalProperties: false — reject unknown fields
        additional = schema.get("additionalProperties")
        if additional is False:
            known = set(props.keys()) | set(schema.get("required", []))
            unknown = [k for k in value.keys() if k not in known and not k.startswith("_")]
            for k in unknown:
                field_path = f"{path}.{k}" if path else k
                errors.append(f"{field_path} is not allowed (additionalProperties: false)")
    elif isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(value):
                errors.extend(_validate_node(item, item_schema, f"{path}[{idx}]", resolver))

        # Array cardinality constraints
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{_format_path(path)} has too few items: {len(value)} < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{_format_path(path)} has too many items: {len(value)} > maxItems {schema['maxItems']}")

    # Numeric range constraints
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{_format_path(path)} value {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{_format_path(path)} value {value} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{_format_path(path)} value {value} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{_format_path(path)} value {value} >= exclusiveMaximum {schema['exclusiveMaximum']}")

    # String length constraints
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{_format_path(path)} string length {len(value)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{_format_path(path)} string length {len(value)} > maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{_format_path(path)} string {value!r} does not match pattern {schema['pattern']}")

    return errors


def _repair_node(value, schema: dict, path: str, resolver: _RefResolver, notes: list[str] | None = None):
    """Returns (repaired_value, repaired_flag, critical_flag).

    If *notes* is provided, each repair action appends a human-readable
    description so callers can surface non-critical repairs in diagnostics.
    """
    def _note(msg: str):
        if notes is not None:
            notes.append(msg)

    # Resolve $ref
    ref = schema.get("$ref")
    if ref:
        resolved = resolver.resolve(ref)
        if resolved is None:
            _note(f"unresolvable $ref at {path or 'root'}: {ref}")
            return _field_default(schema), True, True
        return _repair_node(value, resolved, path, resolver, notes)

    critical = False
    repaired = False
    expected_type = schema.get("type")
    if expected_type and not _check_type(value, expected_type):
        converted = _try_convert(value, expected_type)
        if converted is not None:
            value = converted
            repaired = True
            _note(f"type converted at {path or 'root'} -> {expected_type}")
        else:
            # Cannot convert: the value is replaced by a fabricated type
            # default, which is a substantive rewrite - always critical.
            critical = True
            _note(f"type mismatch at {path or 'root'}: cannot convert to {expected_type}")
            return _field_default(schema), True, critical

    # enum correction: case-insensitive nearest match
    if "enum" in schema and value not in schema["enum"]:
        corrected = _try_enum_correction(value, schema["enum"])
        if corrected is not None:
            value = corrected
            repaired = True
            _note(f"enum corrected at {path or 'root'} -> {value}")
            logger.info("Repaired enum at %s -> %s", path or "root", value)
        else:
            # No deterministic correction possible - falling back to enum[0]
            # rewrites the LLM's semantics, so this is ALWAYS critical
            # (BUG-159), regardless of whether the path is in
            # _CRITICAL_FIELD_HINTS.
            value = schema["enum"][0]
            repaired = True
            critical = True
            _note(f"enum fallback at {path or 'root'}: defaulted to {value}")
            logger.warning("Could not correct enum at %s; defaulting to %s", path or "root", value)

    if isinstance(value, dict):
        result = dict(value)
        props = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in result:
                result[field] = _field_default(props.get(field, {}))
                repaired = True
                critical = critical or _field_is_critical(field)
                _note(f"missing required field filled at {path or 'root'}.{field}")
                logger.info("Repaired missing field %s -> default: %s", field, result[field])
        for field, field_schema in props.items():
            if field not in result:
                continue
            repaired_value, child_repaired, child_critical = _repair_node(
                result[field], field_schema, f"{path}.{field}" if path else field, resolver, notes
            )
            if child_repaired:
                result[field] = repaired_value
                repaired = True
            # Critical flags (e.g. minItems shortfall) must propagate even
            # when the child value itself was not rewritten.
            critical = critical or child_critical

        # Drop unknown properties when additionalProperties: false
        if schema.get("additionalProperties") is False:
            known = set(props.keys()) | set(schema.get("required", []))
            unknown = [k for k in list(result.keys()) if k not in known and not k.startswith("_")]
            for k in unknown:
                result.pop(k, None)
                repaired = True
                _note(f"dropped unknown property at {path or 'root'}.{k}")

        return result, repaired, critical

    if isinstance(value, list) and schema.get("items"):
        items = []
        item_schema = schema["items"]
        for item in value:
            repaired_item, child_repaired, child_critical = _repair_node(
                item, item_schema, path, resolver, notes
            )
            items.append(repaired_item)
            repaired = repaired or child_repaired
            critical = critical or child_critical
        # If below minItems, we cannot synthesize valid items - flag critical.
        if "minItems" in schema and len(items) < schema["minItems"]:
            critical = True
            _note(f"array below minItems at {path or 'root'}: {len(items)} < {schema['minItems']}")
        return items, repaired, critical

    # Numeric range clamping: the value is substantively rewritten (not a
    # format conversion), so clamping is always critical.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            value = schema["minimum"]
            repaired = True
            critical = True
            _note(f"numeric clamped to minimum at {path or 'root'} -> {value}")
        if "maximum" in schema and value > schema["maximum"]:
            value = schema["maximum"]
            repaired = True
            critical = True
            _note(f"numeric clamped to maximum at {path or 'root'} -> {value}")

    # String length truncation (only when maxLength violated)
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        value = value[: schema["maxLength"]]
        repaired = True
        _note(f"string truncated to maxLength at {path or 'root'}")

    return value, repaired, critical

def _try_enum_correction(value, allowed: list):
    """Try to map a malformed enum value to a valid one (case-insensitive,
    whitespace-stripped). Returns None if no match.
    """
    if isinstance(value, str):
        normalized = value.strip().lower()
        for candidate in allowed:
            if isinstance(candidate, str) and candidate.strip().lower() == normalized:
                return candidate
    return None


def _field_is_critical(field_name: str) -> bool:
    return field_name in _CRITICAL_FIELD_HINTS


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
