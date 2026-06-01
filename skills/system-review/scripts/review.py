#!/usr/bin/env python3
"""system-review: 体系化7维度Review，支持多种输出模式。

用法:
    python review.py <classify_json> <analysis_dir> <output_json> [options]

输入: prd-overview-classify输出JSON + prd-per-analysis输出目录
输出: 7维度分析结果JSON + 指定输出类型的Markdown报告
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("错误：需要 pydantic，请运行 pip install pydantic", file=sys.stderr)
    sys.exit(1)

DEFAULT_TEXT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_VISION_MODEL = "claude-sonnet-4-20250514"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

DIMENSION_NAMES = {
    1: "business_value",
    2: "architecture",
    3: "competition",
    4: "product_strategy",
    5: "tech_evolution",
    6: "pm_assessment",
    7: "action_plan",
}

DIMENSION_PROMPT_FILES = {
    1: "business-value.md",
    2: "architecture.md",
    3: "competition.md",
    4: "product-strategy.md",
    5: "tech-evolution.md",
    6: "pm-assessment.md",
    7: "action-plan.md",
}

OUTPUT_TYPE_FULL_REPORT = "full_report"
OUTPUT_TYPE_NEXT_DIRECTIONS = "next_directions"
OUTPUT_TYPE_QUALITY_ASSESSMENT = "quality_assessment"
OUTPUT_TYPE_PRD_DRAFT = "prd_draft"
OUTPUT_TYPE_ALL = "all"
VALID_OUTPUT_TYPES = [OUTPUT_TYPE_FULL_REPORT, OUTPUT_TYPE_NEXT_DIRECTIONS,
                     OUTPUT_TYPE_QUALITY_ASSESSMENT, OUTPUT_TYPE_PRD_DRAFT, OUTPUT_TYPE_ALL]

OUTPUT_TYPE_REQUIRED_DIMS = {
    OUTPUT_TYPE_FULL_REPORT: [1, 2, 3, 4, 5, 6, 7],
    OUTPUT_TYPE_NEXT_DIRECTIONS: [1, 2, 3, 4, 5, 7],
    OUTPUT_TYPE_QUALITY_ASSESSMENT: [1, 6],
    OUTPUT_TYPE_PRD_DRAFT: [1, 2, 5, 6],
    OUTPUT_TYPE_ALL: [1, 2, 3, 4, 5, 6, 7],
}


class StrategicScore(BaseModel):
    score: int = 0
    evidence: str = ""


class StrategicValue(BaseModel):
    user_value: StrategicScore = Field(default_factory=StrategicScore)
    tech_barrier: StrategicScore = Field(default_factory=StrategicScore)
    market_scale: StrategicScore = Field(default_factory=StrategicScore)
    strategic_synergy: StrategicScore = Field(default_factory=StrategicScore)
    feasibility: StrategicScore = Field(default_factory=StrategicScore)


class BusinessGoal(BaseModel):
    goal: str = ""
    coverage: str = "medium"
    gap: str = ""
    evidence: str = ""


class UserInsight(BaseModel):
    insight: str = ""
    source_doc_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class BusinessValueResult(BaseModel):
    strategic_value: StrategicValue = Field(default_factory=StrategicValue)
    business_goals: list[BusinessGoal] = Field(default_factory=list)
    user_insights: list[UserInsight] = Field(default_factory=list)


class EvolutionStage(BaseModel):
    stage: str = ""
    versions: list[str] = Field(default_factory=list)
    core_problems: list[str] = Field(default_factory=list)
    key_solutions: list[str] = Field(default_factory=list)


class CategoryAssessment(BaseModel):
    category: str = ""
    doc_count: int = 0
    assessment: str = "合理"
    note: str = ""


class DependencyIssue(BaseModel):
    type: str = ""
    description: str = ""
    severity: str = "medium"
    involved_docs: list[str] = Field(default_factory=list)


class ArchitectureGap(BaseModel):
    type: str = ""
    description: str = ""
    suggestion: str = ""


class ArchitectureResult(BaseModel):
    evolution_stages: list[EvolutionStage] = Field(default_factory=list)
    category_assessment: list[CategoryAssessment] = Field(default_factory=list)
    dependency_issues: list[DependencyIssue] = Field(default_factory=list)
    architecture_gaps: list[ArchitectureGap] = Field(default_factory=list)


class MarketLandscape(BaseModel):
    position: str = "exploring"
    key_players: list[str] = Field(default_factory=list)
    tech_route_difference: str = ""


class CompetitorDimension(BaseModel):
    dimension: str = ""
    us: str = ""
    competitors: list[dict] = Field(default_factory=list)


class Differentiation(BaseModel):
    unique_strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)


class CompetitionResult(BaseModel):
    market_landscape: MarketLandscape = Field(default_factory=MarketLandscape)
    competitor_comparison: list[CompetitorDimension] = Field(default_factory=list)
    differentiation: Differentiation = Field(default_factory=Differentiation)


class StrategyAssessment(BaseModel):
    prioritization: str = ""
    focus: str = ""
    consistency: str = ""
    evidence: str = ""


class StrategyRecommendation(BaseModel):
    recommendation: str = ""
    targets: str = ""
    reasoning: str = ""
    expected_impact: str = ""
    priority: str = "medium"


class RoadmapItem(BaseModel):
    action: str = ""
    category: str = ""
    depends_on: list[str] = Field(default_factory=list)


class RoadmapPeriod(BaseModel):
    period: str = ""
    items: list[RoadmapItem] = Field(default_factory=list)


class ProductStrategyResult(BaseModel):
    current_strategy_assessment: StrategyAssessment = Field(default_factory=StrategyAssessment)
    recommendations: list[StrategyRecommendation] = Field(default_factory=list)
    roadmap: list[RoadmapPeriod] = Field(default_factory=list)


class TechDecision(BaseModel):
    decision: str = ""
    assessment: str = "合理"
    risk: str = ""


class TechMetric(BaseModel):
    name: str = ""
    value: str = ""
    source_doc_ids: list[str] = Field(default_factory=list)


class TechDebt(BaseModel):
    item: str = ""
    severity: str = "medium"
    suggestion: str = ""


class TechEvolutionDetail(BaseModel):
    trend: str = ""
    tech_debt: list[TechDebt] = Field(default_factory=list)
    alignment_with_strategy: str = ""


class TechEvolutionRecommendation(BaseModel):
    action: str = ""
    reason: str = ""
    priority: str = "medium"


class TechEvolutionResult(BaseModel):
    current_architecture: dict = Field(default_factory=dict)
    key_metrics: list[TechMetric] = Field(default_factory=list)
    tech_evolution: TechEvolutionDetail = Field(default_factory=TechEvolutionDetail)
    evolution_recommendations: list[TechEvolutionRecommendation] = Field(default_factory=list)


class WritingScore(BaseModel):
    score: int = 0
    evidence: str = ""


class WritingScores(BaseModel):
    logic: WritingScore = Field(default_factory=WritingScore)
    tech_depth: WritingScore = Field(default_factory=WritingScore)
    boundary: WritingScore = Field(default_factory=WritingScore)
    business: WritingScore = Field(default_factory=WritingScore)


class ThinkingScores(BaseModel):
    iteration: WritingScore = Field(default_factory=WritingScore)
    experience: WritingScore = Field(default_factory=WritingScore)
    data: WritingScore = Field(default_factory=WritingScore)
    business: WritingScore = Field(default_factory=WritingScore)


class GrowthPath(BaseModel):
    short_term: list[str] = Field(default_factory=list)
    mid_term: list[str] = Field(default_factory=list)
    long_term: list[str] = Field(default_factory=list)


class PMAssessmentResult(BaseModel):
    writing_scores: WritingScores = Field(default_factory=WritingScores)
    thinking_scores: ThinkingScores = Field(default_factory=ThinkingScores)
    pm_type: str = "均衡型"
    highlights: list[str] = Field(default_factory=list)
    blindspots: list[str] = Field(default_factory=list)
    growth_path: GrowthPath = Field(default_factory=GrowthPath)


class ActionItem(BaseModel):
    action: str = ""
    source_dimension: str = ""
    urgency_reason: str = ""
    reason: str = ""
    success_criteria: str = ""
    priority: str = "medium"


class Milestone(BaseModel):
    time: str = ""
    goal: str = ""
    depends_on: list[str] = Field(default_factory=list)


class Risk(BaseModel):
    risk: str = ""
    impact: str = "medium"
    likelihood: str = "medium"
    mitigation: str = ""


class ActionResult(BaseModel):
    short_term: list[ActionItem] = Field(default_factory=list)
    mid_term: list[ActionItem] = Field(default_factory=list)
    long_term: list[ActionItem] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)


class DimensionResults(BaseModel):
    business_value: Optional[dict] = None
    architecture: Optional[dict] = None
    competition: Optional[dict] = None
    product_strategy: Optional[dict] = None
    tech_evolution: Optional[dict] = None
    pm_assessment: Optional[dict] = None
    action_plan: Optional[dict] = None


class ReviewMetadata(BaseModel):
    total_docs: int = 0
    dimensions_executed: list[int] = Field(default_factory=list)
    output_type: str = OUTPUT_TYPE_FULL_REPORT
    models_used: dict = Field(default_factory=dict)
    target_doc: str = ""


class ReviewResult(BaseModel):
    project_name: str = ""
    output_type: str = OUTPUT_TYPE_FULL_REPORT
    dimensions: DimensionResults = Field(default_factory=DimensionResults)
    reports: dict = Field(default_factory=dict)
    metadata: ReviewMetadata = Field(default_factory=ReviewMetadata)


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("错误：需要设置 ANTHROPIC_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)
    return key


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_classify_result(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_analysis_results(analysis_dir: Path) -> list[dict]:
    results = []
    if not analysis_dir.exists():
        return results
    for f in sorted(analysis_dir.iterdir()):
        if f.suffix == ".json" and not f.name.startswith("_"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    data["_source_file"] = f.name
                    results.append(data)
            except Exception as e:
                print(f"  警告：加载分析结果失败 {f.name}：{e}", file=sys.stderr)
    return results


def load_review_context(path: str) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"警告：加载Review Context失败：{e}", file=sys.stderr)
        return {}


def load_industry_template(industry: str) -> dict:
    if not industry:
        return {}
    template_path = TEMPLATES_DIR / f"industry-{industry}.json"
    if template_path.exists():
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_competition_refs(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def load_rubric(path: str) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def read_original_docs(classify_data: dict) -> list[dict]:
    docs = []
    for doc in classify_data.get("documents", []):
        md_path = doc.get("md_path", "")
        if md_path and Path(md_path).exists():
            try:
                content = Path(md_path).read_text(encoding="utf-8")
                docs.append({
                    "doc_id": doc.get("doc_id", ""),
                    "title": doc.get("title", ""),
                    "version": doc.get("version", ""),
                    "md_content": content,
                })
            except Exception:
                pass
    return docs


def build_analyses_summary(analyses: list[dict]) -> str:
    summaries = []
    for a in analyses:
        summaries.append({
            "doc_id": a.get("doc_id", ""),
            "core_problem": a.get("core_problem", ""),
            "category": a.get("category", ""),
            "boundary_issues_count": len(a.get("boundary_issues", [])),
            "quality_score": a.get("quality_score", 0),
            "key_points_type": a.get("key_points", {}).get("type", ""),
        })
    return json.dumps(summaries, ensure_ascii=False, indent=2)


def build_prior_context(completed_dims: dict, dim_number: int) -> str:
    context_parts = []
    for i in range(1, dim_number):
        dim_name = DIMENSION_NAMES.get(i, "")
        if dim_name in completed_dims:
            context_parts.append(f"### 维度{i}：{dim_name} 结论\n"
                                 + json.dumps(completed_dims[dim_name], ensure_ascii=False, indent=2))
    return "\n\n".join(context_parts)


def parse_dimension_output(text: str) -> dict:
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {"raw_output": text}


def execute_dimension(client, dim_number: int, context: dict, text_model: str) -> dict:
    dim_name = DIMENSION_NAMES[dim_number]
    prompt_file = DIMENSION_PROMPT_FILES[dim_number]

    system_prompt = load_prompt("system-context.md")
    dimension_prompt = load_prompt(prompt_file)

    if not dimension_prompt:
        print(f"  警告：未找到维度{dim_number}的Prompt文件 {prompt_file}", file=sys.stderr)
        return {}

    combined_system = f"{system_prompt}\n\n---\n\n{dimension_prompt}"

    user_parts = []
    user_parts.append(f"## 文档分类信息\n{json.dumps(context.get('categories', []), ensure_ascii=False, indent=2)}")
    user_parts.append(f"## 版本链信息\n{json.dumps(context.get('version_chains', []), ensure_ascii=False, indent=2)}")

    if context.get("doc_analyses_summary"):
        user_parts.append(f"## 逐篇分析结果\n{context['doc_analyses_summary']}")

    if context.get("doc_count"):
        user_parts.append(f"## 文档集规模\n{context['doc_count']}篇")

    if context.get("original_docs"):
        docs_excerpt = []
        for doc in context["original_docs"]:
            content = doc.get("md_content", "")
            if len(content) > 5000:
                content = content[:5000] + "\n...(截断)"
            docs_excerpt.append({"doc_id": doc.get("doc_id", ""),
                                 "title": doc.get("title", ""),
                                 "content_preview": content})
        user_parts.append(f"## 文档原文预览\n{json.dumps(docs_excerpt, ensure_ascii=False, indent=2)}")

    if dim_number == 6 and context.get("original_docs_full"):
        user_parts.append(f"## 所有文档原文（PM评估需要）\n{context['original_docs_full']}")

    if context.get("prior_dimensions"):
        user_parts.append(f"## 前置维度结论\n{context['prior_dimensions']}")

    if context.get("industry_context"):
        user_parts.append(f"## 行业背景\n{json.dumps(context['industry_context'], ensure_ascii=False, indent=2)}")

    if context.get("competition_references"):
        user_parts.append(f"## 竞品参考\n{context['competition_references']}")

    if context.get("scoring_overrides"):
        user_parts.append(f"## 评分量规覆盖\n{json.dumps(context['scoring_overrides'], ensure_ascii=False, indent=2)}")

    if context.get("writing_standard"):
        user_parts.append(f"## 写作规范\n{context['writing_standard']}")

    user_msg = "\n\n".join(user_parts)

    try:
        response = client.messages.create(
            model=text_model,
            max_tokens=4096,
            system=combined_system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return parse_dimension_output(response.content[0].text)
    except Exception as e:
        print(f"  错误：维度{dim_number}({dim_name})分析失败：{e}", file=sys.stderr)
        return {"error": str(e)}


def generate_full_report_md(dimensions: dict, project_name: str) -> str:
    lines = [f"# {project_name} — 体系化Review报告\n"]

    bv = dimensions.get("business_value", {})
    if bv:
        lines.append("## 一、业务价值分析\n")
        sv = bv.get("strategic_value", {})
        if sv:
            lines.append("### 战略价值评估\n")
            lines.append("| 维度 | 评分 | 证据 |")
            lines.append("|------|------|------|")
            for key, label in [("user_value", "用户价值"), ("tech_barrier", "技术壁垒"),
                               ("market_scale", "市场规模"), ("strategic_synergy", "战略协同"),
                               ("feasibility", "实现可行性")]:
                item = sv.get(key, {})
                lines.append(f"| {label} | {item.get('score', '-')} | {item.get('evidence', '-')} |")
            lines.append("")
        goals = bv.get("business_goals", [])
        if goals:
            lines.append("### 业务目标与差距\n")
            for g in goals:
                lines.append(f"- **{g.get('goal', '')}**（覆盖：{g.get('coverage', '')}）— 差距：{g.get('gap', '')}")
            lines.append("")
        insights = bv.get("user_insights", [])
        if insights:
            lines.append("### 用户洞察\n")
            for i in insights:
                lines.append(f"- {i.get('insight', '')}（来源：{', '.join(i.get('source_doc_ids', []))}，置信度：{i.get('confidence', '')}）")
            lines.append("")

    arch = dimensions.get("architecture", {})
    if arch:
        lines.append("## 二、需求体系架构\n")
        stages = arch.get("evolution_stages", [])
        if stages:
            lines.append("### 演进阶段\n")
            for s in stages:
                lines.append(f"**{s.get('stage', '')}**（{', '.join(s.get('versions', []))}）")
                for p in s.get("core_problems", []):
                    lines.append(f"  - 核心问题：{p}")
                for sol in s.get("key_solutions", []):
                    lines.append(f"  - 关键方案：{sol}")
            lines.append("")
        gaps = arch.get("architecture_gaps", [])
        if gaps:
            lines.append("### 架构问题\n")
            for g in gaps:
                lines.append(f"- [{g.get('type', '')}] {g.get('description', '')} → 建议：{g.get('suggestion', '')}")
            lines.append("")

    comp = dimensions.get("competition", {})
    if comp:
        lines.append("## 三、品牌与竞争定位\n")
        ml = comp.get("market_landscape", {})
        if ml:
            lines.append(f"市场位置：{ml.get('position', '')} | 主要玩家：{', '.join(ml.get('key_players', []))}\n")
        diff = comp.get("differentiation", {})
        if diff:
            lines.append("### 差异化\n")
            for s in diff.get("unique_strengths", []):
                lines.append(f"- 💪 优势：{s}")
            for w in diff.get("weaknesses", []):
                lines.append(f"- ⚠️ 短板：{w}")
            for o in diff.get("opportunities", []):
                lines.append(f"- 🔮 机会：{o}")
            lines.append("")

    ps = dimensions.get("product_strategy", {})
    if ps:
        lines.append("## 四、产品策略\n")
        assessment = ps.get("current_strategy_assessment", {})
        if assessment:
            lines.append(f"优先级：{assessment.get('prioritization', '')} | 聚焦：{assessment.get('focus', '')} | 一致性：{assessment.get('consistency', '')}\n")
        recs = ps.get("recommendations", [])
        if recs:
            lines.append("### 策略建议\n")
            for r in recs:
                lines.append(f"- **[{r.get('priority', '')}]** {r.get('recommendation', '')}（目标：{r.get('targets', '')}）")
            lines.append("")

    te = dimensions.get("tech_evolution", {})
    if te:
        lines.append("## 五、技术架构演进\n")
        ca = te.get("current_architecture", {})
        if ca:
            decisions = ca.get("core_decisions", [])
            if decisions:
                lines.append("### 核心技术决策\n")
                for d in decisions:
                    lines.append(f"- {d.get('decision', '')}（评估：{d.get('assessment', '')}）")
                lines.append("")
        debts = te.get("tech_evolution", {}).get("tech_debt", [])
        if debts:
            lines.append("### 技术债务\n")
            for d in debts:
                lines.append(f"- [{d.get('severity', '')}] {d.get('item', '')} → 建议：{d.get('suggestion', '')}")
            lines.append("")

    pm = dimensions.get("pm_assessment", {})
    if pm:
        lines.append("## 六、PM能力评估\n")
        lines.append(f"**PM类型：{pm.get('pm_type', '')}**\n")
        ws = pm.get("writing_scores", {})
        ts = pm.get("thinking_scores", {})
        if ws:
            lines.append("### 写作风格\n")
            for key, label in [("logic", "逻辑结构"), ("tech_depth", "技术深度"),
                               ("boundary", "边界意识"), ("business", "商业视角")]:
                s = ws.get(key, {})
                lines.append(f"- {label}：{s.get('score', '-')}分 — {s.get('evidence', '')}")
            lines.append("")
        if ts:
            lines.append("### 产品思维\n")
            for key, label in [("iteration", "迭代思维"), ("experience", "体验思维"),
                               ("data", "数据思维"), ("business", "商业思维")]:
                s = ts.get(key, {})
                lines.append(f"- {label}：{s.get('score', '-')}分 — {s.get('evidence', '')}")
            lines.append("")
        highlights = pm.get("highlights", [])
        blindspots = pm.get("blindspots", [])
        if highlights:
            lines.append("### 亮点\n")
            for h in highlights:
                lines.append(f"- ✅ {h}")
            lines.append("")
        if blindspots:
            lines.append("### 盲点\n")
            for b in blindspots:
                lines.append(f"- ❌ {b}")
            lines.append("")
        gp = pm.get("growth_path", {})
        if gp:
            lines.append("### 成长路径\n")
            lines.append(f"- 短期：{', '.join(gp.get('short_term', []))}")
            lines.append(f"- 中期：{', '.join(gp.get('mid_term', []))}")
            lines.append(f"- 镋期：{', '.join(gp.get('long_term', []))}")
            lines.append("")

    ap = dimensions.get("action_plan", {})
    if ap:
        lines.append("## 七、行动计划\n")
        for period_key, period_label in [("short_term", "短期1-3月"), ("mid_term", "中期3-6月"), ("long_term", "远期6-12月")]:
            items = ap.get(period_key, [])
            if items:
                lines.append(f"### {period_label}\n")
                for item in items:
                    lines.append(f"- **{item.get('action', '')}**（来源：{item.get('source_dimension', '')}，优先级：{item.get('priority', '')}）")
                    lines.append(f"  标准：{item.get('success_criteria', '')}")
                lines.append("")
        milestones = ap.get("milestones", [])
        if milestones:
            lines.append("### 里程碑\n")
            for m in milestones:
                lines.append(f"- {m.get('time', '')}：{m.get('goal', '')}")
            lines.append("")
        risks = ap.get("risks", [])
        if risks:
            lines.append("### 风险\n")
            for r in risks:
                lines.append(f"- [{r.get('impact', '')}影响/{r.get('likelihood', '')}概率] {r.get('risk', '')} → 缓解：{r.get('mitigation', '')}")
            lines.append("")

    return "\n".join(lines)


def generate_next_directions_md(dimensions: dict, project_name: str) -> str:
    lines = [f"# {project_name} — 下一步需求方向建议\n"]

    bv = dimensions.get("business_value", {})
    if bv:
        lines.append("## 当前业务目标与差距\n")
        for g in bv.get("business_goals", []):
            lines.append(f"- **{g.get('goal', '')}**（覆盖：{g.get('coverage', '')}）— 差距：{g.get('gap', '')}")
        lines.append("")

    arch = dimensions.get("architecture", {})
    if arch:
        gaps = arch.get("architecture_gaps", [])
        if gaps:
            lines.append("## 架构层面的需求方向\n")
            for g in gaps:
                if g.get("type") == "coverage_gap":
                    lines.append(f"- 🔴 **缺失方向**：{g.get('description', '')} → 建议：{g.get('suggestion', '')}")
                elif g.get("type") == "redundancy":
                    lines.append(f"- 🟡 **冗余方向**：{g.get('description', '')} → 建议：{g.get('suggestion', '')}")
            lines.append("")

    comp = dimensions.get("competition", {})
    if comp:
        diff = comp.get("differentiation", {})
        opps = diff.get("opportunities", [])
        if opps:
            lines.append("## 竞争驱动的需求方向\n")
            for o in opps:
                lines.append(f"- 🔮 差异化机会：{o}")
            lines.append("")

    ps = dimensions.get("product_strategy", {})
    if ps:
        recs = ps.get("recommendations", [])
        if recs:
            lines.append("## 策略建议中的需求方向\n")
            for r in recs:
                lines.append(f"- [{r.get('priority', '')}] {r.get('recommendation', '')}（目标：{r.get('targets', '')}）")
            lines.append("")

    te = dimensions.get("tech_evolution", {})
    if te:
        debts = te.get("tech_evolution", {}).get("tech_debt", [])
        if debts:
            lines.append("## 技术驱动的需求方向\n")
            for d in debts:
                if d.get("severity") == "high":
                    lines.append(f"- 🔴 **紧急**：{d.get('item', '')} → 建议：{d.get('suggestion', '')}")
                else:
                    lines.append(f"- 🟡 {d.get('item', '')} → 建议：{d.get('suggestion', '')}")
            lines.append("")

    ap = dimensions.get("action_plan", {})
    if ap:
        lines.append("## 优先级行动项\n")
        for period_key, period_label in [("short_term", "短期"), ("mid_term", "中期")]:
            items = ap.get(period_key, [])
            if items:
                lines.append(f"### {period_label}\n")
                for item in items:
                    lines.append(f"- **{item.get('action', '')}**（优先级：{item.get('priority', '')}）")
                lines.append("")

    return "\n".join(lines)


def generate_quality_assessment_md(dimensions: dict, project_name: str) -> str:
    lines = [f"# {project_name} — PRD撰写质量评估\n"]

    pm = dimensions.get("pm_assessment", {})
    if not pm:
        return lines[0] + "\n\nPM评估数据不可用。\n"

    lines.append(f"## PM类型：{pm.get('pm_type', '未确定')}\n")

    ws = pm.get("writing_scores", {})
    if ws:
        lines.append("## 写作风格评估\n")
        lines.append("| 维度 | 评分 | 证据 |")
        lines.append("|------|------|------|")
        for key, label in [("logic", "逻辑结构"), ("tech_depth", "技术深度"),
                           ("boundary", "边界意识"), ("business", "商业视角")]:
            s = ws.get(key, {})
            lines.append(f"| {label} | {s.get('score', '-')} | {s.get('evidence', '-')} |")
        lines.append("")

    ts = pm.get("thinking_scores", {})
    if ts:
        lines.append("## 产品思维评估\n")
        lines.append("| 维度 | 评分 | 证据 |")
        lines.append("|------|------|------|")
        for key, label in [("iteration", "迭代思维"), ("experience", "体验思维"),
                           ("data", "数据思维"), ("business", "商业思维")]:
            s = ts.get(key, {})
            lines.append(f"| {label} | {s.get('score', '-')} | {s.get('evidence', '-')} |")
        lines.append("")

    highlights = pm.get("highlights", [])
    blindspots = pm.get("blindspots", [])
    if highlights:
        lines.append("## 亮点\n")
        for h in highlights:
            lines.append(f"- ✅ {h}")
        lines.append("")
    if blindspots:
        lines.append("## 盲点\n")
        for b in blindspots:
            lines.append(f"- ❌ {b}")
        lines.append("")

    gp = pm.get("growth_path", {})
    if gp:
        lines.append("## 成长路径\n")
        for key, label in [("short_term", "短期1-3月"), ("mid_term", "中期3-6月"), ("long_term", "远期6-12月")]:
            items = gp.get(key, [])
            if items:
                lines.append(f"### {label}\n")
                for i in items:
                    lines.append(f"- {i}")
                lines.append("")

    bv = dimensions.get("business_value", {})
    if bv:
        insights = bv.get("user_insights", [])
        if insights:
            lines.append("## 从业务价值看质量\n")
            for i in insights:
                lines.append(f"- {i.get('insight', '')}（置信度：{i.get('confidence', '')}）")
            lines.append("")

    return "\n".join(lines)


def generate_prd_draft_md(dimensions: dict, project_name: str, target_doc: str,
                          analyses: list[dict], classify_data: dict) -> str:
    lines = [f"# {project_name} — 基于历史分析的需求文档初稿\n"]
    lines.append(f"> 基于历史需求分析，为文档 `{target_doc}` 提供上下文支持并生成PRD初稿\n")

    bv = dimensions.get("business_value", {})
    if bv:
        lines.append("## 一、业务背景\n")
        goals = bv.get("business_goals", [])
        if goals:
            lines.append("### 核心业务目标\n")
            for g in goals:
                lines.append(f"- {g.get('goal', '')}（当前覆盖：{g.get('coverage', '')}）")
            lines.append("")
        insights = bv.get("user_insights", [])
        if insights:
            lines.append("### 用户洞察\n")
            for i in insights:
                lines.append(f"- {i.get('insight', '')}")
            lines.append("")

    arch = dimensions.get("architecture", {})
    if arch:
        gaps = arch.get("architecture_gaps", [])
        if gaps:
            lines.append("## 二、需求演进脉络\n")
            stages = arch.get("evolution_stages", [])
            for s in stages:
                lines.append(f"**{s.get('stage', '')}**：{', '.join(s.get('key_solutions', []))}")
            lines.append("")
            lines.append("### 待解决的架构问题\n")
            for g in gaps:
                if g.get("type") == "coverage_gap":
                    lines.append(f"- 🔴 {g.get('description', '')}")
            lines.append("")

    target_analyses = [a for a in analyses if a.get("doc_id") == target_doc]
    if not target_analyses:
        target_analyses = analyses[:3]
    if target_analyses:
        lines.append("## 三、相关需求的边界外问题（历史参考）\n")
        for a in target_analyses:
            issues = a.get("boundary_issues", [])
            for bi in issues:
                res = bi.get("resolution", {})
                status = res.get("status", "unresolved")
                lines.append(f"- {'🔴' if status == 'unresolved' else '🟡' if status == 'partial' else '🟢'} "
                             f"{bi.get('issue', '')}（严重度：{bi.get('severity', '')}，状态：{status}）")
        lines.append("")

    te = dimensions.get("tech_evolution", {})
    if te:
        metrics = te.get("key_metrics", [])
        if metrics:
            lines.append("## 四、关键技术参数（历史参考）\n")
            lines.append("| 参数 | 值 | 来源 |")
            lines.append("|------|------|------|")
            for m in metrics:
                lines.append(f"| {m.get('name', '')} | {m.get('value', '')} | {', '.join(m.get('source_doc_ids', []))} |")
            lines.append("")

    lines.append("## 五、需求文档初稿\n")
    lines.append("### 1. 需求概述\n")
    lines.append("（基于上述分析，请补充具体需求概述）\n")
    lines.append("### 2. 适用范围\n")
    arch_gaps_for_scope = [g for g in arch.get("architecture_gaps", []) if g.get("type") == "coverage_gap"]
    if arch_gaps_for_scope:
        lines.append("建议覆盖以下方向：")
        for g in arch_gaps_for_scope:
            lines.append(f"- {g.get('suggestion', '')}")
    else:
        lines.append("（请补充适用范围）")
    lines.append("")
    lines.append("### 3. 不涉及范围\n")
    lines.append("（请补充不涉及范围）\n")
    lines.append("### 4. 核心功能\n")
    lines.append("（请补充核心功能描述）\n")
    lines.append("### 5. 关键参数\n")
    lines.append("（参考第四节中的历史参数，定义新文档的参数配置）\n")
    lines.append("### 6. 验收标准\n")
    lines.append("（请补充验收标准）\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="体系化7维度Review")
    parser.add_argument("classify_json", help="prd-overview-classify输出JSON路径")
    parser.add_argument("analysis_dir", help="prd-per-analysis输出目录")
    parser.add_argument("output_json", help="输出JSON文件路径")
    parser.add_argument("--output-type", default=OUTPUT_TYPE_FULL_REPORT,
                        choices=VALID_OUTPUT_TYPES,
                        help="输出类型（默认：full_report）")
    parser.add_argument("--dimensions", default="",
                        help="指定执行的维度，逗号分隔（如1,6,7），默认根据output-type决定")
    parser.add_argument("--target-doc", default="",
                        help="目标文档ID（prd_draft模式或为特定文档生成上下文支持）")
    parser.add_argument("--industry", default="",
                        help="行业领域（如smart_home），影响竞品对标维度")
    parser.add_argument("--competition-refs", default="",
                        help="竞品参考文件路径")
    parser.add_argument("--rubric", default="",
                        help="PM评分量规JSON路径（覆盖默认标准）")
    parser.add_argument("--review-context", default="",
                        help="Review Context JSON路径（评分量规/写作规范/领域规则）")
    parser.add_argument("--enable-vision", action="store_true", help="启用图片理解引擎")
    args = parser.parse_args()

    classify_path = Path(args.classify_json)
    if not classify_path.exists():
        print(f"错误：分类结果文件不存在：{classify_path}", file=sys.stderr)
        sys.exit(1)

    analysis_dir = Path(args.analysis_dir)
    if not analysis_dir.exists():
        print(f"错误：分析结果目录不存在：{analysis_dir}", file=sys.stderr)
        sys.exit(1)

    api_key = get_api_key()
    try:
        import anthropic
    except ImportError:
        print("错误：需要 anthropic，请运行 pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    text_model = os.environ.get("TEXT_MODEL", DEFAULT_TEXT_MODEL)
    vision_model = os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL)

    print("=== 体系化7维度Review ===")
    print(f"输出类型：{args.output_type}")
    print(f"文本引擎：{text_model}")

    classify_data = load_classify_result(classify_path)
    analyses = load_analysis_results(analysis_dir)
    project_name = classify_data.get("project_name", classify_path.stem)

    print(f"项目：{project_name} | 文档数：{len(classify_data.get('documents', []))} | 分析结果：{len(analyses)}篇")

    if args.dimensions:
        target_dims = [int(d.strip()) for d in args.dimensions.split(",") if d.strip().isdigit()]
    else:
        target_dims = OUTPUT_TYPE_REQUIRED_DIMS.get(args.output_type, list(range(1, 8)))

    review_ctx = load_review_context(args.review_context)
    industry_ctx = load_industry_template(args.industry)
    comp_refs = load_competition_refs(args.competition_refs)
    rubric = load_rubric(args.rubric)

    original_docs = read_original_docs(classify_data)
    analyses_summary = build_analyses_summary(analyses)

    scoring_overrides = review_ctx.get("scoring_overrides", {})
    if rubric:
        scoring_overrides.update(rubric)
    writing_standard = ""
    for spec in review_ctx.get("specifications", []):
        if spec.get("type") == "writing_standard":
            writing_standard = spec.get("content", "")
        elif spec.get("type") == "scoring_rubric":
            try:
                rubric_data = json.loads(spec["content"]) if isinstance(spec["content"], str) else spec["content"]
                scoring_overrides.update(rubric_data)
            except Exception:
                pass

    base_context = {
        "categories": classify_data.get("categories", []),
        "version_chains": classify_data.get("version_chains", []),
        "dependencies": classify_data.get("dependencies", []),
        "doc_analyses_summary": analyses_summary,
        "doc_count": len(classify_data.get("documents", [])),
        "original_docs": original_docs,
        "industry_context": industry_ctx,
        "competition_references": comp_refs,
        "scoring_overrides": scoring_overrides,
        "writing_standard": writing_standard,
    }

    if 6 in target_dims:
        full_docs_content = json.dumps(
            [{"doc_id": d["doc_id"], "title": d["title"], "md_content": d["md_content"]}
             for d in original_docs],
            ensure_ascii=False
        )
        base_context["original_docs_full"] = full_docs_content

    completed_dims = {}
    dim_results = DimensionResults()

    for dim_num in sorted(target_dims):
        dim_name = DIMENSION_NAMES[dim_num]
        print(f"\n正在分析维度{dim_num}：{dim_name}...")

        prior_context_str = build_prior_context(completed_dims, dim_num)
        context = {**base_context, "prior_dimensions": prior_context_str}

        result = execute_dimension(client, dim_num, context, text_model)

        if "error" in result:
            print(f"  ⚠️ 维度{dim_num}分析出错，跳过")
        else:
            completed_dims[dim_name] = result
            setattr(dim_results, dim_name, result)
            print(f"  ✓ 维度{dim_num}完成")

    reports = {}

    if args.output_type in [OUTPUT_TYPE_FULL_REPORT, OUTPUT_TYPE_ALL]:
        reports["full_report_md"] = generate_full_report_md(completed_dims, project_name)
        print(f"\n已生成完整Review报告（{len(reports['full_report_md'])}字符）")

    if args.output_type in [OUTPUT_TYPE_NEXT_DIRECTIONS, OUTPUT_TYPE_ALL]:
        reports["next_directions_md"] = generate_next_directions_md(completed_dims, project_name)
        print(f"已生成下一步需求方向建议（{len(reports['next_directions_md'])}字符）")

    if args.output_type in [OUTPUT_TYPE_QUALITY_ASSESSMENT, OUTPUT_TYPE_ALL]:
        reports["quality_assessment_md"] = generate_quality_assessment_md(completed_dims, project_name)
        print(f"已生成PM撰写质量评估（{len(reports['quality_assessment_md'])}字符）")

    if args.output_type in [OUTPUT_TYPE_PRD_DRAFT, OUTPUT_TYPE_ALL]:
        if args.target_doc:
            reports["prd_draft_md"] = generate_prd_draft_md(
                completed_dims, project_name, args.target_doc, analyses, classify_data)
            print(f"已生成PRD初稿（{len(reports['prd_draft_md'])}字符）")
        else:
            print("提示：prd_draft模式建议指定 --target-doc 以生成针对性初稿")

    result = ReviewResult(
        project_name=project_name,
        output_type=args.output_type,
        dimensions=dim_results,
        reports=reports,
        metadata=ReviewMetadata(
            total_docs=len(classify_data.get("documents", [])),
            dimensions_executed=target_dims,
            output_type=args.output_type,
            models_used={"text": text_model, "vision": vision_model},
            target_doc=args.target_doc,
        ),
    )

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2, ensure_ascii=False))

    for report_name, content in reports.items():
        report_path = output_path.parent / f"{output_path.stem}_{report_name.replace('_md', '.md')}"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"报告已保存至：{report_path}")

    print(f"\n结果已保存至：{output_path}")
    print(f"已完成维度：{[DIMENSION_NAMES[d] for d in target_dims if DIMENSION_NAMES.get(d) in completed_dims]}")


if __name__ == "__main__":
    main()
