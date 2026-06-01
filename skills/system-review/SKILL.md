---
name: system-review
description: "Systematic 7-dimension review of a batch of PRD documents with multiple output modes. Use when (1) conducting a full system-level review across business value, architecture, competition, product strategy, tech evolution, PM assessment, and action planning, (2) generating next-direction recommendations for a requirement set, (3) evaluating PM writing quality and product thinking from requirement documents, (4) drafting a new PRD based on historical analysis of related documents, (5) producing any of these outputs: full_report, next_directions, quality_assessment, prd_draft. Also use when a user mentions 'system review', '7-dimension review', 'PM assessment', 'requirement review report', 'quality evaluation', or 'PRD draft generation'."
license: MIT
compatibility: opencode
---

# System Review

Systematic 7-dimension review of a batch of PRD documents, producing different output types from the same foundational analysis.

The core insight: **all output types share the same 7-dimension analysis — only the final formatting and prompt layer differ**.

## 7-Dimension Review Framework

The dimensions execute in order because later dimensions depend on earlier ones:

| Order | Dimension | Core Question | Prompt File |
|-------|-----------|---------------|-------------|
| 1 | Business Value | What business problem does this set solve? Strategic value? | `business-value.md` |
| 2 | Architecture | Are the document classification, evolution stages, and dependencies reasonable? | `architecture.md` |
| 3 | Competition | Differentiation advantages and gaps vs competitors? | `competition.md` |
| 4 | Product Strategy | Is the product roadmap and prioritization reasonable? | `product-strategy.md` |
| 5 | Tech Evolution | Is the technical approach evolving reasonably? Any tech debt? | `tech-evolution.md` |
| 6 | PM Assessment | PM writing style and product thinking strengths and blind spots? | `pm-assessment.md` |
| 7 | Action Plan | What should be done in short/mid/long term? | `action-plan.md` |

**Dependency chain**: 1→2→3→4→5→6→7. Each dimension receives the output of all prior dimensions as context.

## Output Modes

```
                        ┌─ --output-type full_report ──→ Full 7-dimension review report (MD)
                        │
7-dimension analysis ───┼─ --output-type next_directions ──→ Next requirement direction recommendations (MD)
                        │
                        ├─ --output-type quality_assessment ──→ PM writing quality assessment (MD)
                        │
                        ├─ --output-type prd_draft ──→ New PRD draft based on historical analysis (MD)
                        │
                        └─ --output-type all ──→ All outputs
```

| Output Type | Reference Case | Description |
|-------------|---------------|-------------|
| `full_report` | 智能联动 960-line review | Complete 7-dimension report with action plan and milestones |
| `next_directions` | 服务预约 next-step suggestions | What requirements to write next |
| `quality_assessment` | 服务预约 PRD quality evaluation | PM writing and thinking assessment with scoring |
| `prd_draft` | 声纹管理 V3 PRD (621 lines) | New PRD draft generated from historical analysis |

**`--target-doc`**: When specified, generates an additional context report for a specific target document (historical evolution, related boundary issues, existing solutions). Useful when preparing to review a new PRD.

## Dual Engine Architecture

| Engine | Purpose | Default Model | When Used |
|--------|---------|---------------|-----------|
| `text_engine` | All 7 dimensions analysis | `claude-sonnet-4-20250514` | Always |
| `vision_engine` | Image understanding in original docs | `claude-sonnet-4-20250514` | When `--enable-vision` |

Override via environment variables:
- `TEXT_MODEL` / `VISION_MODEL` — override default models
- `ANTHROPIC_API_KEY` — required

## Quick Start

All commands below assume the working directory is the **skill root** (`skills/system-review/`).
Install dependencies first: `pip install -r requirements.txt`

### Full system review

```bash
python scripts/review.py <classify_json> <analysis_dir> <output_json> [options]

# Full 7-dimension review report
python scripts/review.py classify.json ./analysis/ result.json --output-type full_report

# Next directions only
python scripts/review.py classify.json ./analysis/ result.json --output-type next_directions

# PM quality assessment
python scripts/review.py classify.json ./analysis/ result.json --output-type quality_assessment

# Generate PRD draft for a specific document
python scripts/review.py classify.json ./analysis/ result.json --output-type prd_draft --target-doc doc123

# All output types
python scripts/review.py classify.json ./analysis/ result.json --output-type all

# With vision for original document images
python scripts/review.py classify.json ./analysis/ result.json --output-type full_report --enable-vision

# Specific dimensions only
python scripts/review.py classify.json ./analysis/ result.json --dimensions 1,6,7

# With industry context for competition dimension
python scripts/review.py classify.json ./analysis/ result.json --industry smart_home
```

### PM assessment only (standalone)

```bash
python scripts/pm_assess.py <classify_json> <analysis_dir> <output_json> [options]

# Basic PM assessment
python scripts/pm_assess.py classify.json ./analysis/ result.json

# With custom scoring rubric
python scripts/pm_assess.py classify.json ./analysis/ result.json --rubric templates/pm-scoring-rubric.json
```

## Input

### Required

1. **Classify result JSON** — output from `prd-overview-classify` (categories, version chains, dependencies, document paths)
2. **Analysis directory** — directory containing per-document analysis JSONs from `prd-per-analysis`

### Optional

- **Industry template** — via `--industry` flag (e.g., `smart_home`) for competition dimension context
- **Competition references** — via `--competition-refs` for user-provided competitor information
- **Scoring rubric** — via `--rubric` for PM assessment dimension override
- **Review context** — via `--review-context` for project-level specifications (scoring rubrics, domain rules, writing standards)

### Review Context Injection

The `--review-context` parameter accepts a JSON file with project-level specifications that override defaults:

```json
{
  "context_version": 3,
  "specifications": [
    {"type": "scoring_rubric", "content": "..."},
    {"type": "domain_rules", "content": "..."},
    {"type": "writing_standard", "content": "..."}
  ],
  "scoring_overrides": {
    "writing_dimensions": [
      {"name": "逻辑结构", "weight": 0.3},
      {"name": "技术深度", "weight": 0.25}
    ],
    "thinking_dimensions": [
      {"name": "迭代思维", "weight": 0.3},
      {"name": "体验思维", "weight": 0.25}
    ]
  }
}
```

## Output Format

The output JSON structure varies by `--output-type`:

```json
{
  "project_name": "智能联动",
  "output_type": "full_report",
  "dimensions": {
    "business_value": { "...": "..." },
    "architecture": { "...": "..." },
    "competition": { "...": "..." },
    "product_strategy": { "...": "..." },
    "tech_evolution": { "...": "..." },
    "pm_assessment": { "...": "..." },
    "action_plan": { "...": "..." }
  },
  "reports": {
    "full_report_md": "... (Markdown content)",
    "next_directions_md": "... (optional, when output-type includes it)",
    "quality_assessment_md": "... (optional)",
    "prd_draft_md": "... (optional, when --target-doc specified)"
  },
  "metadata": {
    "total_docs": 29,
    "dimensions_executed": [1, 2, 3, 4, 5, 6, 7],
    "models_used": {"text": "claude-sonnet-4-20250514", "vision": "..."}
  }
}
```

## PM Assessment Details

The PM assessment dimension is the most unique and valuable sub-module.

### Writing Style (4 dimensions × 1-5 score)

| Dimension | 5-point | 3-point | 1-point |
|-----------|---------|---------|---------|
| Logic Structure | Clear flowcharts, state machines, decision rules per requirement | Basic structure but not systematic | No structure, scattered descriptions |
| Tech Depth | Accurate SDK versions, APIs, tracking plans, algorithm params | Basically correct but lacks detail | Vague or incorrect |
| Boundary Awareness | Explicit scope and exclusions per document | Some documents have boundaries | No boundary definitions |
| Business Perspective | ROI analysis, quantified user value, business metrics | User value described but not quantified | Technical descriptions only |

### Product Thinking (4 dimensions × 1-5 score)

| Dimension | 5-point | 3-point | 1-point |
|-----------|---------|---------|---------|
| Iteration Thinking | Clear problem evolution chains between requirements | Iteration exists but evolution logic unclear | Isolated requirements, no iteration |
| Experience Thinking | Interaction designed from user cognition perspective | Basic UX consideration | Pure feature description |
| Data Thinking | Data statistics and evaluation plans with key metrics | Data mentioned but no concrete plan | No data-related content |
| Business Thinking | Closed-loop business design with ROI and success criteria | Business thinking but not closed-loop | No business consideration |

### PM Type Classification

- All writing scores ≥ 4 AND business ≤ 2 → **Technical PM**
- Business thinking ≥ 4 AND tech depth ≤ 2 → **Business PM**
| Relatively balanced → **Balanced PM**

### Growth Path Generation

Based on blind-spot dimensions, generate short/mid/long term action items:
- Short-term (1-3 months): Address weakest dimension basics
- Mid-term (3-6 months): Build cross-dimension connection ability
- Long-term (6-12 months): Advance to higher role

## Key Features

- **Same analysis, different outputs**: One 7-dimension pass produces all output types
- **Ordered dimension execution**: Later dimensions receive all prior dimension outputs as context
- **Standalone PM assessment**: `pm_assess.py` can be called independently
- **Configurable industry context**: Competition dimension uses industry templates
- **Review context injection**: Project-level specifications override defaults
- **Targeted document support**: `--target-doc` generates context for a specific new PRD

## Dependencies

```bash
pip install -r requirements.txt
# Core: anthropic, pydantic
```

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `review.py` | Main entry: 7-dimension review with output type selection |
| `pm_assess.py` | Standalone PM assessment (dimension 6 only) |

## Prompts Reference

| Prompt | Purpose |
|--------|---------|
| `system-context.md` | System context injected into all LLM calls |
| `business-value.md` | Dimension 1: Business value analysis |
| `architecture.md` | Dimension 2: Requirement architecture review |
| `competition.md` | Dimension 3: Competitive positioning |
| `product-strategy.md` | Dimension 4: Product strategy evaluation |
| `tech-evolution.md` | Dimension 5: Technical evolution review |
| `pm-assessment.md` | Dimension 6: PM capability assessment |
| `action-plan.md` | Dimension 7: Action plan and prioritization |

For detailed API and customization, see [references/usage-guide.md](references/usage-guide.md).
