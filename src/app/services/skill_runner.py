"""SkillRunner — Pi-inspired deterministic pipeline orchestrator with hooks and pruning."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.services.skill_prompts import SkillPromptLoader
from app.services.skill_schema import SkillSchemaLoader
from app.services.skill_prune import strip_base64_images, truncate_for_classify, truncate_for_analysis
from app.services.retry import structured_chat, RetryConfig
from app.services.review_helpers import extract_pm_assessment_payload, build_context_injection, json_from_raw_text

logger = logging.getLogger(__name__)


_DIMENSION_PAYLOAD_KEYS = {
    "business-value": ("business_value", "business_value_analysis"),
    "architecture": ("architecture", "requirement_architecture", "architecture_assessment"),
    "competition": ("competition", "competitive_positioning", "competition_assessment"),
    "product-strategy": ("product_strategy", "product_strategy_assessment"),
    "tech-evolution": ("tech_evolution", "technical_evolution", "tech_evolution_assessment"),
    "pm-assessment": ("pm_assessment", "pm_scores"),
    "action-plan": ("action_plan", "action_plan_assessment"),
}


def normalize_dimension_result(dim_name: str, result: dict) -> dict:
    """Normalize common LLM wrappers into the direct dimension payload."""
    if not isinstance(result, dict):
        return result

    raw_text = result.get("raw_text")
    if isinstance(raw_text, str):
        parsed = json_from_raw_text(raw_text)
        if parsed:
            result = parsed

    dimensions = result.get("dimensions")
    if isinstance(dimensions, dict):
        for key in _DIMENSION_PAYLOAD_KEYS.get(dim_name, ()):
            nested = dimensions.get(key)
            if isinstance(nested, dict):
                return nested

    for key in _DIMENSION_PAYLOAD_KEYS.get(dim_name, ()):
        nested = result.get(key)
        if isinstance(nested, dict):
            return nested

    return result


async def _cancel_requested(should_cancel) -> bool:
    if should_cancel is None:
        return False
    result = should_cancel()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


# ── Pi-inspired: SkillStepResult ──

@dataclass
class SkillStepResult:
    """Unified output structure for each pipeline step.

    Inspired by Pi's tool result: {content, details, isError, terminate}.
    """
    status: str = "success"         # "success" | "error" | "partial"
    data: dict = field(default_factory=dict)  # structured JSON output
    markdown: str = ""              # Markdown format output (for reports)
    diagnostics: list[str] = field(default_factory=list)  # schema errors, repair logs
    artifacts: dict = field(default_factory=dict)  # extra outputs (mermaid, coverage_matrix)
    schema_valid: bool | None = None  # passed schema validation?

    @property
    def is_error(self) -> bool:
        return self.status == "error"


# ── Pi-inspired: PipelineState ──

class PipelineState:
    """Typed pipeline state — replaces raw dict with structured access and pruning."""

    def __init__(self):
        self.docs: list[dict] = []
        self.classify: dict = {}
        self.analyses: dict[str, dict] = {}
        self.review_dimensions: dict = {}
        self.insights: dict = {}
        self.report: dict = {}
        self.project_id: int | None = None
        self.extra: dict = {}

    def __getitem__(self, key: str):
        if hasattr(self, key):
            return getattr(self, key)
        return self.extra[key]

    def __setitem__(self, key: str, value) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self.extra[key] = value

    def setdefault(self, key: str, default=None):
        if hasattr(self, key):
            val = getattr(self, key)
            if val is None and default is not None:
                setattr(self, key, default)
                return default
            return val if val is not None else default
        if key not in self.extra:
            self.extra[key] = default
        return self.extra[key]

    def get(self, key: str, default=None):
        if hasattr(self, key):
            return getattr(self, key)
        return self.extra.get(key, default)

    def prune_docs(self) -> PipelineState:
        """Strip base64 images and truncate md_content in all docs."""
        for doc in self.docs:
            raw_md = doc.get("md_content", "")
            doc["md_content"] = strip_base64_images(raw_md)
            doc["md_content_pruned"] = truncate_for_analysis(raw_md)
            doc["md_excerpt"] = truncate_for_classify(raw_md)
        return self

    def analyses_summary(self) -> str:
        """Generate analyses summary text for downstream prompts."""
        lines = []
        for doc_id, analysis in self.analyses.items():
            core = analysis.get("core_problem", "")
            score = analysis.get("quality_score", "N/A")
            lines.append(f"- {doc_id}: {core} (质量分: {score})")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize to dict for SSE events or DB storage."""
        return {
            "docs": self.docs,
            "classify": self.classify,
            "analyses": self.analyses,
            "review_dimensions": self.review_dimensions,
            "insights": self.insights,
            "report": self.report,
            "project_id": self.project_id,
            **self.extra,
        }


# ── Pi-inspired: StepEvent ──

@dataclass
class StepEvent:
    """Unified SSE event type. Inspired by Pi's event stream."""
    event_type: str  # pipeline_start | step_start | step_update | step_end | pipeline_end
    data: dict = field(default_factory=dict)


# Skill name → internal pipeline step name mapping
_SKILL_NAMES = {
    "classify": "prd-overview-classify",
    "classify_version_chain": "prd-overview-classify",  # second classify sub-step
    "per_analysis": "prd-per-analysis",
    "system_review": "system-review",
    "insights": "requirement-insights",
    "report": "report-generator",
}

# Review mode → ordered skill sequence
_MODE_STEPS = {
    "quick": ["classify", "per_analysis"],
    "review": ["classify", "per_analysis", "system_review", "report"],
    "pm": ["classify", "per_analysis", "system_review", "report"],
    "insight": ["classify", "per_analysis", "system_review", "insights", "report"],
    "full": ["classify", "per_analysis", "system_review", "insights", "report"],
    "draft": ["classify", "per_analysis", "system_review", "insights", "report"],
}

# System-review dimensions in execution order
_REVIEW_DIMENSIONS = [
    "business-value",
    "architecture",
    "competition",
    "product-strategy",
    "tech-evolution",
    "pm-assessment",
    "action-plan",
]

# Dimension name → prior dimension result variable name
_DIM_RESULT_VARS = {
    "business-value": None,
    "architecture": "business_value_result",
    "competition": ["business_value_result", "architecture_result"],
    "product-strategy": ["business_value_result", "architecture_result", "competition_result"],
    "tech-evolution": ["business_value_result", "architecture_result", "competition_result", "product_strategy_result"],
    "pm-assessment": None,  # uses prior_dimensions_summary instead
    "action-plan": [
        "business_value_result", "architecture_result", "competition_result",
        "product_strategy_result", "tech_evolution_result", "pm_assessment_result",
    ],
}

_EXPERT_REVIEW_RULE_KEYS = [
    "scope_realism",
    "boundary_completeness",
    "structured_entitlements",
    "user_facing_naming",
    "copy_consistency",
    "phased_tech_plan",
]

_EMPTY_EXPERT_SUMMARY_VALUES = {"", "-", "无", "暂无", "无意见", "暂无意见", "无额外意见", "暂无额外意见"}


def _validate_expert_review_block(data: dict) -> list[str]:
    errors: list[str] = []
    expert_review = data.get("expert_review")
    if not isinstance(expert_review, dict):
        return ["missing or invalid expert_review"]

    checks = expert_review.get("checks")
    if not isinstance(checks, list):
        errors.append("expert_review.checks is required")
        return errors

    seen_rule_keys = set()
    for check in checks:
        if not isinstance(check, dict):
            continue
        rule_key = check.get("rule_key")
        if isinstance(rule_key, str):
            seen_rule_keys.add(rule_key)

    missing_rule_keys = [key for key in _EXPERT_REVIEW_RULE_KEYS if key not in seen_rule_keys]
    if missing_rule_keys:
        errors.append(f"expert_review.checks missing rules: {', '.join(missing_rule_keys)}")

    return errors


def _fill_expert_review_summary(data: dict) -> None:
    expert_review = data.get("expert_review")
    if not isinstance(expert_review, dict):
        return

    summary = str(expert_review.get("summary") or "").strip()
    if summary and summary not in _EMPTY_EXPERT_SUMMARY_VALUES:
        return

    checks = expert_review.get("checks")
    if not isinstance(checks, list):
        return

    problem_names = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        status = str(check.get("status") or "").lower()
        if status in {"risk", "missing"}:
            problem_names.append(str(check.get("rule_name") or check.get("rule_key") or "未命名规则"))

    if problem_names:
        expert_review["summary"] = f"专家评审发现 {len(problem_names)} 项需关注：{'、'.join(problem_names)}。"
    else:
        expert_review["summary"] = "专家六项评审均通过，暂无额外修改意见。"


class SkillRunner:
    """Pi-inspired SkillRunner — deterministic pipeline with hooks, pruning, and events."""

    def __init__(
        self,
        model_cfg: dict,
        skills_dir: str | Path,
        context: dict | None = None,
        retry_config: RetryConfig | None = None,
        step_max_retries: int = 3,
        step_retry_delay: int = 5,
        event_sink: Callable[[StepEvent], None] | None = None,
    ):
        self.model_cfg = model_cfg
        self.skills_dir = Path(skills_dir).resolve()
        self.context = context or {}
        self.retry_config = retry_config or RetryConfig()
        self.step_max_retries = step_max_retries
        self.step_retry_delay = step_retry_delay
        self.event_sink = event_sink

        self.prompt_loader = SkillPromptLoader(self.skills_dir)
        self.schema_loader = SkillSchemaLoader(self.skills_dir)

        self.state = PipelineState()
        self.pipeline_state = self.state

    # ── Event emission ──

    def emit(self, event_type: str, data: dict | None = None) -> None:
        """Push a StepEvent to the SSE queue via event_sink callback."""
        if data is None:
            data = {}
        if self.event_sink:
            self.event_sink(StepEvent(event_type=event_type, data=data))

    # ── Pi-inspired hooks ──

    async def before_step(self, step_name: str, inputs: dict) -> dict:
        """Hook before step execution. Prune context, inject ReviewContext."""
        # 1. Prune md_content if present
        if "md_content" in inputs:
            inputs["md_content"] = strip_base64_images(inputs["md_content"])
        if "doc_titles_and_excerpts" in inputs:
            inputs["doc_titles_and_excerpts"] = strip_base64_images(inputs["doc_titles_and_excerpts"])
        return inputs

    async def after_step(self, step_name: str, result: SkillStepResult) -> SkillStepResult:
        """Hook after step execution. Schema validation, repair, logging."""
        # Schema validation is already done inside run_skill
        # This hook is for additional post-processing
        if step_name == "per_analysis" and not result.is_error:
            errors = _validate_expert_review_block(result.data)
            if errors:
                result.status = "error"
                result.data["error"] = "; ".join(errors)
                result.diagnostics.extend(errors)
                result.schema_valid = False
            else:
                _fill_expert_review_summary(result.data)
        return result

    # ── Core API ──

    async def run_skill(self, skill_name: str, inputs: dict) -> SkillStepResult:
        """Run a single skill step: before_step → prompt → LLM → validate → after_step → return SkillStepResult."""
        # Apply before_step hook
        inputs = await self.before_step(skill_name, inputs)

        skill_dir = _SKILL_NAMES.get(skill_name, skill_name)
        prompt_name = self._prompt_name_for(skill_name)

        template = self.prompt_loader.load(skill_dir, prompt_name)
        if not template:
            logger.error("No prompt template for skill %s", skill_name)
            return SkillStepResult(status="error", data={"error": f"missing prompt for {skill_name}"})

        # Build context injection string
        context_injection = self._build_context_injection()

        # Fill variables into template
        user_prompt = self.prompt_loader.fill(template, inputs)

        # System prompt: load skill-specific system context if available
        system_prompt = self._load_system_prompt(skill_dir)
        if context_injection:
            system_prompt = system_prompt + "\n" + context_injection

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Determine per-skill LLM parameters
        max_tokens, temperature = self._llm_params_for(skill_name)

        raw_result = await structured_chat(
            messages,
            api_base=self.model_cfg["api_base"],
            api_key=self.model_cfg["api_key"],
            llm_model=self.model_cfg["llm_model"],
            max_tokens=max_tokens,
            temperature=temperature,
            config=self.retry_config,
        )

        # Validate and repair against output schema
        diagnostics = []
        schema_valid = None
        schema = self.schema_loader.load(skill_dir)
        if schema:
            errors = self.schema_loader.validate(raw_result, schema)
            if errors:
                logger.warning("Schema validation errors for %s: %s", skill_name, errors)
                diagnostics.extend(errors)
                raw_result = self.schema_loader.repair(raw_result, schema)
                schema_valid = raw_result.get("_schema_valid", False)
            else:
                schema_valid = True
        else:
            raw_result["_schema_valid"] = None

        step_result = SkillStepResult(
            status="success" if not raw_result.get("error") else "error",
            data=raw_result,
            diagnostics=diagnostics,
            schema_valid=schema_valid,
        )

        # Apply after_step hook
        step_result = await self.after_step(skill_name, step_result)
        return step_result

    async def run_pipeline(self, mode: str, initial_inputs: dict) -> PipelineState:
        """Run a full pipeline for the given review mode.

        Args:
            mode: One of quick/review/pm/insight/full/draft.
            initial_inputs: Starting inputs including doc data, project info, etc.

        Returns:
            Final pipeline_state dict with all intermediate outputs.
        """
        steps = _MODE_STEPS.get(mode, _MODE_STEPS["review"])
        self.state = PipelineState()
        self.pipeline_state = self.state
        for key, value in initial_inputs.items():
            self.state[key] = value

        for step_idx, skill_name in enumerate(steps):
            logger.info("Pipeline step %d/%d: %s (mode=%s)", step_idx + 1, len(steps), skill_name, mode)

            # Special handling for multi-call steps
            if skill_name == "per_analysis":
                await self._run_per_analysis()
            elif skill_name == "system_review":
                await self._run_system_review()
            elif skill_name == "insights":
                await self._run_insights()
            else:
                inputs = self.build_step_inputs(skill_name, self.pipeline_state)
                result = await self.run_skill_with_retry(skill_name, inputs)
                self._store_result(skill_name, result)

        return self.pipeline_state

    # ── Multi-call step handlers ──

    async def _run_per_analysis(self, only_doc_ids: list[str] | None = None, should_cancel=None) -> bool:
        """Run per-analysis for each document in pipeline_state[docs].

        If only_doc_ids is provided, only analyze those documents;
        docs not in the list are skipped (assumed already cached).
        Returns True when cancelled between document calls.
        """
        docs = self.pipeline_state.get("docs", [])
        existing_analyses = self.pipeline_state.get("analyses", {})
        analyses = dict(existing_analyses)  # preserve already cached entries

        target_docs = docs if only_doc_ids is None else [d for d in docs if str(d.get("doc_id", d.get("id", ""))) in only_doc_ids]

        for doc in target_docs:
            if await _cancel_requested(should_cancel):
                self.pipeline_state["analyses"] = analyses
                return True
            doc_id = doc.get("doc_id", doc.get("id", ""))
            md_content = doc.get("md_content", "")
            category = doc.get("category", "未分类")
            version = doc.get("version", "")

            inputs = {
                "md_content": md_content,
                "category": category,
                "version": version,
                "image_descriptions": "",  # Phase 2: not yet implemented
            }

            result = await self.run_skill_with_retry("per_analysis", inputs)
            result_data = result.data if hasattr(result, 'data') else result
            result_data["doc_id"] = doc_id
            analyses[doc_id] = result_data

        self.pipeline_state["analyses"] = analyses
        return False

    async def _run_system_review(self, should_cancel=None) -> bool:
        """Run system-review as sequential dimension calls.

        Always runs all 7 dimensions. Results are cached and reused —
        mode only determines which tab to display and what report highlights.
        Returns True when cancelled between dimension calls.
        """
        dimensions = _REVIEW_DIMENSIONS

        dimension_results = {}

        for dim_idx, dim_name in enumerate(dimensions):
            if await _cancel_requested(should_cancel):
                self.pipeline_state["review_dimensions"] = dimension_results
                return True
            logger.info("System-review dimension %d/%d: %s", dim_idx + 1, len(dimensions), dim_name)

            inputs = self._build_dimension_inputs(dim_name, dimension_results)
            # The "skill" is still system_review, but we specify the dimension prompt
            result = await self._run_dimension_with_retry(dim_name, inputs)
            dimension_results[dim_name] = result

        self.pipeline_state["review_dimensions"] = dimension_results
        return False

    async def _run_insights(self) -> None:
        """Run requirement-insights as 3 sequential sub-steps."""
        sub_steps = [
            ("evolution-match", "evolution"),
            ("feature-extraction", "features"),
            ("gap-assessment", "gap"),
        ]
        insight_results = {}

        for prompt_name, key in sub_steps:
            inputs = self._build_insight_inputs(prompt_name, insight_results)
            result = await self._run_insight_substep_with_retry(prompt_name, inputs)
            insight_results[key] = result

        self.pipeline_state["insights"] = insight_results

    # ── Input builders ──

    def build_step_inputs(self, skill_name: str, state: dict) -> dict:
        """Build the inputs dict for a skill from current pipeline state."""
        if skill_name == "classify":
            return self._build_classify_inputs(state)
        elif skill_name == "report":
            return self._build_report_inputs(state)
        return {}

    def _build_classify_inputs(self, state: dict) -> dict:
        """Build inputs for the classify skill."""
        docs = state.get("docs", [])
        excerpts = []
        for doc in docs:
            title = doc.get("filename", doc.get("title", ""))
            content = doc.get("md_content", "")[:2000]
            excerpts.append(f"文档: {title}\n内容摘要:\n{content[:1000]}")

        # Load default categories from skill template
        categories_path = self.skills_dir / "prd-overview-classify" / "templates" / "default-categories.json"
        category_keywords = ""
        if categories_path.exists():
            try:
                cat_data = json.loads(categories_path.read_text(encoding="utf-8"))
                category_keywords = json.dumps(cat_data, ensure_ascii=False)
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to load default-categories.json")

        # Override with ReviewContext category_overrides if present
        if self.context.get("category_overrides"):
            category_keywords = json.dumps(self.context["category_overrides"], ensure_ascii=False)

        return {
            "doc_titles_and_excerpts": "\n\n---\n\n".join(excerpts),
            "category_keywords": category_keywords,
        }

    def _build_dimension_inputs(self, dim_name: str, prior_results: dict) -> dict:
        """Build inputs for a system-review dimension prompt."""
        state = self.pipeline_state
        inputs = {}

        # Common inputs: categories, version_chains, doc_analyses_summary, doc_count
        classify_output = state.get("classify", {})
        inputs["categories"] = json.dumps(classify_output.get("categories", []), ensure_ascii=False)
        inputs["version_chains"] = json.dumps(classify_output.get("version_chains", []), ensure_ascii=False)

        analyses = state.get("analyses", {})
        summaries = []
        for doc_id, analysis in analyses.items():
            core = analysis.get("core_problem", "")
            score = analysis.get("quality_score", "N/A")
            summaries.append(f"- {doc_id}: {core} (质量分: {score})")
        inputs["doc_analyses_summary"] = "\n".join(summaries)
        inputs["doc_count"] = str(len(analyses))

        # Prior dimension results
        prior_vars = _DIM_RESULT_VARS.get(dim_name)
        if isinstance(prior_vars, list):
            for var in prior_vars:
                # Map variable name to dimension name: business_value_result → business-value
                dim_key = var.replace("_result", "").replace("_", "-")
                inputs[var] = json.dumps(prior_results.get(dim_key, {}), ensure_ascii=False)
        elif prior_vars is None and dim_name == "pm-assessment":
            # pm-assessment uses prior_dimensions_summary + original_docs
            prior_summary = []
            for prev_dim, prev_result in prior_results.items():
                if prev_dim != "pm-assessment":
                    prior_summary.append(f"维度 {prev_dim}: {json.dumps(prev_result, ensure_ascii=False)[:500]}")
            inputs["prior_dimensions_summary"] = "\n".join(prior_summary)

            # Original document content — essential for PM writing/thinking evaluation
            docs = state.get("docs", [])
            doc_parts = []
            for doc in docs:
                content = doc.get("md_content_pruned", "") or doc.get("md_content", "")
                if len(content) > 3000:
                    content = content[:3000] + "\n... (截断)"
                doc_parts.append(f"### {doc.get('filename', '')}\n{content}")
            inputs["original_docs"] = "\n\n---\n\n".join(doc_parts)

            # ReviewContext overrides for PM assessment
            inputs["scoring_overrides"] = json.dumps(
                self.context.get("scoring_overrides", {}), ensure_ascii=False
            )
            inputs["writing_standard"] = json.dumps(
                self.context.get("specifications", self.context.get("required_sections", [])),
                ensure_ascii=False,
            )

        # Competition dimension gets industry context
        if dim_name == "competition":
            industry_path = self.skills_dir / "system-review" / "templates" / "industry-smart-home.json"
            if industry_path.exists():
                try:
                    inputs["industry_context"] = industry_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            inputs["competition_references"] = ""

        # Architecture gets dependencies from classify output
        if dim_name == "architecture":
            inputs["dependencies"] = json.dumps(
                classify_output.get("dependencies", []), ensure_ascii=False
            )

        return inputs

    def _build_insight_inputs(self, prompt_name: str, prior_results: dict) -> dict:
        """Build inputs for an insights sub-step."""
        state = self.pipeline_state

        if prompt_name == "evolution-match":
            # Gather boundary issues from analyses
            current_issues = []
            analyses = state.get("analyses", {})
            for doc_id, analysis in analyses.items():
                for issue in analysis.get("boundary_issues", []):
                    current_issues.append({
                        "doc_id": doc_id,
                        "issue": issue.get("issue", ""),
                        "severity": issue.get("severity", "medium"),
                    })
            inputs = {
                "current_issues": json.dumps(current_issues, ensure_ascii=False),
                "subsequent_docs": json.dumps(
                    state.get("classify", {}).get("version_chains", []),
                    ensure_ascii=False,
                ),
            }

        elif prompt_name == "feature-extraction":
            analyses = state.get("analyses", {})
            boundary_data = []
            for doc_id, analysis in analyses.items():
                boundary_data.append({
                    "doc_id": doc_id,
                    "boundary_in": analysis.get("boundary_in", []),
                    "boundary_out": analysis.get("boundary_out", []),
                })
            inputs = {
                "boundary_data": json.dumps(boundary_data, ensure_ascii=False),
                "categories": json.dumps(
                    state.get("classify", {}).get("categories", []), ensure_ascii=False
                ),
                "version_chains": json.dumps(
                    state.get("classify", {}).get("version_chains", []), ensure_ascii=False
                ),
            }

        elif prompt_name == "gap-assessment":
            features_result = prior_results.get("features", {})
            inputs = {
                "coverage_matrix": json.dumps(
                    features_result.get("coverage_matrix", []), ensure_ascii=False
                ),
                "gaps": json.dumps(features_result.get("gaps", []), ensure_ascii=False),
                "overlaps": json.dumps(features_result.get("overlaps", []), ensure_ascii=False),
                "categories": json.dumps(
                    state.get("classify", {}).get("categories", []), ensure_ascii=False
                ),
            }

        else:
            inputs = {}

        return inputs

    def _build_report_inputs(self, state: dict) -> dict:
        """Build inputs for the report skill."""
        # Assemble raw report content from pipeline state
        parts = []

        classify = state.get("classify", {})
        if classify:
            parts.append(f"## 文档分类\n{json.dumps(classify.get('categories', []), ensure_ascii=False)}")

        analyses = state.get("analyses", {})
        if analyses:
            parts.append("## 逐篇分析")
            for doc_id, analysis in analyses.items():
                parts.append(f"### {doc_id}\n{json.dumps(analysis, ensure_ascii=False)[:3000]}")

        dimensions = state.get("review_dimensions", {})
        if dimensions:
            parts.append("## 体系Review")
            for dim_name, dim_result in dimensions.items():
                parts.append(f"### {dim_name}\n{json.dumps(dim_result, ensure_ascii=False)[:3000]}")

        insights = state.get("insights", {})
        if insights:
            parts.append(f"## 需求洞察\n{json.dumps(insights, ensure_ascii=False)[:5000]}")

        return {"report_content": "\n\n---\n\n".join(parts)}

    # ── Retry wrapper ──

    async def run_skill_with_retry(self, skill_name: str, inputs: dict) -> SkillStepResult:
        """Run a skill with step-level retry logic."""
        import asyncio

        for attempt in range(self.step_max_retries):
            try:
                result = await self.run_skill(skill_name, inputs)
                if not result.is_error:
                    return result
                logger.warning("Skill %s returned error on attempt %d: %s", skill_name, attempt + 1, result.data.get("error", "unknown"))
            except Exception as e:
                logger.warning("Skill %s exception on attempt %d: %s", skill_name, attempt + 1, e)

            if attempt < self.step_max_retries - 1:
                await asyncio.sleep(self.step_retry_delay)

        logger.error("Skill %s failed after %d retries", skill_name, self.step_max_retries)
        return SkillStepResult(status="error", data={"error": f"skill {skill_name} failed after {self.step_max_retries} retries"})

    async def _run_dimension_with_retry(self, dim_name: str, inputs: dict) -> dict:
        """Run a system-review dimension with retry."""
        import asyncio

        skill_dir = "system-review"
        system_prompt = self._load_system_prompt(skill_dir)
        context_injection = self._build_context_injection()
        if context_injection:
            system_prompt += "\n" + context_injection

        # Load dimension-specific prompt
        template = self.prompt_loader.load(skill_dir, dim_name)
        if not template:
            logger.error("No prompt for dimension %s", dim_name)
            return {"error": f"missing prompt for dimension {dim_name}"}

        user_prompt = self.prompt_loader.fill(template, inputs)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(self.step_max_retries):
            try:
                result = await structured_chat(
                    messages,
                    api_base=self.model_cfg["api_base"],
                    api_key=self.model_cfg["api_key"],
                    llm_model=self.model_cfg["llm_model"],
                    max_tokens=self.model_cfg["max_tokens"],
                    temperature=0.3,
                    config=self.retry_config,
                )
                result = normalize_dimension_result(dim_name, result)

                schema = self.schema_loader.load(skill_dir)
                if schema:
                    errors = self.schema_loader.validate(result, schema)
                    if errors:
                        logger.warning("Schema errors for dim %s: %s", dim_name, errors)
                        result = self.schema_loader.repair(result, schema)

                if dim_name == "pm-assessment":
                    pm_payload = extract_pm_assessment_payload(result)
                    if not pm_payload:
                        raise ValueError("pm-assessment returned no parseable PM scores")
                    result = {**result, **pm_payload}

                return result

            except Exception as e:
                logger.warning("Dimension %s attempt %d failed: %s", dim_name, attempt + 1, e)
                if attempt < self.step_max_retries - 1:
                    await asyncio.sleep(self.step_retry_delay)

        return {"error": f"dimension {dim_name} failed after {self.step_max_retries} retries"}

    async def _run_insight_substep_with_retry(self, prompt_name: str, inputs: dict) -> dict:
        """Run an insights sub-step with retry."""
        import asyncio

        skill_dir = "requirement-insights"
        system_prompt = self._load_system_prompt(skill_dir)
        context_injection = self._build_context_injection()
        if context_injection:
            system_prompt += "\n" + context_injection

        template = self.prompt_loader.load(skill_dir, prompt_name)
        if not template:
            logger.error("No prompt for insight sub-step %s", prompt_name)
            return {"error": f"missing prompt for {prompt_name}"}

        user_prompt = self.prompt_loader.fill(template, inputs)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(self.step_max_retries):
            try:
                result = await structured_chat(
                    messages,
                    api_base=self.model_cfg["api_base"],
                    api_key=self.model_cfg["api_key"],
                    llm_model=self.model_cfg["llm_model"],
                    max_tokens=self.model_cfg["max_tokens"],
                    temperature=0.3,
                    config=self.retry_config,
                )

                schema = self.schema_loader.load(skill_dir)
                if schema:
                    errors = self.schema_loader.validate(result, schema)
                    if errors:
                        logger.warning("Schema errors for insight %s: %s", prompt_name, errors)
                        result = self.schema_loader.repair(result, schema)

                return result

            except Exception as e:
                logger.warning("Insight %s attempt %d failed: %s", prompt_name, attempt + 1, e)
                if attempt < self.step_max_retries - 1:
                    await asyncio.sleep(self.step_retry_delay)

        return {"error": f"insight {prompt_name} failed after {self.step_max_retries} retries"}

    # ── Helpers ──

    def _prompt_name_for(self, skill_name: str) -> str:
        """Return the primary prompt file name for a skill."""
        mapping = {
            "classify": "classify",
            "classify_version_chain": "version-chain",
            "per_analysis": "per-doc-analysis",
            "report": "report-polish",
        }
        return mapping.get(skill_name, skill_name)

    def _load_system_prompt(self, skill_dir: str) -> str:
        """Load the system-context.md as system prompt if it exists."""
        system_prompt = self.prompt_loader.load(skill_dir, "system-context")
        return system_prompt or "你是一位需求文档审查专家。严格按JSON格式输出。"

    def _build_context_injection(self) -> str:
        return build_context_injection(self.context)

    def _llm_params_for(self, skill_name: str) -> tuple[int, float]:
        """Return (max_tokens, temperature) for a skill step."""
        if skill_name == "classify":
            return (min(self.model_cfg.get("max_tokens", 4096), 2048), 0.1)
        return (self.model_cfg.get("max_tokens", 4096), 0.3)

    def _store_result(self, skill_name: str, result) -> None:
        """Store a skill's result data in pipeline_state.

        Accepts both SkillStepResult (extracts .data) and plain dict.
        """
        data = result.data if isinstance(result, SkillStepResult) else result
        self.pipeline_state[skill_name] = data
