---
name: prd-per-analysis
description: "Analyze individual PRD documents across 6 dimensions with vision support for images. Use when (1) analyzing a PRD document's core problem, boundaries, and boundary-external issues, (2) tracking whether issues are resolved in later versions, (3) extracting key parameters and solution highlights from technical PRDs, (4) scoring document quality, (5) understanding flowcharts, architecture diagrams, UI mockups, or screenshots embedded in PRD documents. Also use when a user mentions 'per-doc analysis', 'boundary analysis', 'issue tracking', 'document review', or 'PRD quality scoring'."
license: MIT
compatibility: opencode
---

# PRD Per-Document Analysis

Analyze each PRD document across 6 dimensions with optional vision (multimodal) support for embedded images.

This is the highest-value step in the review pipeline — "boundary-external issue tracking" reveals the evolution logic between requirements.

## Dual Engine Architecture

This skill uses two LLM engines:

| Engine | Purpose | Default Model | When Used |
|--------|---------|---------------|-----------|
| `text_engine` | Text analysis (6 dimensions, resolution tracking) | `claude-sonnet-4-20250514` | Always |
| `vision_engine` | Image understanding (diagrams, UI, flowcharts) | `claude-sonnet-4-20250514` | When `--enable-vision` and images exist |

Override via environment variables:
- `TEXT_MODEL` / `VISION_MODEL` — override default models
- `ANTHROPIC_API_KEY` — required for both engines

Vision is **opt-in** because images consume significantly more tokens. When enabled, images are classified before sending to the vision engine to avoid wasting tokens on decorative images.

### Image Classification

| Image Type | Action | Examples |
|-----------|--------|---------|
| Flowchart / Architecture diagram | Send to vision engine | Decision trees, system architecture, sequence diagrams |
| UI / App screenshot | Send to vision engine | App pages, web interfaces, device screens |
| Data chart / Table image | Send to vision engine | Bar charts, pie charts, comparison tables |
| Decorative / Emoji / Icon | Skip | Decorative dividers, emoji, brand logos |
| Photo / Illustration | Context-dependent | User research photos may be relevant |

## Six-Dimension Analysis Framework

| Dim | Name | What It Captures | Output Field |
|-----|------|-----------------|--------------|
| 1 | Core Problem | The specific problem this requirement solves | `core_problem` |
| 2 | Category | Which functional domain it belongs to | `category` |
| 3 | Boundary | What it does and doesn't cover | `boundary_in[]`, `boundary_out[]` |
| 4 | Boundary-External Issues | Related problems NOT covered by this requirement | `boundary_issues[]` |
| 5 | Resolution Tracking | Whether boundary issues are resolved in later versions | `boundary_issues[].resolution` |
| 6 | Key Points Extraction | Type-specific highlights (technical/survey/competitive) | `key_points` |

**Dimension 6 type-specific rules:**

| Doc Type | What to Extract |
|----------|----------------|
| Technical | Solution highlights + key parameters (thresholds, timeouts, algorithm names) |
| Survey | Research method + core insights |
| Competitive | Comparison dimensions + gap analysis |

### Quality Scoring

| Score | Criteria |
|-------|----------|
| 5 | Clear boundaries, boundary-external issues acknowledged, parameters complete |
| 4 | Relatively clear boundaries, some boundary-external issues recognized |
| 3 | Basic boundaries exist, but insufficient boundary-external issue identification |
| 2 | Vague boundaries, missing key parameters |
| 1 | No boundary definition, core problem unclear |

## Quick Start

All commands below assume the working directory is the **skill root** (`skills/prd-per-analysis/`).
Install dependencies first: `pip install -r requirements.txt`

### Analyze a single document

```bash
python scripts/analyze.py <md_path> <output_json> [options]

# Basic text-only analysis
python scripts/analyze.py /path/to/doc.md result.json

# With category and version from prd-overview-classify
python scripts/analyze.py /path/to/doc.md result.json --category "核心策略" --version "V2.3.6"

# Enable vision for images in assets/ folder
python scripts/analyze.py /path/to/doc.md result.json --enable-vision

# With other docs' excerpts for resolution tracking
python scripts/analyze.py /path/to/doc.md result.json --context context.json
```

### Analyze a batch of documents

```bash
python scripts/batch_analyze.py <classify_result_json> <output_dir> [options]

# Basic batch analysis (text only)
python scripts/batch_analyze.py classify-result.json ./analysis-results/

# With vision enabled
python scripts/batch_analyze.py classify-result.json ./analysis-results/ --enable-vision

# Control concurrency (default: 3)
python scripts/batch_analyze.py classify-result.json ./analysis-results/ --max-concurrent 5
```

## Input

### Single document mode

The `analyze.py` script takes a Markdown file path and optional context.

### Batch mode

The `batch_analyze.py` script takes the **output JSON from `prd-overview-classify`** as input, which contains document paths, categories, and version chains needed for resolution tracking.

### Context JSON (for resolution tracking)

```json
{
  "other_docs_excerpts": [
    {
      "doc_id": "abc123",
      "version": "V2.3.5",
      "title": "智能判定下发策略V2",
      "boundary_issues": ["edge case not handled"]
    }
  ]
}
```

## Output Format

```json
{
  "doc_id": "abc123",
  "core_problem": "新旧算法设备混合组网的判定流程",
  "category": "核心策略",
  "boundary_in": [
    "新旧算法混合判定流程",
    "算法版本标记机制"
  ],
  "boundary_out": [
    "纯新/纯旧算法场景（已有独立流程）"
  ],
  "boundary_issues": [
    {
      "issue": "混合组网时边缘情况的权重配比未详细定义",
      "severity": "medium",
      "resolution": {
        "status": "unresolved",
        "resolved_by": null,
        "evidence": null,
        "note": "当前版本未覆盖此场景"
      }
    }
  ],
  "key_points": {
    "type": "technical",
    "solution_highlights": ["NewTop vs OldTop×0.7 对比", "3阶段过渡方案"],
    "key_parameters": [
      {"name": "混合策略阈值", "value": "0.7"},
      {"name": "A/B测试周期", "value": "2周"}
    ]
  },
  "image_insights": [
    {
      "image_path": "assets/image3.png",
      "image_type": "flowchart",
      "description": "新旧算法判定的3阶段流程：纯新→纯旧→混合",
      "relevant_dimensions": ["core_problem", "boundary_in"]
    }
  ],
  "quality_score": 4.0,
  "confidence": 0.92
}
```

## Key Features

- **Dual engine**: Text engine for analysis, vision engine for images (opt-in)
- **Image classification**: Automatically filters decorative images before sending to vision engine
- **Resolution tracking**: Cross-references boundary issues with other documents
- **Type-aware extraction**: Different extraction rules for technical/survey/competitive docs
- **Batch processing**: Concurrent analysis with configurable rate limiting
- **Incremental**: Analyze only new or changed documents

## Dependencies

```bash
pip install -r requirements.txt
# Core: anthropic, pydantic
# Optional: Pillow (image format detection)
```

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `analyze.py` | Single document analysis (text + vision) |
| `batch_analyze.py` | Batch analysis with concurrency control |

## Prompts Reference

| Prompt | Purpose |
|--------|---------|
| `per-doc-analysis.md` | 6-dimension analysis (text + vision) |
| `resolution-tracking.md` | Boundary issue resolution tracking |

For detailed API and customization, see [references/usage-guide.md](references/usage-guide.md).
