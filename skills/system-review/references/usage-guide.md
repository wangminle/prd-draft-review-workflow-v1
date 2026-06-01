# Usage Guide: system-review

## Full System Review

```
python scripts/review.py <classify_json> <analysis_dir> <output_json> [options]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `classify_json` | Yes | Path to prd-overview-classify output JSON |
| `analysis_dir` | Yes | Directory containing prd-per-analysis output JSONs |
| `output_json` | Yes | Output JSON file path |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output-type` | `full_report` | Output type: full_report, next_directions, quality_assessment, prd_draft, all |
| `--dimensions` | auto | Specific dimensions to execute (e.g., `1,6,7`). Default: determined by output-type |
| `--target-doc` | none | Target document ID for prd_draft or context report |
| `--industry` | none | Industry context (e.g., `smart_home`) for competition dimension |
| `--competition-refs` | none | Path to competitor reference file |
| `--rubric` | none | Path to PM scoring rubric JSON (overrides default) |
| `--review-context` | none | Path to Review Context JSON (scoring rubrics, domain rules, writing standards) |
| `--enable-vision` | off | Enable vision engine for original document images |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | required | API key for LLM calls |
| `TEXT_MODEL` | claude-sonnet-4-20250514 | Model for text analysis |
| `VISION_MODEL` | claude-sonnet-4-20250514 | Model for image analysis |

## Standalone PM Assessment

```
python scripts/pm_assess.py <classify_json> <analysis_dir> <output_json> [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--rubric` | none | Path to PM scoring rubric JSON |

## Output Types and Required Dimensions

| Output Type | Dimensions | Description |
|-------------|-----------|-------------|
| `full_report` | 1,2,3,4,5,6,7 | Complete 7-dimension review report |
| `next_directions` | 1,2,3,4,5,7 | Next requirement direction recommendations |
| `quality_assessment` | 1,6 | PM writing quality and thinking assessment |
| `prd_draft` | 1,2,5,6 | New PRD draft based on historical analysis |
| `all` | 1,2,3,4,5,6,7 | All output types |

## Dimension Execution Order

Dimensions execute in strict order because later dimensions depend on earlier ones:

1. Business Value → 2. Architecture → 3. Competition → 4. Product Strategy → 5. Tech Evolution → 6. PM Assessment → 7. Action Plan

Each dimension receives the output of all prior dimensions as context.

## Review Context Format

The `--review-context` parameter accepts a JSON file:

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

When `scoring_overrides` is present, PM assessment uses the team-defined dimensions and weights instead of defaults.

## Industry Templates

Available industry templates in `templates/`:

| File | Industry | What It Provides |
|------|----------|-----------------|
| `industry-smart-home.json` | Smart Home | Key players, comparison dimensions, market characteristics |

Use via `--industry smart_home`.

## PM Assessment Details

### Scoring Dimensions

**Writing Style** (4 dimensions × 1-5 score):
- Logic Structure, Tech Depth, Boundary Awareness, Business Perspective

**Product Thinking** (4 dimensions × 1-5 score):
- Iteration Thinking, Experience Thinking, Data Thinking, Business Thinking

### PM Type Classification

- Technical PM: Writing scores ≥ 4, Business ≤ 2
- Business PM: Business thinking ≥ 4, Tech depth ≤ 2
- Balanced PM: Relatively balanced across dimensions

### Custom Rubric

Override the default scoring rubric by creating a JSON file matching the format in `templates/pm-scoring-rubric.json` and passing it with `--rubric`.

## Output Structure

The main output is a JSON file matching the schema in `templates/output-schema.json`.

Additionally, Markdown reports are generated alongside the JSON:
- `{stem}_full_report.md`
- `{stem}_next_directions.md`
- `{stem}_quality_assessment.md`
- `{stem}_prd_draft.md`

Which reports are generated depends on the `--output-type` flag.
