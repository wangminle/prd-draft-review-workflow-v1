"""POC-A 统一评估框架 — 所有检索方案共用同一个评估口径。

评估指标：
1. top-5 命中率：30 个问题中，返回的 top-5 结果包含期望文档的比例
2. top-1 命中率：返回的第一个结果是否命中期望文档
3. 平均延迟：每个查询的响应时间（ms）
4. 权限过滤正确率：10 个权限用例中，越权结果数为 0 的比例
"""

import json
import time
import csv
from pathlib import Path
from dataclasses import dataclass, asdict

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# ── 检索问题集 ──

QUESTIONS = [
    # 章节查找类 (8)
    {"qid": "Q-01", "query": "需求评审的完整流程是怎样的", "expect_ids": ["NORM-001", "prd-002-需求审查工作台"], "expect_sections": ["2", "3"], "category": "section_find"},
    {"qid": "Q-02", "query": "JWT鉴权的具体实现方案", "expect_ids": ["prd-005-用户认证与安全", "NORM-005"], "expect_sections": ["4", "3"], "category": "section_find"},
    {"qid": "Q-03", "query": "PRD应该包含哪些必要章节", "expect_ids": ["NORM-002", "prd-014-审查快照与版本"], "expect_sections": ["1", "2"], "category": "section_find"},
    {"qid": "Q-04", "query": "团队空间的角色权限怎么划分", "expect_ids": ["prd-013-权限RBAC模型", "prd-003-团队空间管理"], "expect_sections": ["3", "4"], "category": "section_find"},
    {"qid": "Q-05", "query": "向量检索和FTS检索有什么区别", "expect_ids": ["prd-016-知识库检索RAG"], "expect_sections": ["4"], "category": "section_find"},
    {"qid": "Q-06", "query": "Agent工具调用需要审批吗", "expect_ids": ["prd-015-Agent对话与工具", "prd-019-个人Agent与消息"], "expect_sections": ["7", "4"], "category": "section_find"},
    {"qid": "Q-07", "query": "审查快照为什么需要冻结", "expect_ids": ["prd-014-审查快照与版本"], "expect_sections": ["3"], "category": "section_find"},
    {"qid": "Q-08", "query": "飞书集成需要哪些配置项", "expect_ids": ["prd-011-飞书集成导入"], "expect_sections": ["3"], "category": "section_find"},
    # 风险定位类 (8)
    {"qid": "Q-09", "query": "多轮对话有哪些常见风险", "expect_ids": ["prd-001-智能对话系统", "rpt-001-智能对话审查报告"], "expect_sections": ["6", "3"], "category": "risk_find"},
    {"qid": "Q-10", "query": "权限绕过的典型场景", "expect_ids": ["rpt-003-团队空间审查报告", "prd-013-权限RBAC模型"], "expect_sections": ["2", "6"], "category": "risk_find"},
    {"qid": "Q-11", "query": "知识库上传有没有安全隐患", "expect_ids": ["rpt-004-知识库审查报告", "NORM-005"], "expect_sections": ["2", "4"], "category": "risk_find"},
    {"qid": "Q-12", "query": "审查流程可能在哪里断裂", "expect_ids": ["rpt-002-需求审查工作台报告", "NORM-001"], "expect_sections": ["3", "4"], "category": "risk_find"},
    {"qid": "Q-13", "query": "Mermaid渲染失败的兜底方案", "expect_ids": ["prd-010-Mermaid图表渲染"], "expect_sections": ["5"], "category": "risk_find"},
    {"qid": "Q-14", "query": "数据导出有没有隐私泄露风险", "expect_ids": ["prd-006-数据导出与报表", "NORM-005"], "expect_sections": ["5", "5"], "category": "risk_find"},
    {"qid": "Q-15", "query": "停用成员还能访问项目吗", "expect_ids": ["prd-003-团队空间管理", "rpt-003-团队空间审查报告"], "expect_sections": ["5", "4"], "category": "risk_find"},
    {"qid": "Q-16", "query": "Agent循环失控怎么防止", "expect_ids": ["prd-015-Agent对话与工具"], "expect_sections": ["5"], "category": "risk_find"},
    # 术语解释类 (5)
    {"qid": "Q-17", "query": "SkillRunner是什么", "expect_ids": ["prd-002-需求审查工作台"], "expect_sections": ["2"], "category": "term_explain"},
    {"qid": "Q-18", "query": "workspace_id的作用是什么", "expect_ids": ["prd-003-团队空间管理", "prd-013-权限RBAC模型"], "expect_sections": ["1", "2"], "category": "term_explain"},
    {"qid": "Q-19", "query": "什么是知识快照冻结", "expect_ids": ["prd-014-审查快照与版本"], "expect_sections": ["1"], "category": "term_explain"},
    {"qid": "Q-20", "query": "require_action怎么用", "expect_ids": ["prd-013-权限RBAC模型"], "expect_sections": ["4"], "category": "term_explain"},
    {"qid": "Q-21", "query": "content_hash有什么用途", "expect_ids": ["prd-004-知识库资料管理"], "expect_sections": ["3"], "category": "term_explain"},
    # 跨文档对比类 (5)
    {"qid": "Q-22", "query": "用户认证和API鉴权有什么区别", "expect_ids": ["prd-005-用户认证与安全"], "expect_sections": ["4", "5"], "category": "cross_doc"},
    {"qid": "Q-23", "query": "FTS5检索和向量检索各自的优势", "expect_ids": ["prd-016-知识库检索RAG"], "expect_sections": ["4"], "category": "cross_doc"},
    {"qid": "Q-24", "query": "PRD写作规范和接口设计规范有什么重叠", "expect_ids": ["NORM-002", "NORM-004"], "expect_sections": ["2", "2"], "category": "cross_doc"},
    {"qid": "Q-25", "query": "个人Agent和团队Agent权限范围有什么不同", "expect_ids": ["prd-015-Agent对话与工具", "prd-019-个人Agent与消息"], "expect_sections": ["4", "3"], "category": "cross_doc"},
    {"qid": "Q-26", "query": "审查报告和审查流程规范在风险描述上有什么不同", "expect_ids": ["rpt-001-智能对话审查报告", "NORM-001"], "expect_sections": ["3", "4"], "category": "cross_doc"},
    # 无答案类 (4)
    {"qid": "Q-27", "query": "系统支持多语言国际化吗", "expect_ids": [], "expect_sections": [], "category": "no_answer"},
    {"qid": "Q-28", "query": "有没有移动端适配方案", "expect_ids": [], "expect_sections": [], "category": "no_answer"},
    {"qid": "Q-29", "query": "如何配置第三方短信服务商", "expect_ids": [], "expect_sections": [], "category": "no_answer"},
    {"qid": "Q-30", "query": "系统有没有内置数据可视化仪表盘", "expect_ids": [], "expect_sections": [], "category": "no_answer"},
]

# ── 权限过滤用例 ──

PERMISSION_CASES = [
    {"pid": "P-01", "role": "owner", "workspace": "ws-1", "query": "需求评审流程", "expect_nonempty": True, "expect_prefixes": ["norm-001", "prd-002"]},
    {"pid": "P-02", "role": "admin", "workspace": "ws-1", "query": "JWT鉴权", "expect_nonempty": True, "expect_prefixes": ["prd-005", "norm-005"]},
    {"pid": "P-03", "role": "member", "workspace": "ws-1", "query": "权限绕过", "expect_nonempty": True, "expect_prefixes": ["rpt-003", "prd-013"]},
    {"pid": "P-04", "role": "viewer", "workspace": "ws-1", "query": "SkillRunner定义", "expect_nonempty": True, "expect_prefixes": ["prd-002"]},
    {"pid": "P-05", "role": "inactive", "workspace": "ws-1", "query": "需求评审流程", "expect_nonempty": False, "expect_prefixes": []},
    {"pid": "P-06", "role": "member", "workspace": "ws-2", "query": "JWT鉴权", "expect_nonempty": False, "expect_prefixes": []},
    {"pid": "P-07", "role": "owner", "workspace": "ws-2", "query": "代码提交规范", "expect_nonempty": True, "expect_prefixes": ["norm-003"]},
    {"pid": "P-08", "role": "member", "workspace": "ws-2", "query": "需求评审流程", "expect_nonempty": True, "expect_prefixes": ["norm-001"]},
    {"pid": "P-09", "role": "viewer", "workspace": "ws-1", "query": "Agent工具审批", "expect_nonempty": True, "expect_prefixes": ["prd-015"]},
    {"pid": "P-10", "role": "non-member", "workspace": "ws-1", "query": "任何问题", "expect_nonempty": False, "expect_prefixes": []},
]


# ── workspace → 文档映射 ──
# ws-1 包含全部 30 份文档，ws-2 只包含 NORM-001~005

WS1_DOC_IDS = None  # 延迟初始化，加载所有文档
WS2_DOC_IDS = None  # 延迟初始化，加载所有 norm 文档

def _init_ws2_docs():
    """延迟加载 ws-2 的文档 ID（所有规范类文档）。"""
    from chunking import load_all_samples
    global WS2_DOC_IDS
    if WS2_DOC_IDS is None:
        docs = load_all_samples()
        WS2_DOC_IDS = [sid for sid, stype, _, _ in docs if stype == "norm"]


def _init_ws1_docs():
    """延迟加载 ws-1 的全部文档 ID。"""
    from chunking import load_all_samples
    global WS1_DOC_IDS
    if WS1_DOC_IDS is None:
        docs = load_all_samples()
        WS1_DOC_IDS = [sid for sid, _, _, _ in docs]


@dataclass
class QueryResult:
    qid: str
    query: str
    top_results: list[dict]  # [{source_id, section, text_snippet, score}]
    latency_ms: float
    hit: bool  # top-5 是否包含期望文档


@dataclass
class EvalResult:
    solution_name: str
    top5_hit_rate: float
    top1_hit_rate: float
    avg_latency_ms: float
    permission_accuracy: float
    category_hit_rates: dict  # {category: hit_rate}
    details: list[QueryResult]


def evaluate_retrieval(solution_name: str, retrieve_fn, top_k: int = 5) -> EvalResult:
    """
    通用评估函数。retrieve_fn(query, workspace_id, top_k) → list[{source_id, section, text, score}]

    所有 POC 方案传入自己的 retrieve_fn 即可使用统一口径评估。
    """
    _init_ws1_docs()
    _init_ws2_docs()
    RESULTS_DIR.mkdir(exist_ok=True)

    query_results = []
    top5_hits = 0
    top1_hits = 0
    total_latency = 0.0
    category_hits = {}

    for q in QUESTIONS:
        start = time.perf_counter()
        results = retrieve_fn(q["query"], "ws-1", top_k)
        latency = (time.perf_counter() - start) * 1000

        # 命中判断：top-5 中任一结果的 source_id 与期望匹配
        result_ids = [r["source_id"] for r in results[:top_k]]
        first_id = result_ids[0] if result_ids else None

        hit5 = any(rid in q["expect_ids"] for rid in result_ids) if q["expect_ids"] else len(result_ids) == 0
        hit1 = first_id in q["expect_ids"] if q["expect_ids"] and first_id else (first_id is None and not q["expect_ids"])

        top5_hits += int(hit5)
        top1_hits += int(hit1)
        total_latency += latency

        cat = q["category"]
        if cat not in category_hits:
            category_hits[cat] = {"hits": 0, "total": 0}
        category_hits[cat]["hits"] += int(hit5)
        category_hits[cat]["total"] += 1

        query_results.append(QueryResult(
            qid=q["qid"],
            query=q["query"],
            top_results=results[:top_k],
            latency_ms=round(latency, 2),
            hit=hit5,
        ))

    # 权限过滤评估
    perm_correct = 0
    for p in PERMISSION_CASES:
        ws_docs = WS1_DOC_IDS if p["workspace"] == "ws-1" else WS2_DOC_IDS
        start = time.perf_counter()
        results = retrieve_fn(p["query"], p["workspace"], top_k)
        latency = (time.perf_counter() - start) * 1000

        result_ids = [r["source_id"] for r in results]

        if not p["expect_nonempty"]:
            # 期望空结果：inactive/non-member/ws-2不包含的
            correct = len(result_ids) == 0
        else:
            # 期望有结果：所有返回的文档 ID 都应在该 workspace 可见范围内
            correct = all(rid in ws_docs for rid in result_ids) and len(result_ids) > 0

        perm_correct += int(correct)

    n_questions = len(QUESTIONS)
    n_perms = len(PERMISSION_CASES)

    cat_rates = {cat: hits["hits"] / hits["total"] for cat, hits in category_hits.items()}

    eval_result = EvalResult(
        solution_name=solution_name,
        top5_hit_rate=round(top5_hits / n_questions, 4),
        top1_hit_rate=round(top1_hits / n_questions, 4),
        avg_latency_ms=round(total_latency / n_questions, 2),
        permission_accuracy=round(perm_correct / n_perms, 4),
        category_hit_rates=cat_rates,
        details=query_results,
    )

    # 保存结果
    out_path = RESULTS_DIR / f"{solution_name}_eval.json"
    out_path.write_text(json.dumps(asdict(eval_result), ensure_ascii=False, indent=2), encoding="utf-8")

    return eval_result


def print_eval_summary(result: EvalResult):
    """打印评估摘要。"""
    print(f"\n{'='*60}")
    print(f"  {result.solution_name} 评估结果")
    print(f"{'='*60}")
    print(f"  top-5 命中率: {result.top5_hit_rate:.1%} ({int(result.top5_hit_rate*30)}/30)")
    print(f"  top-1 呕中率: {result.top1_hit_rate:.1%}")
    print(f"  平均延迟: {result.avg_latency_ms:.1f} ms")
    print(f"  权限过滤正确率: {result.permission_accuracy:.1%} ({int(result.permission_accuracy*10)}/10)")
    print(f"\n  分类别命中率:")
    for cat, rate in result.category_hit_rates.items():
        print(f"    {cat}: {rate:.1%}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    print(f"Questions: {len(QUESTIONS)}")
    print(f"Permission cases: {len(PERMISSION_CASES)}")
    for q in QUESTIONS[:3]:
        print(f"  {q['qid']}: {q['query']} → {q['expect_ids']}")