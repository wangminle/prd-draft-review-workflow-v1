# Usage Guide: prd-per-analysis

## Single Document Analysis

```
python3 scripts/analyze.py <md_path> <output_json> [options]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `md_path` | Yes | Path to the Markdown document |
| `output_json` | Yes | Output JSON file path |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--doc-id` | filename stem | Document ID (from prd-overview-classify) |
| `--category` | empty | Document category |
| `--version` | empty | Document version |
| `--enable-vision` | off | Enable vision engine for image understanding |
| `--context` | none | Path to context JSON for resolution tracking |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | required | API key for both engines |
| `TEXT_MODEL` | claude-sonnet-4-20250514 | Model for text analysis |
| `VISION_MODEL` | claude-sonnet-4-20250514 | Model for image analysis |

## Batch Analysis

```
python3 scripts/batch_analyze.py <classify_result_json> <output_dir> [options]
```

### How it works

1. Reads the output JSON from `prd-overview-classify`
2. For each document, builds a context JSON with subsequent version excerpts
3. Calls `analyze.py` for each document with concurrency control
4. Outputs per-document JSON files + a batch summary

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--enable-vision` | off | Enable vision engine |
| `--max-concurrent` | 3 | Maximum concurrent analyses |
| `--force` | off | Force re-analysis of all documents (ignore incremental cache) |
| `--review-context-version` | empty | ReviewContext version; cache is invalidated when it changes |
| `--skill-root` | auto-detected | Skill root directory |

## Context JSON Format

For resolution tracking, provide a JSON file with other documents' excerpts:

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

In batch mode, this is auto-generated from the classify result's version chains.

## Vision Engine Details

### Image Discovery

Images are found in the `assets/` subdirectory alongside the Markdown file (as produced by `docx-to-markdown`).

### Image Classification

Each image is first classified by the vision engine into one of:
- `flowchart` — Decision trees, process flows, architecture diagrams
- `ui_screenshot` — App pages, web interfaces, device screens
- `data_chart` — Charts, graphs, comparison tables
- `photo` — Real-world photos (user research, etc.)
- `decorative` — Skipped (emojis, logos, dividers, tiny icons)

### Decorative Image Heuristics

Images are pre-filtered before sending to the vision engine:
- Filenames starting with `emoji`, `icon`
- Filenames containing `logo`, `divider`, `separator`
- Files smaller than 500 bytes

This reduces unnecessary vision API calls and token consumption.

### Cost Considerations

Vision analysis approximately doubles the token cost per document (image classification + text analysis with image descriptions). Use `--enable-vision` only when documents contain meaningful visual content.

## Output Structure

Each analysis produces a JSON file matching `templates/output-schema.per-doc-analysis.json` (same shape as `templates/output-schema.json`).

Key fields:
- `core_problem`: 1-2 sentence summary
- `boundary_in/out`: What the requirement covers/excludes
- `boundary_issues`: Related uncovered problems with severity and resolution status
- `key_points`: Type-specific extraction (technical/survey/competitive)
- `expert_review`: Expert-opinion review against 6 predefined rules — `summary` plus `checks[]` entries (`rule_key`, `rule_name`, `status: pass|risk|missing`, `evidence`, `suggestion`); `checks` must cover exactly the 6 rules with no duplicate or missing `rule_key`
- `image_insights`: Vision analysis results (when enabled)
- `quality_score`: 1-5 overall score
- `confidence`: 0-1 analysis confidence
