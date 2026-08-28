#!/usr/bin/env python3
"""BUG-163：补齐 Skill 审计（design/3-plans/项目Skill审查与业务漏洞分析-20260811.md）
第九节建议测试清单中的缺失项。

覆盖点：
1. docx-to-markdown：清洗后同名/近同名文件不互相覆盖（sanitize_stem 附加哈希）。
   （“源文件变化后缓存失效”已由 tests/test_skill_docx_audit.py::TestSentinelSourceHash
   的 test_hash_mismatch_reconverts 覆盖，此处不重复。）
2. docx-to-markdown：单 entry 解压大小超 100MB 的 DOCX 被 validate_docx_zip_security 拒绝。
3. report-generator：markdown_to_pdf 生成含中文的 PDF，pdfminer 可提取出中文文本。
   （项目依赖中无 pypdf，环境中有 pdfminer.six，故用 pdfminer 做提取验证。）
4. prd-per-analysis 线上校验路径：专家检查项缺失 / 重复 rule_key / 非法状态时失败。
5. system-review：全失败/部分失败的评审结果不会被 find_cached_system_review 复用。
6. system-review：argparse 不存在 --enable-vision 参数。
7. report-generator：缺少可选输入（--insights-json）时报告有明确标注。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

DOCX_SCRIPTS = ROOT / "skills" / "docx-to-markdown" / "scripts"
if str(DOCX_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DOCX_SCRIPTS))

REPORT_SCRIPTS = ROOT / "skills" / "report-generator" / "scripts"
if str(REPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(REPORT_SCRIPTS))

import convert_docx  # noqa: E402
import generate  # noqa: E402


def _make_minimal_docx(path: Path, text: bytes = b"hello") -> None:
    """构造一个最小合法 DOCX（仅 word/document.xml）。"""
    document_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>' + text + b'</w:t></w:r></w:p></w:body>'
        b'</w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)


# ───────────────────── 1. docx 同名/近同名不互相覆盖 ─────────────────────

class TestSanitizeStemCollision:
    def test_near_identical_names_map_to_different_folders(self):
        """清洗后同名的两个原始文件名应映射到不同目录名。"""
        folder_a = convert_docx.sanitize_stem("A:B")
        folder_b = convert_docx.sanitize_stem("A?B")
        # 两者都被清洗为 "A_B" 前缀，但附加的源名哈希必须不同
        assert folder_a != folder_b
        assert folder_a.startswith("A_B_")
        assert folder_b.startswith("A_B_")

    def test_same_name_maps_to_same_folder(self):
        """同一原始文件名应稳定映射到同一目录（否则缓存失效）。"""
        assert convert_docx.sanitize_stem("A:B") == convert_docx.sanitize_stem("A:B")

    def test_conversion_outputs_do_not_overwrite(self, tmp_path):
        """端到端：A:B.docx 与 A?B.docx 转换到同一输出目录，互不覆盖。"""
        out_dir = tmp_path / "out"
        results = []
        for name in ("A:B.docx", "A?B.docx"):
            docx_path = tmp_path / name
            _make_minimal_docx(docx_path)
            md_path = convert_docx.convert_docx_to_markdown(str(docx_path), str(out_dir))
            results.append(md_path)
        assert results[0] != results[1]
        for md_path in results:
            assert os.path.isfile(md_path)
        # 两个输出目录各自有独立 sentinel
        assert len(list(Path(out_dir).iterdir())) == 2


# ───────────────────── 2. 超大 ZIP entry 被拒绝 ─────────────────────

class TestOversizedZipEntry:
    def test_single_entry_over_100mb_rejected(self, tmp_path):
        """单 entry 解压大小超过 100MB 的 DOCX 应被拒绝。

        validate_docx_zip_security 只读 ZIP 元数据（infolist），不解压，
        因此用高度可压缩的零字节填充即可低成本构造超限 entry。
        """
        docx_path = tmp_path / "huge.docx"
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"<doc/>")
            # 100MB+1 解压大小（压缩后极小，写入快）
            entry_limit = convert_docx.DOCX_SECURITY_LIMITS["entry_uncompressed"]
            zf.writestr("word/media/pad.bin", b"\x00" * (entry_limit + 1))

        with zipfile.ZipFile(docx_path, "r") as zf:
            with pytest.raises(convert_docx.DocxSecurityError, match="单文件上限"):
                convert_docx.validate_docx_zip_security(zf)

    def test_entry_just_under_limit_accepted(self, tmp_path):
        """单 entry 略低于 100MB 阈值时不应被该检查拦截。"""
        docx_path = tmp_path / "ok.docx"
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"<doc/>")
            entry_limit = convert_docx.DOCX_SECURITY_LIMITS["entry_uncompressed"]
            # 非 word/media 路径：避免触发第二层的单图大小限制，隔离 entry 大小检查
            zf.writestr("word/embeddings/pad.bin", b"\x00" * (entry_limit - 1024))

        # 不抛异常（零字节压缩比极高，但压缩后体积 < 1MB，不触发总压缩比检查；
        # 单 entry 压缩比检查可能触发，因此这里调高超限以隔离单 entry 大小路径）
        from unittest import mock
        with mock.patch.dict(convert_docx.DOCX_SECURITY_LIMITS, {"entry_ratio": 10**12}):
            with zipfile.ZipFile(docx_path, "r") as zf:
                convert_docx.validate_docx_zip_security(zf)


# ───────────────────── 3. 中文 PDF 可提取文本 ─────────────────────

class TestChinesePdfExtraction:
    def test_chinese_pdf_text_extractable(self, tmp_path):
        """markdown_to_pdf 生成的中文 PDF，pdfminer 可提取出可读中文。

        项目依赖中无 pypdf，环境中有 pdfminer.six，故用 pdfminer 提取验证；
        同时断言使用了 CJK 字体（STSong-Light），保证中文不是渲染为空白。
        """
        pdf_path = tmp_path / "中文报告.pdf"
        ok = generate.markdown_to_pdf(
            "# 需求评审报告\n\n这是中文段落：预约入口、权限管理、灰度发布。\n", pdf_path
        )
        assert ok is True
        assert pdf_path.exists()

        # 降级验证：PDF 字节流中应注册了 CJK 字体
        raw = pdf_path.read_bytes()
        assert b"STSong-Light" in raw

        from pdfminer.high_level import extract_text
        text = extract_text(str(pdf_path))
        assert "需求评审报告" in text
        assert "预约入口" in text


# ───────────────────── 4. per-analysis 专家规则校验（线上路径）─────────────────────

def _valid_checks() -> list[dict]:
    keys = [
        ("scope_realism", "需求范围要写实"),
        ("boundary_completeness", "能力边界要写全"),
        ("structured_entitlements", "权益和分类要结构化"),
        ("user_facing_naming", "用户侧命名要可理解"),
        ("copy_consistency", "多入口文案要统一"),
        ("phased_tech_plan", "技术方案要分期但不能糊涂"),
    ]
    return [
        {"rule_key": k, "rule_name": n, "status": "pass", "evidence": "已说明", "suggestion": "保持"}
        for k, n in keys
    ]


def _per_analysis_data(checks: list[dict]) -> dict:
    return {
        "core_problem": "统一预约入口",
        "category": "功能需求",
        "quality_score": 4,
        "expert_review": {"summary": "", "checks": checks},
    }


class TestExpertReviewValidation:
    """skill_runner._validate_expert_review_block：缺失/重复/非法状态均应失败。"""

    @pytest.mark.asyncio
    async def test_missing_rule_key_fails(self, tmp_path):
        from app.services.skill_runner import SkillRunner, SkillStepResult

        runner = SkillRunner(
            model_cfg={"api_base": "http://example.test", "api_key": "k", "llm_model": "m"},
            skills_dir=tmp_path,
        )
        checks = _valid_checks()[:-1]  # 去掉 phased_tech_plan
        result = await runner.after_step("per_analysis", SkillStepResult(data=_per_analysis_data(checks)))

        assert result.status == "error"
        assert "missing rules" in result.data["error"]
        assert "phased_tech_plan" in result.data["error"]

    @pytest.mark.asyncio
    async def test_duplicate_rule_key_fails(self, tmp_path):
        from app.services.skill_runner import SkillRunner, SkillStepResult

        runner = SkillRunner(
            model_cfg={"api_base": "http://example.test", "api_key": "k", "llm_model": "m"},
            skills_dir=tmp_path,
        )
        checks = _valid_checks()
        # 重复 scope_realism（再追加一条），六项仍齐全但存在重复
        checks.append({**checks[0]})
        result = await runner.after_step("per_analysis", SkillStepResult(data=_per_analysis_data(checks)))

        assert result.status == "error"
        assert "duplicate rules" in result.data["error"]
        assert "scope_realism" in result.data["error"]

    @pytest.mark.asyncio
    async def test_invalid_status_fails(self, tmp_path):
        from app.services.skill_runner import SkillRunner, SkillStepResult

        runner = SkillRunner(
            model_cfg={"api_base": "http://example.test", "api_key": "k", "llm_model": "m"},
            skills_dir=tmp_path,
        )
        checks = _valid_checks()
        checks[2]["status"] = "unknown_status"  # 不在 pass/risk/missing 枚举内
        result = await runner.after_step("per_analysis", SkillStepResult(data=_per_analysis_data(checks)))

        assert result.status == "error"
        assert "invalid status" in result.data["error"]
        assert "structured_entitlements" in result.data["error"]

    @pytest.mark.asyncio
    async def test_valid_checks_pass(self, tmp_path):
        from app.services.skill_runner import SkillRunner, SkillStepResult

        runner = SkillRunner(
            model_cfg={"api_base": "http://example.test", "api_key": "k", "llm_model": "m"},
            skills_dir=tmp_path,
        )
        result = await runner.after_step("per_analysis", SkillStepResult(data=_per_analysis_data(_valid_checks())))
        assert result.status == "success"


# ───────────────────── 5. system-review 错误结果不写缓存 ─────────────────────

_COMPLETE_DIM = '{"summary": "ok"}'
_VALID_PM_SCORES = json.dumps({"writing_scores": {"logic": {"score": 4, "evidence": "结构清晰"}}})


@pytest.mark.asyncio
async def test_failed_system_review_not_cached():
    """全失败/部分失败的 SystemReview 不应被 find_cached_system_review 复用。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.review import ReviewProject, ReviewTask, SystemReview
    from app.models.user import Base
    from app.repositories.review_task_repository import ReviewTaskRepository

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as db:
        proj = ReviewProject(name="p")
        db.add(proj)
        await db.flush()

        # 任务1：全失败（所有维度为空）
        task_all_failed = ReviewTask(project_id=proj.id, mode="full")
        db.add(task_all_failed)
        await db.flush()
        db.add(SystemReview(
            task_id=task_all_failed.id, project_id=proj.id,
            business_value=None, architecture=None, competition=None,
            product_strategy=None, tech_evolution=None, action_plan=None,
            pm_scores=None,
        ))

        # 任务2：部分失败（缺 competition 维度与 pm_scores）
        task_partial = ReviewTask(project_id=proj.id, mode="full")
        db.add(task_partial)
        await db.flush()
        db.add(SystemReview(
            task_id=task_partial.id, project_id=proj.id,
            business_value=_COMPLETE_DIM, architecture=_COMPLETE_DIM,
            competition=None,  # 该维度失败
            product_strategy=_COMPLETE_DIM, tech_evolution=_COMPLETE_DIM,
            action_plan=_COMPLETE_DIM,
            pm_scores=_VALID_PM_SCORES,
        ))

        # 任务3：完整成功
        task_ok = ReviewTask(project_id=proj.id, mode="full")
        db.add(task_ok)
        await db.flush()
        db.add(SystemReview(
            task_id=task_ok.id, project_id=proj.id,
            business_value=_COMPLETE_DIM, architecture=_COMPLETE_DIM,
            competition=_COMPLETE_DIM, product_strategy=_COMPLETE_DIM,
            tech_evolution=_COMPLETE_DIM, action_plan=_COMPLETE_DIM,
            pm_scores=_VALID_PM_SCORES,
        ))
        await db.commit()

        repo = ReviewTaskRepository(db)
        hit = await repo.find_cached_system_review(proj.id)
        assert hit is not None
        # 命中的必须是完整成功的那条，而不是（更新的）失败结果
        assert hit.task_id == task_ok.id

    async with session_maker() as db:
        # 只有失败结果时，缓存应完全 miss
        proj2 = ReviewProject(name="p2")
        db.add(proj2)
        await db.flush()
        task_fail = ReviewTask(project_id=proj2.id, mode="full")
        db.add(task_fail)
        await db.flush()
        db.add(SystemReview(
            task_id=task_fail.id, project_id=proj2.id,
            business_value=_COMPLETE_DIM, architecture=_COMPLETE_DIM,
            competition=None, product_strategy=_COMPLETE_DIM,
            tech_evolution=_COMPLETE_DIM, action_plan=_COMPLETE_DIM,
            pm_scores=_VALID_PM_SCORES,
        ))
        await db.commit()

        repo = ReviewTaskRepository(db)
        assert await repo.find_cached_system_review(proj2.id) is None

    await engine.dispose()


# ───────────────────── 6. --enable-vision 已移除 ─────────────────────

class TestEnableVisionRemoved:
    REVIEW_PY = ROOT / "skills" / "system-review" / "scripts" / "review.py"

    def test_no_enable_vision_in_source(self):
        src = self.REVIEW_PY.read_text(encoding="utf-8")
        assert "--enable-vision" not in src
        assert "enable_vision" not in src

    def test_no_enable_vision_in_help(self):
        proc = subprocess.run(
            [sys.executable, str(self.REVIEW_PY), "--help"],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0
        assert "--enable-vision" not in proc.stdout


# ───────────────────── 7. report-generator 缺可选输入标注 ─────────────────────

class TestMissingOptionalInputAnnotation:
    def test_per_analysis_annotates_missing_insights(self):
        """无洞察数据且无版本链时，演进脉络章节应有明确标注而非静默消失。"""
        md = generate.generate_per_analysis_md("测试项目", [], {"documents": []}, {})
        assert "## 四、需求演进脉络" in md
        assert "未提供需求洞察数据" in md

    def test_per_analysis_no_annotation_when_insights_present(self):
        """有洞察数据时正常渲染演进图，不出现缺数据标注。"""
        md = generate.generate_per_analysis_md(
            "测试项目", [], {"documents": []},
            {"evolution": {"mermaid_graph": "flowchart TD\n    a --> b"}},
        )
        assert "未提供需求洞察数据" not in md

    def test_next_directions_annotates_missing_insights(self):
        """有体系评审数据但无洞察数据时，应标注不含演进/缺口层面建议。"""
        review_data = {
            "dimensions": {
                "business_value": {
                    "business_goals": [{"goal": "提升转化", "coverage": "60%", "gap": "入口分散"}],
                },
            },
        }
        md = generate.generate_next_directions_md("测试项目", review_data, {})
        assert "提升转化" in md
        assert "未提供需求洞察数据" in md

    def test_next_directions_all_data_missing_annotated(self):
        """评审与洞察数据都缺时，应明确标注而非输出只有标题的空报告。"""
        md = generate.generate_next_directions_md("测试项目", {}, {})
        assert "暂无法生成下一步方向建议" in md
        assert "未提供需求洞察数据" in md

    def test_insights_report_empty_data_annotated(self):
        """需求洞察报告在无数据时已有明确标注（回归保护）。"""
        md = generate.generate_insights_md("测试项目", {})
        assert "无洞察数据" in md
