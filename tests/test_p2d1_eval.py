"""P2.D.1 检索评估自动化测试。

验证评估脚本的正确性：
1. 文档加载与切块正确性
2. 问题生成完整性（自动问题 + 补充问题）
3. 命中判定逻辑
4. 评估结果 JSON 结构
5. 报告文件格式
"""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_p2d1_eval.py"
EVAL_DIR = PROJECT_ROOT / "eval" / "p2d1"
RESULTS_JSON = EVAL_DIR / "p2d1_results.json"
REPORT_MD = EVAL_DIR / "P2D1-检索评估报告.md"


class TestEvalScriptExists:
    """评估脚本存在性检查。"""

    def test_eval_script_exists(self):
        assert SCRIPT_PATH.exists(), f"评估脚本不存在: {SCRIPT_PATH}"

    def test_eval_script_has_main(self):
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "async def run_evaluation" in content
        assert "def main" in content


class TestDocumentLoading:
    """POC 样例文档加载正确性。"""

    def test_poc_samples_dir_exists(self):
        samples_dir = PROJECT_ROOT / "poc-a" / "samples"
        assert samples_dir.exists(), f"POC 样例目录不存在: {samples_dir}"

    def test_prd_samples_exist(self):
        prd_dir = PROJECT_ROOT / "poc-a" / "samples" / "prds"
        assert prd_dir.exists(), f"PRD 样例目录不存在: {prd_dir}"
        prd_files = list(prd_dir.glob("*.md"))
        assert len(prd_files) >= 20, f"PRD 文档不足 20 份: {len(prd_files)}"

    def test_norm_samples_exist(self):
        norm_dir = PROJECT_ROOT / "poc-a" / "samples" / "norms"
        assert norm_dir.exists(), f"规范样例目录不存在: {norm_dir}"
        norm_files = list(norm_dir.glob("*.md"))
        assert len(norm_files) >= 5, f"规范文档不足 5 份: {len(norm_files)}"

    def test_report_samples_exist(self):
        report_dir = PROJECT_ROOT / "poc-a" / "samples" / "reports"
        assert report_dir.exists(), f"报告样例目录不存在: {report_dir}"
        report_files = list(report_dir.glob("*.md"))
        assert len(report_files) >= 5, f"报告文档不足 5 份: {len(report_files)}"

    def test_load_poc_samples_function(self):
        """测试 load_poc_samples 函数能正确加载文档。"""
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import load_poc_samples

        docs = load_poc_samples()
        assert len(docs) == 30, f"应加载 30 份文档，实际 {len(docs)}"
        # 检查每份文档包含必要字段
        for doc in docs:
            assert "filename" in doc
            assert "title" in doc
            assert "content" in doc
            assert "doc_type" in doc
            assert doc["doc_type"] in ("prd", "norm", "report")
            assert len(doc["content"]) > 100

    def test_document_type_distribution(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import load_poc_samples

        docs = load_poc_samples()
        prds = [d for d in docs if d["doc_type"] == "prd"]
        norms = [d for d in docs if d["doc_type"] == "norm"]
        reports = [d for d in docs if d["doc_type"] == "report"]
        assert len(prds) == 20
        assert len(norms) == 5
        assert len(reports) == 5


class TestQuestionGeneration:
    """评估问题生成正确性。"""

    def test_auto_questions_count(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import load_poc_samples, generate_auto_questions

        docs = load_poc_samples()
        questions = generate_auto_questions(docs)
        # 30 docs × 1 (title_find) = 30, 大部分有 section_find
        assert len(questions) >= 30, f"至少 30 个自动问题，实际 {len(questions)}"
        # 全部应该是 title_find 或 section_find
        categories = {q.category for q in questions}
        assert categories <= {"title_find", "section_find"}

    def test_supplemental_questions_count(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import load_poc_samples, generate_supplemental_questions

        docs = load_poc_samples()
        questions = generate_supplemental_questions(docs)
        assert len(questions) == 20, f"补充问题应为 20 条，实际 {len(questions)}"

    def test_supplemental_no_answer_count(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import load_poc_samples, generate_supplemental_questions

        docs = load_poc_samples()
        questions = generate_supplemental_questions(docs)
        no_answer = [q for q in questions if q.category == "no_answer"]
        assert len(no_answer) == 8, f"no_answer 问题应为 8 条，实际 {len(no_answer)}"
        # no_answer 问题的 expect_source_titles 应为空
        for q in no_answer:
            assert q.expect_source_titles == []

    def test_supplemental_category_distribution(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import load_poc_samples, generate_supplemental_questions

        docs = load_poc_samples()
        questions = generate_supplemental_questions(docs)
        semantic = [q for q in questions if q.category == "semantic_match"]
        cross_doc = [q for q in questions if q.category == "cross_doc"]
        no_answer = [q for q in questions if q.category == "no_answer"]
        assert len(semantic) == 8
        assert len(cross_doc) == 4
        assert len(no_answer) == 8


class TestHitDetermination:
    """命中判定逻辑测试。"""

    def test_title_matches_exact(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import _title_matches

        assert _title_matches("001-智能对话系统", ["智能对话系统"])
        assert _title_matches("智能对话系统", ["001-智能对话系统"])

    def test_title_matches_partial(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import _title_matches

        # 包含关系
        assert _title_matches("智能对话系统需求文档", ["智能对话系统"])

    def test_title_no_match(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import _title_matches

        assert not _title_matches("知识库资料管理", ["智能对话系统"])

    def test_title_matches_empty_expected(self):
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from run_p2d1_eval import _title_matches

        assert not _title_matches("智能对话系统", [])


class TestEvalResults:
    """评估结果 JSON 文件结构和验收标准测试。"""

    @pytest.fixture
    def results_data(self):
        if not RESULTS_JSON.exists():
            pytest.skip("评估结果文件不存在，请先运行 python3 scripts/run_p2d1_eval.py")
        with open(RESULTS_JSON, encoding="utf-8") as f:
            return json.load(f)

    def test_results_json_has_summary(self, results_data):
        assert "summary" in results_data
        summary = results_data["summary"]
        assert "total_questions" in summary
        assert "top5_hit_rate" in summary
        assert "top1_hit_rate" in summary
        assert "no_answer_rejection_rate" in summary
        assert "passed" in summary

    def test_top5_hit_rate_passes_threshold(self, results_data):
        """P2.D.1 验收: top-5 命中率 ≥ 80%。"""
        rate = results_data["summary"]["top5_hit_rate"]
        assert rate >= 0.80, f"top-5 命中率 {rate:.1%} < 80% 门槛"

    def test_top5_hit_rate_meets_expectation(self, results_data):
        """P2.D.1 预期: top-5 命中率 ≥ 92%（使用真实 OpenAI embedding）。"""
        rate = results_data["summary"]["top5_hit_rate"]
        assert rate >= 0.92, f"top-5 命中率 {rate:.1%} < 92% 预期值"

    def test_no_answer_rejection_rate(self, results_data):
        """P2.D.1 验收: no_answer 拒答率 ≥ 50%。"""
        rate = results_data["summary"]["no_answer_rejection_rate"]
        assert rate >= 0.50, f"no_answer 拒答率 {rate:.1%} < 50%"

    def test_no_permission_violations(self, results_data):
        """P2.D.1 验收: 无越权召回。"""
        violations = results_data["summary"]["permission_violations"]
        assert violations == 0, f"存在 {violations} 条越权召回"

    def test_overall_passed(self, results_data):
        """P2.D.1 整体验收通过。"""
        assert results_data["summary"]["passed"], "P2.D.1 评估未通过验收"

    def test_results_json_has_details(self, results_data):
        assert "details" in results_data
        details = results_data["details"]
        assert len(details) >= 80, f"评估问题数不足: {len(details)}"

    def test_detail_record_fields(self, results_data):
        details = results_data["details"]
        if not details:
            pytest.skip("无详情数据")
        first = details[0]
        required_fields = [
            "qid", "query", "category", "top1_hit", "top5_hit",
            "no_answer_correct", "latency_ms", "confidence_top1",
            "rejected_top1", "dist_top1", "gap_top1_top2",
            "returned_source_ids", "returned_source_titles",
        ]
        for field in required_fields:
            assert field in first, f"详情记录缺少字段: {field}"

    def test_category_coverage(self, results_data):
        """验证评估覆盖了所有 5 类问题。"""
        details = results_data["details"]
        categories = {d["category"] for d in details}
        required = {"title_find", "section_find", "semantic_match", "cross_doc", "no_answer"}
        assert required.issubset(categories), f"缺少类别: {required - categories}"

    def test_no_answer_records_all_present(self, results_data):
        """验证 no_answer 问题全部存在。"""
        details = results_data["details"]
        no_answer = [d for d in details if d["category"] == "no_answer"]
        assert len(no_answer) >= 4, f"no_answer 问题不足 4 条: {len(no_answer)}"

    def test_latency_reasonable(self, results_data):
        """验证延迟在合理范围内（< 5s 每次查询）。"""
        details = results_data["details"]
        for d in details:
            assert d["latency_ms"] < 5000, f"查询 {d['qid']} 延迟 {d['latency_ms']:.0f}ms 超过 5s"


class TestEvalReport:
    """评估报告 Markdown 格式测试。"""

    @pytest.fixture
    def report_text(self):
        if not REPORT_MD.exists():
            pytest.skip("评估报告不存在，请先运行 python3 scripts/run_p2d1_eval.py")
        return REPORT_MD.read_text(encoding="utf-8")

    def test_report_has_title(self, report_text):
        assert "# P2.D.1 检索评估报告" in report_text

    def test_report_has_acceptance_section(self, report_text):
        assert "验收结论" in report_text

    def test_report_has_overall_metrics(self, report_text):
        assert "总体指标" in report_text
        assert "top-5 命中率" in report_text

    def test_report_has_category_rates(self, report_text):
        assert "分类命中率" in report_text

    def test_report_has_no_answer_analysis(self, report_text):
        assert "no_answer" in report_text

    def test_report_has_distance_analysis(self, report_text):
        assert "距离分布" in report_text

    def test_report_shows_pass_verdict(self, report_text):
        assert "✅ 通过" in report_text
