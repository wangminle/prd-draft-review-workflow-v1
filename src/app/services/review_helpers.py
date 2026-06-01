"""Shared utility functions used by review router and skill runner.

Eliminates code duplication between routers/review.py and services/skill_runner.py.
"""

import ast
import json


DEFAULT_TEAM_REVIEW_GUIDANCE = [
    "需求范围要写实：明确写清当前需求到底解决什么，不只写背景价值。",
    "能力边界要写全：写清做什么、不做什么、依赖什么前置条件。",
    "权益和分类要结构化：把用户权益、对象分类、场景分类讲清楚。",
    "用户侧命名要可理解：使用用户能理解的名称，避免内部黑话。",
    "多入口文案要统一：不同页面、入口、账号体系下文案要保持一致。",
    "技术方案要分期但不能糊涂：分阶段推进时写清阶段边界、适用范围和当前落点。",
]


def default_review_context() -> dict:
    return {"professional_guidance": list(DEFAULT_TEAM_REVIEW_GUIDANCE)}


def merge_review_context_defaults(context: dict | None) -> dict:
    data = dict(context) if isinstance(context, dict) else {}
    if not data.get("professional_guidance"):
        data["professional_guidance"] = list(DEFAULT_TEAM_REVIEW_GUIDANCE)
    return data


def json_from_raw_text(raw_text: str) -> dict | None:
    """Extract JSON dict from Markdown-wrapped or raw text.

    Handles three patterns:
    - Pure JSON text
    - Markdown ```json code blocks
    - JSON embedded inside prose (bracket matching)
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, SyntaxError):
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        body = text[start:end + 1]
        try:
            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(body)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, SyntaxError):
            return None
    return None


def extract_pm_assessment_payload(data: dict | None) -> dict | None:
    """Unwrap nested PM assessment payloads from various LLM output formats.

    Handles:
    - Direct writing_scores/thinking_scores
    - Nested under pm_scores/pm_assessment keys
    - Nested under dimensions.pm_assessment
    - Raw_text containing Markdown-wrapped JSON
    - Fallback: data with pm_type/highlights/blindspots/growth_path keys
    """
    if not isinstance(data, dict):
        return None

    if data.get("writing_scores") or data.get("thinking_scores"):
        return data

    for key in ("pm_scores", "pm_assessment"):
        nested_payload = data.get(key)
        if isinstance(nested_payload, dict):
            extracted = extract_pm_assessment_payload(nested_payload)
            if extracted:
                return extracted

    dimensions = data.get("dimensions")
    nested = dimensions.get("pm_assessment") if isinstance(dimensions, dict) else None
    if isinstance(nested, dict):
        extracted = extract_pm_assessment_payload(nested)
        if extracted:
            return extracted

    raw_text = data.get("raw_text")
    if isinstance(raw_text, str):
        return extract_pm_assessment_payload(json_from_raw_text(raw_text))

    pm_content_keys = ("pm_type", "highlights", "blindspots", "growth_path")
    if any(data.get(key) for key in pm_content_keys):
        return data

    return None


def build_context_injection(context: dict | None) -> str:
    """Build a prompt injection block from ReviewContext data."""
    context = merge_review_context_defaults(context)
    parts = []
    if context.get("category_overrides"):
        parts.append(f"分类覆盖规则: {json.dumps(context['category_overrides'], ensure_ascii=False)}")
    if context.get("required_sections"):
        parts.append(f"必需章节检查: {json.dumps(context['required_sections'], ensure_ascii=False)}")
    if context.get("scoring_overrides"):
        parts.append(f"评分量规覆盖: {json.dumps(context['scoring_overrides'], ensure_ascii=False)}")
    if context.get("specifications"):
        parts.append(f"业务规范约束: {json.dumps(context['specifications'], ensure_ascii=False)}")
    if context.get("professional_guidance"):
        parts.append(f"团队评审意见: {json.dumps(context['professional_guidance'], ensure_ascii=False)}")
    if not parts:
        return ""
    return "\n\n[评审上下文注入]\n" + "\n".join(parts) + "\n[/评审上下文注入]"
