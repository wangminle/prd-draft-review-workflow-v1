"""Thinking adapter — 将抽象思考级别转换为各供应商的请求参数。

核心原则：adapter 只在明确支持时注入字段，否则不传任何思考参数。
内置映射仅供参考，管理员可通过 custom_json 完全覆盖。
"""

from __future__ import annotations

import json
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ThinkingLevel(str, Enum):
    OFF = "off"
    LOW = "low"
    HIGH = "high"


class ThinkingAdapter(str, Enum):
    NONE = "none"
    OPENAI_REASONING = "openai_reasoning"
    DEEPSEEK_REASONER = "deepseek_reasoner"
    QWEN_THINKING = "qwen_thinking"
    CUSTOM_JSON = "custom_json"


# 内置 adapter 模板：每种 adapter 对每个 level 返回的额外请求参数。
# 这些只是参考映射，管理员可通过 custom_json 完全覆盖。
THINKING_ADAPTER_TEMPLATES: dict[str, dict[str, dict]] = {
    ThinkingAdapter.OPENAI_REASONING: {
        ThinkingLevel.LOW: {"reasoning_effort": "low"},
        ThinkingLevel.HIGH: {"reasoning_effort": "high"},
    },
    ThinkingAdapter.DEEPSEEK_REASONER: {
        ThinkingLevel.LOW: {"reasoning_effort": "low"},
        ThinkingLevel.HIGH: {"reasoning_effort": "high"},
    },
    ThinkingAdapter.QWEN_THINKING: {
        ThinkingLevel.LOW: {"enable_thinking": True, "thinking_budget": 4096},
        ThinkingLevel.HIGH: {"enable_thinking": True, "thinking_budget": 32768},
    },
}


def build_thinking_payload(
    thinking_level: str,
    thinking_adapter: str,
    thinking_payload: str | None = None,
    *,
    runtime_level_override: str | None = None,
) -> dict:
    """将抽象思考配置转换为供应商特定的请求参数。

    Args:
        thinking_level: 模型默认思考级别 (off/low/high)
        thinking_adapter: 适配类型 (none/openai_reasoning/...)
        thinking_payload: 自定义 JSON 模板 (仅 custom_json 使用)
        runtime_level_override: 运行时覆盖的思考级别 (来自用户请求)

    Returns:
        dict: 需要注入到 LLM 请求体的额外参数。空 dict 表示不注入任何字段。
    """
    level = runtime_level_override or thinking_level

    if level == ThinkingLevel.OFF:
        return {}

    if thinking_adapter == ThinkingAdapter.NONE or thinking_adapter == ThinkingAdapter.CUSTOM_JSON and not thinking_payload:
        return {}

    if thinking_adapter == ThinkingAdapter.CUSTOM_JSON:
        return _resolve_custom_json(thinking_payload, level)

    template = THINKING_ADAPTER_TEMPLATES.get(thinking_adapter, {})
    return dict(template.get(level, {}))


def _resolve_custom_json(payload_template: str, level: str) -> dict:
    """从自定义 JSON 模板解析并替换级别变量。"""
    if not payload_template:
        return {}

    try:
        raw = json.loads(payload_template)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid thinking_payload JSON, ignoring")
        return {}

    if isinstance(raw, dict):
        return _substitute_level(raw, level)

    return {}


def _substitute_level(obj, level: str):
    """递归替换模板中的 {{level}} 占位符。"""
    if isinstance(obj, str):
        return obj.replace("{{level}}", level)
    if isinstance(obj, dict):
        return {k: _substitute_level(v, level) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_level(item, level) for item in obj]
    return obj
