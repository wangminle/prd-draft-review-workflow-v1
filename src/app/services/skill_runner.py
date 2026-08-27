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
            # Only unwrap tight wrappers where the payload key is the sole
            # meaningful top-level key. tech-evolution 的合法扁平输出本身就带
            # 顶层 tech_evolution 子对象（与兄弟字段并存），不能被剥掉（Issue #3）。
            meaningful = [k for k in result if not k.startswith("_")]
            if len(meaningful) == 1 and meaningful[0] == key:
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

# Steps that cannot be skipped — if the underlying Skill is inactive,
# the pipeline must refuse to start rather than silently skip.
_REQUIRED_STEPS = {
    "classify", "per_analysis", "system_review", "report",
}

# Steps that may be skipped when the underlying Skill is inactive —
# the pipeline runs in degraded mode and downstream reports must mark
# the missing dimension explicitly.
_OPTIONAL_STEPS = {
    "insights",
}


class SkillInactiveError(RuntimeError):
    """Raised when a required Skill is inactive and cannot be skipped.

    Distinguishes "degraded mode" (optional Skill inactive, pipeline can
    continue with warnings) from "blocked mode" (required Skill inactive,
    pipeline cannot start).
    """

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

# 与 skills/prd-per-analysis/templates/output-schema.json 中 status 枚举保持一致。
_EXPERT_REVIEW_VALID_STATUSES = {"pass", "risk", "missing"}


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
    duplicate_rule_keys: list[str] = []
    invalid_statuses: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        rule_key = check.get("rule_key")
        if isinstance(rule_key, str):
            if rule_key in seen_rule_keys and rule_key not in duplicate_rule_keys:
                duplicate_rule_keys.append(rule_key)
            seen_rule_keys.add(rule_key)
        status = str(check.get("status") or "").strip().lower()
        if status not in _EXPERT_REVIEW_VALID_STATUSES:
            label = rule_key if isinstance(rule_key, str) else "unknown"
            invalid_statuses.append(f"{label}={check.get('status')!r}")

    if duplicate_rule_keys:
        errors.append(f"expert_review.checks duplicate rules: {', '.join(duplicate_rule_keys)}")
    if invalid_statuses:
        errors.append(f"expert_review.checks invalid status: {', '.join(invalid_statuses)}")

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
        workspace_id: int | None = None,
        user_id: int | None = None,
    ):
        self.model_cfg = model_cfg
        self.skills_dir = Path(skills_dir).resolve()
        self.context = context or {}
        self.retry_config = retry_config or RetryConfig()
        self.step_max_retries = step_max_retries
        self.step_retry_delay = step_retry_delay
        self.event_sink = event_sink
        self.workspace_id = workspace_id
        self.user_id = user_id

        self.prompt_loader = SkillPromptLoader(self.skills_dir)
        self.schema_loader = SkillSchemaLoader(self.skills_dir)

        self.state = PipelineState()
        self.pipeline_state = self.state

    def _llm_attribution(self) -> dict:
        """审查主路径 LLM 调用归属，供配额聚合（mode=review）。"""
        return {
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "mode": "review",
        }

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
            extra_body=self.model_cfg.get("extra_body"),
            config=self.retry_config,
            **self._llm_attribution(),
        )

        # Validate and repair against output schema
        diagnostics = []
        schema_valid = None
        schema_critical = False
        schema = self.schema_loader.load(skill_dir, prompt_name)
        if schema:
            errors = self.schema_loader.validate(raw_result, schema)
            if errors:
                logger.warning("Schema validation errors for %s: %s", skill_name, errors)
                diagnostics.extend(errors)
                raw_result = self.schema_loader.repair(raw_result, schema)
                schema_valid = raw_result.get("_schema_valid", False)
                schema_critical = bool(raw_result.get("_schema_critical", False))
                # P1-4.2: Surface non-critical repairs in diagnostics so they
                # are visible to callers instead of being silently applied.
                repair_notes = raw_result.pop("_schema_repair_notes", [])
                if repair_notes:
                    diagnostics.extend(repair_notes)
                if schema_critical:
                    # Critical business field was missing/invalid — treat as error
                    # so downstream steps cannot silently consume bogus data.
                    logger.error(
                        "Schema critical failure for %s: business field invalid/missing",
                        skill_name,
                    )
            else:
                schema_valid = True
        else:
            raw_result["_schema_valid"] = None

        # When a critical business field was repaired, mark step as error so
        # callers can retry or fail gracefully instead of persisting bogus data.
        step_status = "success"
        if raw_result.get("error"):
            step_status = "error"
        elif schema_critical:
            step_status = "error"
            raw_result["error"] = (
                f"schema critical validation failure for {skill_name}: "
                f"business field missing or out of range"
            )

        step_result = SkillStepResult(
            status=step_status,
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

        Raises:
            SkillInactiveError: if a required Skill is marked inactive by the
                caller-provided `inactive_skills` set in initial_inputs.
        """
        steps = _MODE_STEPS.get(mode, _MODE_STEPS["review"])
        self.state = PipelineState()
        self.pipeline_state = self.state
        for key, value in initial_inputs.items():
            self.state[key] = value

        # Preflight: enforce SkillConfig.status gate. The caller passes the
        # set of inactive skill_ids (from SkillConfigRepository.list_all) via
        # initial_inputs["inactive_skills"]. Required Skills inactive → raise.
        # Optional Skills inactive → mark degraded and skip.
        inactive_skills = set(initial_inputs.get("inactive_skills", []) or [])
        if inactive_skills:
            self._preflight_skill_gate(steps, inactive_skills)

        for step_idx, skill_name in enumerate(steps):
            logger.info("Pipeline step %d/%d: %s (mode=%s)", step_idx + 1, len(steps), skill_name, mode)

            # Skip optional steps whose Skill is inactive (degraded mode)
            skill_dir = _SKILL_NAMES.get(skill_name, skill_name)
            if skill_dir in inactive_skills and skill_name in _OPTIONAL_STEPS:
                logger.warning("Skill %s inactive — running in degraded mode (skipping %s)",
                               skill_dir, skill_name)
                self.state.setdefault("degraded_steps", []).append(skill_name)
                continue

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

    def _preflight_skill_gate(
        self, steps: list[str], inactive_skills: set[str]
    ) -> None:
        """Refuse to start the pipeline if any required Skill is inactive.

        Optional Skills inactive are allowed (degraded mode handled in run_pipeline).
        """
        blocked: list[str] = []
        for step_name in steps:
            if step_name not in _REQUIRED_STEPS:
                continue
            skill_dir = _SKILL_NAMES.get(step_name, step_name)
            if skill_dir in inactive_skills:
                blocked.append(skill_dir)
        if blocked:
            raise SkillInactiveError(
                f"必需 Skill 处于 inactive 状态，拒绝启动管线：{', '.join(blocked)}。"
                f"请在管理后台重新启用后再发起审查任务。"
            )

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
                "doc_id": str(doc_id),
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

        Tracks per-dimension success/failure in pipeline_state["review_dimensions_meta"]:
          - dimensions_executed: list of dim names that produced valid (non-error) output
          - dimensions_failed: list of dim names whose output was an error object
          - status: "success" | "partial" | "all_failed" | "cancelled"

        If all dimensions fail, status is "all_failed" — callers MUST treat the
        review step as failed and must not cache or persist the error objects
        as a completed review.
        """
        dimensions = _REVIEW_DIMENSIONS

        dimension_results: dict[str, dict] = {}
        executed: list[str] = []
        failed: list[str] = []

        for dim_idx, dim_name in enumerate(dimensions):
            if await _cancel_requested(should_cancel):
                self.pipeline_state["review_dimensions"] = dimension_results
                self._record_review_dimensions_meta(executed, failed, status="cancelled")
                return True
            logger.info("System-review dimension %d/%d: %s", dim_idx + 1, len(dimensions), dim_name)

            inputs = self._build_dimension_inputs(dim_name, dimension_results)
            # The "skill" is still system_review, but we specify the dimension prompt
            result = await self._run_dimension_with_retry(dim_name, inputs)
            dimension_results[dim_name] = result

            if isinstance(result, dict) and result.get("error"):
                failed.append(dim_name)
                logger.warning("System-review dimension %s failed: %s", dim_name, result.get("error"))
            else:
                executed.append(dim_name)

        self.pipeline_state["review_dimensions"] = dimension_results

        if not executed:
            status = "all_failed"
        elif failed:
            status = "partial"
        else:
            status = "success"
        self._record_review_dimensions_meta(executed, failed, status=status)

        return False

    def _record_review_dimensions_meta(
        self, executed: list[str], failed: list[str], status: str
    ) -> None:
        """Record structured execution summary for the seven-dimension review."""
        self.pipeline_state["review_dimensions_meta"] = {
            "dimensions_executed": executed,
            "dimensions_failed": failed,
            "total": len(_REVIEW_DIMENSIONS),
            "success_count": len(executed),
            "failed_count": len(failed),
            "status": status,
        }

    async def _run_insights(self) -> None:
        """Run requirement-insights as 3 sequential sub-steps.

        After completion, pipeline_state["insights_meta"] carries:
          - issue_conservation: total_issues == resolved + partial + unresolved
          - baseline_warning: non-empty when no independent target baseline
            was provided (so callers must not claim absolute gap identification)
          - sub_step_status: per sub-step "success" | "error"
        """
        sub_steps = [
            ("evolution-match", "evolution"),
            ("feature-extraction", "features"),
            ("gap-assessment", "gap"),
        ]
        insight_results: dict[str, dict] = {}
        sub_step_status: dict[str, str] = {}
        sub_step_inputs: dict[str, dict] = {}

        for prompt_name, key in sub_steps:
            inputs = self._build_insight_inputs(prompt_name, insight_results)
            sub_step_inputs[prompt_name] = inputs
            result = await self._run_insight_substep_with_retry(prompt_name, inputs)
            insight_results[key] = result
            sub_step_status[prompt_name] = (
                "error" if (isinstance(result, dict) and result.get("error")) else "success"
            )

        # Issue conservation: ensure every input issue is represented in matches.
        # If the model dropped issues, the LLM-side matches list will be shorter
        # than the input current_issues list. We backfill unresolved entries here
        # so downstream stats cannot silently lose problems.
        evolution_result = insight_results.get("evolution", {}) or {}
        matches = evolution_result.get("matches", []) if isinstance(evolution_result, dict) else []
        if isinstance(matches, list):
            backfilled = self._backfill_missing_issues(
                matches, sub_step_inputs.get("evolution-match", {})
            )
            if backfilled:
                insight_results["evolution"]["matches"] = backfilled["matches"]
                insight_results["evolution"]["_conservation_note"] = backfilled["note"]

        # Carry baseline_warning from feature-extraction output into gap-assessment
        # inputs and surface in insights_meta so reports can be transparent.
        features_result = insight_results.get("features", {}) or {}
        baseline_warning = features_result.get("baseline_warning", "") if isinstance(features_result, dict) else ""

        # Issue conservation stats
        conservation = self._compute_issue_conservation(
            insight_results.get("evolution", {}) or {}
        )

        self.pipeline_state["insights"] = insight_results
        self.pipeline_state["insights_meta"] = {
            "sub_step_status": sub_step_status,
            "baseline_warning": baseline_warning,
            "issue_conservation": conservation,
        }

    def _backfill_missing_issues(
        self, matches: list[dict], last_inputs: dict
    ) -> dict | None:
        """Ensure every input issue appears in matches.

        If the model returned fewer matches than input issues (or omitted
        some issue_ids), add unresolved entries with confidence=low so
        downstream stats cannot silently drop problems.
        """
        current_issues_raw = last_inputs.get("current_issues", "[]")
        try:
            current_issues = json.loads(current_issues_raw) if isinstance(current_issues_raw, str) else current_issues_raw
        except json.JSONDecodeError:
            current_issues = []
        if not isinstance(current_issues, list) or not current_issues:
            return None

        seen_ids = {
            m.get("issue_id") for m in matches if isinstance(m, dict) and m.get("issue_id")
        }
        backfilled_count = 0
        for issue in current_issues:
            if not isinstance(issue, dict):
                continue
            issue_id = issue.get("issue_id")
            if issue_id and issue_id not in seen_ids:
                matches.append({
                    "issue_id": issue_id,
                    "issue": issue.get("issue", ""),
                    "resolved_in": None,
                    "resolved_version": None,
                    "status": "unresolved",
                    "evidence": None,
                    "confidence": "low",
                    "note": "模型漏返回，已由代码回填为 unresolved",
                })
                backfilled_count += 1
        if backfilled_count == 0:
            return None
        return {
            "matches": matches,
            "note": f"代码回填 {backfilled_count} 个被模型漏返回的问题为 unresolved",
        }

    def _compute_issue_conservation(self, evolution_result: dict) -> dict:
        """Verify total_issues == resolved + partial + unresolved.

        Matches with missing/unknown status default to "unresolved" so the
        invariant still holds (and surfaces data-quality issues via the
        unresolved count rather than silently dropping the issue).
        """
        matches = evolution_result.get("matches", []) if isinstance(evolution_result, dict) else []
        if not isinstance(matches, list):
            return {"valid": False, "reason": "matches is not a list"}
        resolved = 0
        partial = 0
        unresolved = 0
        for m in matches:
            if not isinstance(m, dict):
                unresolved += 1
                continue
            status = m.get("status", "unresolved")
            if status == "resolved":
                resolved += 1
            elif status == "partial":
                partial += 1
            else:
                unresolved += 1
        total = len(matches)
        return {
            "valid": total == resolved + partial + unresolved,
            "total_issues": total,
            "resolved": resolved,
            "partial": partial,
            "unresolved": unresolved,
        }

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
            # 使用 DB doc_id（不可变主键）作为唯一标识，文件名仅用于展示。
            # 这与 classify.md prompt 示例中的 [doc_id] 格式一致，确保 LLM
            # 回填的 doc_id 可被路由精确匹配，避免重名文件误匹配。
            doc_id = doc.get("id", doc.get("doc_id", ""))
            title = doc.get("filename", doc.get("title", ""))
            content = doc.get("md_content", "")[:2000]
            excerpts.append(f"- [{doc_id}] {title}: {content[:1000]}")

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
        analyses = state.get("analyses", {})
        classify_output = state.get("classify", {})
        version_chains = classify_output.get("version_chains", [])
        categories = classify_output.get("categories", [])

        if prompt_name == "evolution-match":
            # Build current issues with stable issue_id, grouped by doc.
            # Each issue carries its doc_id so downstream can find the
            # subsequent versions in the same chain and inject their
            # structured analysis (core_problem / boundary_in / key_points).
            current_issues = []
            for doc_id, analysis in analyses.items():
                for idx, issue in enumerate(analysis.get("boundary_issues", [])):
                    issue_text = issue.get("issue", "") if isinstance(issue, dict) else str(issue)
                    if not issue_text:
                        continue
                    current_issues.append({
                        "issue_id": f"{doc_id}_issue_{idx:03d}",
                        "doc_id": str(doc_id),
                        "issue": issue_text,
                        "severity": issue.get("severity", "medium") if isinstance(issue, dict) else "medium",
                    })

            # Build a map: doc_id → list of subsequent docs in the same chain
            # (with structured analysis content, not just metadata).
            subsequent_docs_map = self._build_subsequent_docs_map(version_chains, analyses)

            # For each issue, attach the structured content of its subsequent docs
            for issue_entry in current_issues:
                issue_entry["subsequent_docs"] = subsequent_docs_map.get(
                    issue_entry["doc_id"], []
                )

            inputs = {
                "current_issues": json.dumps(current_issues, ensure_ascii=False),
                "subsequent_docs": json.dumps(subsequent_docs_map, ensure_ascii=False),
            }

        elif prompt_name == "feature-extraction":
            boundary_data = []
            for doc_id, analysis in analyses.items():
                boundary_data.append({
                    "doc_id": str(doc_id),
                    "boundary_in": analysis.get("boundary_in", []),
                    "boundary_out": analysis.get("boundary_out", []),
                })
            # Optional target capability baseline from ReviewContext —
            # without an independent baseline, only "coverage analysis"
            # (not "absolute gap identification") is meaningful.
            target_baseline = self.context.get("target_capability_baseline", [])
            inputs = {
                "boundary_data": json.dumps(boundary_data, ensure_ascii=False),
                "categories": json.dumps(categories, ensure_ascii=False),
                "version_chains": json.dumps(version_chains, ensure_ascii=False),
                "target_baseline": json.dumps(target_baseline, ensure_ascii=False),
            }

        elif prompt_name == "gap-assessment":
            features_result = prior_results.get("features", {}) or {}
            feature_dimensions = features_result.get("feature_dimensions", [])
            baseline_warning = features_result.get("baseline_warning", "")

            # Deterministically build coverage_matrix from feature_dimensions
            # + analyses. The model is NOT asked to simultaneously produce
            # dimensions and coverage conclusions — that dual task caused
            # gap-assessment to receive empty matrices.
            coverage_matrix = self._build_coverage_matrix(feature_dimensions, analyses)
            gaps = [entry for entry in coverage_matrix if entry["status"] == "gap"]
            overlaps = [entry for entry in coverage_matrix if entry["status"] == "overlap"]

            inputs = {
                "coverage_matrix": json.dumps(coverage_matrix, ensure_ascii=False),
                "gaps": json.dumps(gaps, ensure_ascii=False),
                "overlaps": json.dumps(overlaps, ensure_ascii=False),
                "categories": json.dumps(categories, ensure_ascii=False),
                "baseline_warning": baseline_warning,
            }

        else:
            inputs = {}

        return inputs

    def _build_subsequent_docs_map(
        self, version_chains: list[dict], analyses: dict
    ) -> dict[str, list[dict]]:
        """For each doc_id, return the structured analysis of all docs that
        come AFTER it in the same version chain.

        Includes core_problem / boundary_in / boundary_out / key_points /
        excerpt, so the LLM can actually cite evidence for resolved/partial
        status instead of guessing from metadata.
        """
        subsequent_map: dict[str, list[dict]] = {}
        if not version_chains:
            return subsequent_map

        for chain in version_chains:
            if not isinstance(chain, dict):
                continue
            versions = chain.get("versions", []) or []
            for i, v_info in enumerate(versions):
                doc_id = str(v_info.get("doc_id", ""))
                subsequent = []
                for later in versions[i + 1:]:
                    later_id = str(later.get("doc_id", ""))
                    analysis = analyses.get(later_id, {}) or {}
                    subsequent.append({
                        "doc_id": later_id,
                        "version": later.get("version", analysis.get("version", "")),
                        "title": later.get("title", analysis.get("title", "")),
                        "core_problem": analysis.get("core_problem", ""),
                        "boundary_in": analysis.get("boundary_in", []),
                        "boundary_out": analysis.get("boundary_out", []),
                        "key_points": analysis.get("key_points", {}),
                        "excerpt": (analysis.get("core_problem", "") or "")[:500],
                    })
                if subsequent:
                    subsequent_map[doc_id] = subsequent_map.get(doc_id, []) + subsequent
        return subsequent_map

    def _build_coverage_matrix(
        self, feature_dimensions: list, analyses: dict
    ) -> list[dict]:
        """Deterministically build a coverage matrix from feature dimensions
        and per-doc analyses.

        Rules:
        - Each feature with source_doc_ids becomes "covered" or "overlap"
          (overlap when >1 doc covers it).
        - Each feature with empty source_doc_ids becomes "gap".
        - When the LLM did not provide source_doc_ids, fall back to a
          case-insensitive substring match against boundary_in + core_problem
          (matches the standalone insights.py behavior).
        """
        matrix: list[dict] = []
        for idx, dim in enumerate(feature_dimensions):
            if isinstance(dim, str):
                name = dim
                feature_id = f"feat_{idx + 1:03d}"
                source_doc_ids: list[str] = []
            elif isinstance(dim, dict):
                name = dim.get("name", "")
                feature_id = dim.get("feature_id") or f"feat_{idx + 1:03d}"
                source_doc_ids = list(dim.get("source_doc_ids", []) or [])
            else:
                continue

            # If the model didn't return source_doc_ids, derive them.
            if not source_doc_ids and name:
                name_lower = name.lower()
                for doc_id, analysis in analyses.items():
                    boundary_in = analysis.get("boundary_in", []) or []
                    core_problem = analysis.get("core_problem", "") or ""
                    check_text = " ".join(boundary_in) + " " + core_problem
                    if name_lower in check_text.lower() or any(
                        name_lower in str(bi).lower() for bi in boundary_in
                    ):
                        source_doc_ids.append(str(doc_id))

            if not source_doc_ids:
                status = "gap"
            elif len(source_doc_ids) > 1:
                status = "overlap"
            else:
                status = "covered"

            matrix.append({
                "feature_id": feature_id,
                "feature": name,
                "covered_by": source_doc_ids,
                "status": status,
            })
        return matrix

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
                    extra_body=self.model_cfg.get("extra_body"),
                    config=self.retry_config,
                    **self._llm_attribution(),
                )
                result = normalize_dimension_result(dim_name, result)

                schema = self.schema_loader.load(skill_dir, dim_name)
                if schema:
                    errors = self.schema_loader.validate(result, schema)
                    if errors:
                        logger.warning("Schema errors for dim %s: %s", dim_name, errors)
                        result = self.schema_loader.repair(result, schema)
                        # P1-4.2: Surface non-critical repairs in result
                        _repair_notes = result.pop("_schema_repair_notes", [])
                        if _repair_notes:
                            result["_repair_notes"] = _repair_notes
                        # Check critical field failure - treat as error so
                        # downstream cannot silently consume bogus data.
                        if result.get("_schema_critical"):
                            raise ValueError(
                                f"dimension {dim_name} schema critical failure: "
                                f"business field missing or out of range"
                            )

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
                    extra_body=self.model_cfg.get("extra_body"),
                    config=self.retry_config,
                    **self._llm_attribution(),
                )

                schema = self.schema_loader.load(skill_dir, prompt_name)
                if schema:
                    errors = self.schema_loader.validate(result, schema)
                    if errors:
                        logger.warning("Schema errors for insight %s: %s", prompt_name, errors)
                        result = self.schema_loader.repair(result, schema)
                        # P1-4.2: Surface non-critical repairs in result
                        _repair_notes = result.pop("_schema_repair_notes", [])
                        if _repair_notes:
                            result["_repair_notes"] = _repair_notes
                        # Check critical field failure - treat as error so
                        # downstream cannot silently consume bogus data.
                        if result.get("_schema_critical"):
                            raise ValueError(
                                f"insight {prompt_name} schema critical failure: "
                                f"business field missing or out of range"
                            )

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
