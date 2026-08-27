"""BUG-170 / GitHub Issue #4：report 步骤被文件元信息 schema 校验必告警 + 纯文本调用链。

根因（与 #3 同源）：report skill 的 prompt 是 report-polish（润色报告
Markdown 文本），但 run_skill 通用路径存在双重错位——

  1. schema 错位：回退加载 skill 级 output-schema.json（scripts/generate.py
     CLI 的文件清单结构，required=project_name/files/summary），对润色产出
     校验必然缺 3 个 required → 每次评审告警 + 无效 repair 注入假字段；
  2. 调用链错位：structured_chat 的 _parse_json_response 会把 Markdown
     正文中的 JSON 对象（如示例代码块 {"timeout": 30}）误提取为结果并
     丢弃整篇正文 → 路由取不到 markdown/report_content/raw_text → 报告
     不落库。

修复：
  - report 步骤改走纯文本调用链 plain_chat，始终包装 {"raw_text": text}；
  - output-schema.report-polish.json 要求 raw_text 必填且含非空白字符
    （minLength=1 + pattern=\\S，critical hint），空响应 / 纯空白 /
    JSON 误解析产物一律判失败；
  - CLI 文件清单 schema 保留不动（仍是 generate.py 产物的正当约束）。
"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SKILLS = ROOT / "skills"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.services.skill_runner import SkillRunner  # noqa: E402
from app.services.skill_schema import SkillSchemaLoader  # noqa: E402


def _make_runner() -> SkillRunner:
    return SkillRunner(
        model_cfg={
            "api_base": "http://example.test",
            "api_key": "fake-key",
            "llm_model": "fake-model",
            "max_tokens": 4096,
        },
        skills_dir=SKILLS,
    )


REPORT_MARKDOWN = (
    "# 需求评审报告\n\n"
    "## 文档分类\n\n- 功能需求：doc1\n\n"
    "## 逐篇分析\n\n### doc1\n\n核心问题：统一预约入口\n\n"
    "## 配置示例\n\n```json\n{\"timeout\": 30, \"retries\": 3}\n```\n\n"
    "```mermaid\ngraph LR\nA-->B\n```\n\n"
    "## 优先级矩阵\n\n| 需求 | 价值 | 可行性 | 优先级 |\n|---|---|---|---|\n"
)


# ── schema 本身 ──


def test_report_polish_loads_prompt_schema_over_skill_schema():
    loader = SkillSchemaLoader(SKILLS)

    schema = loader.load("report-generator", "report-polish")
    assert schema is not None, "缺少 output-schema.report-polish.json"
    assert schema.get("title") == "Report Polish Output"
    assert schema.get("required") == ["raw_text"]
    assert schema["properties"]["raw_text"]["type"] == "string"
    assert schema["properties"]["raw_text"]["minLength"] == 1
    assert schema["properties"]["raw_text"]["pattern"] == r"\S"


def test_skill_level_schema_still_validates_cli_manifest():
    """CLI 文件清单 schema 保留：generate.py 产物结构仍受约束。"""
    loader = SkillSchemaLoader(SKILLS)

    schema = loader.load("report-generator")
    assert schema.get("required") == ["project_name", "files", "summary"]

    errors = loader.validate({"project_name": "p"}, schema)
    assert "files missing required field" in errors
    assert "summary missing required field" in errors


def test_polish_schema_rejects_empty_and_missing_raw_text():
    loader = SkillSchemaLoader(SKILLS)
    schema = loader.load("report-generator", "report-polish")

    for broken in (
        {},
        {"raw_text": ""},
        {"raw_text": "   "},
        {"raw_text": "\n\t"},
        {"timeout": 30},
        {"markdown": "# 报告"},
    ):
        errors = loader.validate(broken, schema)
        assert errors, f"{broken} 不应通过校验"
        repaired = loader.repair(broken, schema)
        assert repaired["_schema_critical"] is True, f"{broken} 必须判 critical"


# ── 调用链：report 必须走 plain_chat，正文逐字保留 ──


@pytest.mark.asyncio
async def test_report_step_uses_plain_chat_and_preserves_markdown_verbatim(monkeypatch):
    """Markdown 内含 JSON/Mermaid 代码块时，正文必须逐字保留、不被 JSON 提取吞掉。"""
    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()

    plain_calls = []

    async def fake_plain_chat(messages, **kwargs):
        plain_calls.append(1)
        return {"raw_text": REPORT_MARKDOWN}

    async def fail_structured_chat(messages, **kwargs):
        raise AssertionError("report 步骤不得走 structured_chat（会吞掉正文中的 JSON）")

    monkeypatch.setattr(skill_runner_module, "plain_chat", fake_plain_chat)
    monkeypatch.setattr(skill_runner_module, "structured_chat", fail_structured_chat)

    result = await runner.run_skill("report", {
        "report_content": "原始报告",
        "output_type": "report",
    })

    assert len(plain_calls) == 1
    assert result.status == "success"
    assert result.schema_valid is True
    assert result.diagnostics == [], f"不应再有 schema 告警: {result.diagnostics}"
    assert result.data["raw_text"] == REPORT_MARKDOWN, "正文必须逐字保留"
    for injected in ("project_name", "files", "summary", "total_reports"):
        assert injected not in result.data, f"repair 假字段 {injected} 不应出现在产出中"
    # 落库链路（review.py: markdown|report_content|raw_text）取到完整正文
    md = result.data.get("markdown") or result.data.get("report_content") or result.data.get("raw_text")
    assert md == REPORT_MARKDOWN


@pytest.mark.asyncio
async def test_report_step_prd_draft_output_same_plain_path(monkeypatch):
    """PRD 草稿生成复用 report skill（output_type=prd_draft），同样走纯文本链。"""
    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()

    async def fake_plain_chat(messages, **kwargs):
        return {"raw_text": "# PRD 草稿\n\n## 项目背景\n\n含 JSON 示例 {\"ver\": 1} 的正文"}

    monkeypatch.setattr(skill_runner_module, "plain_chat", fake_plain_chat)

    result = await runner.run_skill("report", {
        "report_content": "分析结果",
        "output_type": "prd_draft",
    })

    assert result.status == "success"
    assert result.schema_valid is True
    assert result.diagnostics == []
    assert result.data["raw_text"].startswith("# PRD 草稿")


# ── 反向：空响应 / 任意 JSON 对象不得被当作报告成功 ──


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_output", [
    {"raw_text": ""},          # 空正文
    {"raw_text": "   "},       # 纯空格
    {"raw_text": "\n\t"},      # 纯换行/制表符
    {},                        # 空对象
    {"timeout": 30},           # JSON 误解析产物（正文被吞后的残留）
    {"markdown": "# 报告"},    # 键名不符
])
async def test_report_step_bad_output_fails_after_retries(monkeypatch, bad_output):
    import asyncio

    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()
    calls = []

    async def fake_plain_chat(messages, **kwargs):
        calls.append(1)
        return bad_output

    monkeypatch.setattr(skill_runner_module, "plain_chat", fake_plain_chat)
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    result = await runner.run_skill_with_retry("report", {
        "report_content": "原始报告",
        "output_type": "report",
    })

    assert result.is_error, f"{bad_output} 不得被当作报告成功"
    assert len(calls) == runner.step_max_retries, "应重试耗尽而非静默放行"


async def _fast_sleep(_delay):
    return None


@pytest.mark.asyncio
async def test_non_report_skills_still_use_structured_chat(monkeypatch):
    """结构化 JSON 步骤（如 classify）不受影响，仍走 structured_chat。"""
    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()
    runner.pipeline_state["docs"] = [{
        "doc_id": "1", "filename": "需求A.docx", "md_content": "正文",
    }]

    structured_calls = []

    async def fake_structured_chat(messages, **kwargs):
        structured_calls.append(1)
        return {"classifications": [{"doc_id": "1", "category": "功能需求", "confidence": 0.9}], "version_chains": []}

    async def fail_plain_chat(messages, **kwargs):
        raise AssertionError("classify 是结构化步骤，不得走 plain_chat")

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)
    monkeypatch.setattr(skill_runner_module, "plain_chat", fail_plain_chat)

    inputs = runner.build_step_inputs("classify", runner.pipeline_state)
    result = await runner.run_skill("classify", inputs)

    assert len(structured_calls) == 1
    assert result.status == "success"
