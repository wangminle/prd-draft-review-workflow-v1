from pathlib import Path
import sys

import pytest


@pytest.mark.asyncio
async def test_docx_conversion_accepts_skill_string_return(tmp_path, monkeypatch):
    from app.routers import review

    skills_dir = tmp_path / "skills"
    scripts_dir = skills_dir / "docx-to-markdown" / "scripts"
    scripts_dir.mkdir(parents=True)
    output_md = tmp_path / "converted.md"

    (scripts_dir / "convert_docx.py").write_text(
        "def convert_docx_to_markdown(file_path, output_dir):\n"
        f"    return {str(output_md)!r}\n",
        encoding="utf-8",
    )
    source_docx = tmp_path / "input.docx"
    source_docx.write_bytes(b"fake docx is enough because the skill is stubbed")

    monkeypatch.setattr(review, "SKILLS_DIR", str(skills_dir))
    sys.modules.pop("convert_docx", None)

    assert await review._convert_docx(str(source_docx), 123) == str(output_md)


def test_context_injection_includes_professional_guidance():
    from app.services.review_helpers import build_context_injection

    injection = build_context_injection({
        "specifications": ["需求必须包含验收口径"],
        "professional_guidance": ["优先关注跨部门协同边界"],
    })

    assert "业务规范约束" in injection
    assert "团队评审意见" in injection
    assert "跨部门协同边界" in injection


def test_default_review_context_includes_team_review_rules():
    from app.services.review_helpers import DEFAULT_TEAM_REVIEW_GUIDANCE, default_review_context

    context = default_review_context()

    assert context["professional_guidance"] == DEFAULT_TEAM_REVIEW_GUIDANCE
    assert len(context["professional_guidance"]) == 6
    assert "需求范围要写实" in context["professional_guidance"][0]
    assert "技术方案要分期但不能糊涂" in context["professional_guidance"][5]


def test_context_injection_uses_default_team_review_rules_without_saved_context():
    from app.services.review_helpers import build_context_injection, DEFAULT_TEAM_REVIEW_GUIDANCE

    injection = build_context_injection(None)

    assert "团队评审意见" in injection
    assert DEFAULT_TEAM_REVIEW_GUIDANCE[0] in injection
    assert DEFAULT_TEAM_REVIEW_GUIDANCE[5] in injection


def test_review_report_artifacts_are_extracted_from_step_details():
    from types import SimpleNamespace

    from app.routers.review import _extract_task_artifacts

    task = SimpleNamespace(
        step_details=(
            '{"insights":{"gap":{"summary":"存在空白"}}'
            ',"prd_draft":{"title":"新PRD"}'
            ',"report_markdown":"# 报告"}'
        )
    )

    artifacts = _extract_task_artifacts(task)

    assert artifacts["insights"]["gap"]["summary"] == "存在空白"
    assert artifacts["prd_draft"]["title"] == "新PRD"
    assert artifacts["report_markdown"] == "# 报告"


def test_markdown_report_prefers_stored_polished_report():
    from types import SimpleNamespace

    from app.routers.review import _render_markdown_report

    task = SimpleNamespace(
        mode="quick",
        context_version=1,
        step_details='{"report_markdown":"# 已润色报告\\n\\n正文"}',
    )

    assert _render_markdown_report([], {}, None, task) == "# 已润色报告\n\n正文"


def test_pipeline_failure_marks_current_step_failed():
    from types import SimpleNamespace

    from app.routers.review import _mark_current_step_failed

    task = SimpleNamespace(
        current_step=2,
        step_statuses='{"0":"completed","1":"completed","2":"running","3":"pending"}',
    )

    statuses = _mark_current_step_failed(task)

    assert statuses["2"] == "failed"
    assert statuses["3"] == "pending"
    assert task.step_statuses == '{"0": "completed", "1": "completed", "2": "failed", "3": "pending"}'


def test_finalize_task_failed_marks_current_step_and_completion_time():
    from types import SimpleNamespace

    from app.routers.review import _finalize_task_failed

    task = SimpleNamespace(
        status="running",
        current_step=5,
        step_statuses='{"0":"completed","1":"completed","5":"running"}',
        completed_at=None,
    )

    statuses = _finalize_task_failed(task)

    assert task.status == "failed"
    assert statuses["5"] == "failed"
    assert task.completed_at is not None


def test_review_retry_config_reads_timeout_settings(monkeypatch):
    from app.routers import review

    monkeypatch.setattr(review, "_settings", {
        "review": {
            "retry": {
                "max_attempts": 7,
                "initial_delay_ms": 1000,
                "backoff_factor": 1.5,
                "max_delay_ms": 20000,
                "timeout_seconds": 300,
                "connect_timeout_seconds": 12,
            }
        }
    })

    config = review._build_review_retry_config()

    assert config.max_attempts == 7
    assert config.timeout_seconds == 300
    assert config.connect_timeout_seconds == 12


def test_step_error_result_is_promoted_to_pipeline_failure():
    from types import SimpleNamespace

    import pytest
    from app.routers.review import _raise_if_step_failed

    result = SimpleNamespace(is_error=True, data={"error": "skill report failed after 3 retries"})

    with pytest.raises(RuntimeError, match="skill report failed"):
        _raise_if_step_failed("报告生成", result)


def test_system_review_cache_requires_pm_scores():
    from types import SimpleNamespace

    from app.routers.review import _system_review_has_complete_dimensions

    incomplete = SimpleNamespace(
        business_value='{"ok": true}',
        architecture='{"ok": true}',
        competition='{"ok": true}',
        product_strategy='{"ok": true}',
        tech_evolution='{"ok": true}',
        action_plan='{"ok": true}',
        pm_scores=None,
    )
    complete = SimpleNamespace(
        business_value='{"ok": true}',
        architecture='{"ok": true}',
        competition='{"ok": true}',
        product_strategy='{"ok": true}',
        tech_evolution='{"ok": true}',
        action_plan='{"ok": true}',
        pm_scores='{"writing_scores": {"logic": {"score": 4, "evidence": "结构清晰"}}}',
    )

    assert _system_review_has_complete_dimensions(incomplete) is False
    assert _system_review_has_complete_dimensions(complete) is True


def test_analysis_cache_requires_expert_review_block():
    from types import SimpleNamespace

    from app.routers.review import _analysis_has_required_expert_review

    old_analysis = SimpleNamespace(
        full_analysis='{"core_problem":"旧缓存","quality_score":4}'
    )
    complete_analysis = SimpleNamespace(
        full_analysis=(
            '{"expert_review":{"summary":"专家六项评审均通过，暂无额外修改意见。",'
            '"checks":['
            '{"rule_key":"scope_realism"},'
            '{"rule_key":"boundary_completeness"},'
            '{"rule_key":"structured_entitlements"},'
            '{"rule_key":"user_facing_naming"},'
            '{"rule_key":"copy_consistency"},'
            '{"rule_key":"phased_tech_plan"}'
            ']}}'
        )
    )

    assert _analysis_has_required_expert_review(old_analysis) is False
    assert _analysis_has_required_expert_review(complete_analysis) is True


def test_legacy_runtime_file_path_resolves_to_workspace_runtime(tmp_path, monkeypatch):
    from app.routers import review

    runtime_root = tmp_path / "runtime"
    source = runtime_root / "data" / "review_uploads" / "6" / "requirement" / "legacy.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"legacy docx")

    monkeypatch.setattr(review, "runtime_path", lambda *parts: runtime_root.joinpath(*parts))

    resolved = review._resolve_stored_file_path("./runtime/data/review_uploads/6/requirement/legacy.docx")

    assert resolved == str(source)


def test_parent_relative_runtime_file_path_resolves_to_workspace_runtime(tmp_path, monkeypatch):
    from app.routers import review

    runtime_root = tmp_path / "runtime"
    source = runtime_root / "data" / "review_uploads" / "6" / "requirement" / "legacy.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"legacy docx")

    monkeypatch.setattr(review, "runtime_path", lambda *parts: runtime_root.joinpath(*parts))

    resolved = review._resolve_stored_file_path("../../runtime/data/review_uploads/6/requirement/legacy.docx")

    assert resolved == str(source)


def test_configured_skills_dir_resolves_from_project_root_when_cwd_is_src(tmp_path, monkeypatch):
    from app.routers import review

    project_root = tmp_path / "app"
    src_root = project_root / "src"
    skills_root = project_root / "skills"
    skills_root.mkdir(parents=True)
    src_root.mkdir()

    fake_review_file = src_root / "app" / "routers" / "review.py"
    fake_review_file.parent.mkdir(parents=True)
    fake_review_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(review, "__file__", str(fake_review_file))
    monkeypatch.chdir(src_root)

    assert review._resolve_skills_dir("./skills") == str(skills_root.resolve())


def test_pm_assessment_payload_extraction_rejects_truncated_raw_text():
    from app.services.review_helpers import extract_pm_assessment_payload

    assert extract_pm_assessment_payload({"raw_text": '{"writing_scores": {"logic":'}) is None
    assert extract_pm_assessment_payload({
        "dimensions": {
            "pm_assessment": {
                "writing_scores": {"logic": {"score": 4, "evidence": "结构清晰"}},
                "thinking_scores": {"data": {"score": 3, "evidence": "有数据采集"}},
            }
        }
    })["writing_scores"]["logic"]["score"] == 4


def test_pm_assessment_payload_extraction_accepts_pm_scores_wrapper():
    from app.services.review_helpers import extract_pm_assessment_payload

    payload = {
        "pm_scores": {
            "writing_scores": {"logic": {"score": 4, "evidence": "结构清晰"}},
            "thinking_scores": {"data": {"score": 3, "evidence": "有数据采集"}},
        }
    }

    extracted = extract_pm_assessment_payload(payload)

    assert extracted["writing_scores"]["logic"]["score"] == 4
    assert extracted["thinking_scores"]["data"]["score"] == 3


def test_pm_assessment_payload_extraction_preserves_pm_like_payload_without_scores():
    from app.services.review_helpers import extract_pm_assessment_payload

    payload = {
        "pm_type": "均衡型",
        "highlights": ["结构较清晰"],
        "blindspots": ["缺少数据闭环"],
        "growth_path": {"short_term": ["补齐指标口径"]},
    }

    assert extract_pm_assessment_payload(payload) == payload


def test_system_review_dimension_unwraps_product_strategy_raw_text():
    from app.services.skill_runner import normalize_dimension_result

    result = normalize_dimension_result(
        "product-strategy",
        {
            "raw_text": (
                '{"product_strategy_assessment": {'
                '"current_strategy_assessment": {"prioritization": "合理"},'
                '"recommendations": [{"recommendation": "补齐口语化语音场景"}],'
                '"roadmap": [{"period": "Q1", "items": []}]'
                "}}"
            )
        },
    )

    assert "raw_text" not in result
    assert result["current_strategy_assessment"]["prioritization"] == "合理"
    assert result["recommendations"][0]["recommendation"] == "补齐口语化语音场景"
    assert result["roadmap"][0]["period"] == "Q1"


def test_system_review_dimension_unwraps_python_style_raw_text():
    from app.services.skill_runner import normalize_dimension_result

    result = normalize_dimension_result(
        "product-strategy",
        {
            "raw_text": (
                "{'product_strategy_assessment': {"
                "'current_strategy_assessment': {'prioritization': '合理'}, "
                "'recommendations': [], "
                "'roadmap': []"
                "}}"
            )
        },
    )

    assert "raw_text" not in result
    assert result["current_strategy_assessment"]["prioritization"] == "合理"


def test_system_review_api_parser_normalizes_persisted_raw_text():
    from app.routers.review import _parse_system_review_dimension

    raw = (
        '{"raw_text": "{\\"product_strategy_assessment\\": '
        '{\\"current_strategy_assessment\\": {\\"prioritization\\": \\"合理\\"}, '
        '\\"recommendations\\": [], \\"roadmap\\": []}}"}'
    )

    parsed = _parse_system_review_dimension(raw, "product-strategy")

    assert "raw_text" not in parsed
    assert parsed["current_strategy_assessment"]["prioritization"] == "合理"


def test_logging_detects_when_console_stream_is_app_log_file(tmp_path):
    from app.logging_config import _stream_points_to_path

    log_file = tmp_path / "app.log"
    log_file.write_text("", encoding="utf-8")

    with log_file.open("a", encoding="utf-8") as stream:
        assert _stream_points_to_path(stream, log_file) is True


def test_audit_log_writes_structured_jsonl_and_redacts_secrets(tmp_path):
    import json

    from app.logging_config import log_audit, setup_logging

    setup_logging(tmp_path)
    log_audit(
        "review.start",
        actor={"user_id": 8, "username": "user-public", "role": "user"},
        target_type="review_task",
        target_id=51,
        detail={"mode": "pm", "password": "secret", "document_ids": [35]},
    )

    row = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])

    assert row["action"] == "review.start"
    assert row["actor"]["username"] == "user-public"
    assert row["target"]["type"] == "review_task"
    assert row["target"]["id"] == 51
    assert row["detail"]["mode"] == "pm"
    assert row["detail"]["password"] == "***"


def test_skill_runner_state_supports_existing_dict_access(tmp_path):
    from app.services.skill_runner import SkillRunner

    runner = SkillRunner(
        model_cfg={"api_base": "", "api_key": "", "llm_model": ""},
        skills_dir=tmp_path,
    )

    runner.state["docs"] = [{"doc_id": "1", "md_content": "内容"}]
    runner.state["project_id"] = 123
    runner.state["prd_draft"] = {"title": "草稿"}

    assert runner.pipeline_state.get("docs")[0]["doc_id"] == "1"
    assert runner.pipeline_state["project_id"] == 123
    assert runner.pipeline_state.get("prd_draft")["title"] == "草稿"


def test_pm_assessment_dimension_inputs_include_original_docs(tmp_path):
    from app.services.skill_runner import SkillRunner

    runner = SkillRunner(
        model_cfg={"api_base": "", "api_key": "", "llm_model": ""},
        skills_dir=tmp_path,
    )
    runner.state["docs"] = [{
        "filename": "需求A.docx",
        "md_content": "未裁剪正文",
        "md_content_pruned": "已裁剪正文",
    }]
    runner.state["analyses"] = {
        "1": {"core_problem": "解决预约表达问题", "quality_score": 4}
    }

    inputs = runner._build_dimension_inputs("pm-assessment", {})

    assert "original_docs" in inputs
    assert "需求A.docx" in inputs["original_docs"]
    assert "已裁剪正文" in inputs["original_docs"]
    assert "{{original_docs}}" not in inputs["original_docs"]


def test_review_pipeline_passes_cancel_callback_into_long_skill_loops():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("src/app/routers/review.py").read_text(encoding="utf-8")

    assert "runner._run_per_analysis(only_doc_ids=uncached_ids, should_cancel=_check_cancelled)" in source
    assert "runner._run_system_review(should_cancel=_check_cancelled)" in source


def test_re_review_request_can_force_fresh_analysis():
    from app.schemas.review import StartReviewRequest

    req = StartReviewRequest(mode="quick", force_reanalysis=True)

    assert req.force_reanalysis is True


def test_review_pipeline_skips_analysis_cache_when_forced():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("src/app/routers/review.py").read_text(encoding="utf-8")

    assert "force_reanalysis: bool = False" in source
    assert "req.force_reanalysis" in source
    assert "cached_analyses = {} if force_reanalysis else await _find_cached_analyses" in source
    assert "if not force_reanalysis:" in source


def test_active_review_task_matching_uses_mode_and_document_scope():
    from types import SimpleNamespace

    from app.routers.review import _is_same_active_review_scope

    same_scope = SimpleNamespace(
        mode="insight",
        step_details='{"document_ids":[37,35],"historical_document_ids":[1]}',
    )
    different_docs = SimpleNamespace(
        mode="insight",
        step_details='{"document_ids":[37],"historical_document_ids":[1]}',
    )
    different_mode = SimpleNamespace(
        mode="review",
        step_details='{"document_ids":[35,37],"historical_document_ids":[1]}',
    )

    assert _is_same_active_review_scope(same_scope, "insight", [35, 37], [1]) is True
    assert _is_same_active_review_scope(different_docs, "insight", [35, 37], [1]) is False
    assert _is_same_active_review_scope(different_mode, "insight", [35, 37], [1]) is False


def test_source_hash_write_failure_is_non_fatal(tmp_path, caplog):
    from app.routers.review import _write_source_hash

    missing_parent_hash = tmp_path / "missing" / ".source_hash"

    assert _write_source_hash(str(missing_parent_hash), "abc123") is False
    assert "Failed to write source hash cache" in caplog.text


def test_all_conversion_failure_marks_preprocess_step_failed():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("src/app/routers/review.py").read_text(encoding="utf-8")
    conversion_failure_block = source.split("if not converted_docs:", 1)[1].split("doc_dicts = []", 1)[0]

    assert "step_statuses = _finalize_task_failed(task)" in conversion_failure_block


def test_issue_sse_ticket_prunes_expired_tickets():
    from datetime import datetime, timedelta, timezone

    from app.services import auth

    auth._sse_tickets.clear()
    auth._sse_tickets["expired-ticket"] = {
        "user_id": 1,
        "expires_at": datetime.now(timezone.utc) - timedelta(seconds=5),
    }

    ticket = auth.issue_sse_ticket(2)

    assert ticket in auth._sse_tickets
    assert "expired-ticket" not in auth._sse_tickets
