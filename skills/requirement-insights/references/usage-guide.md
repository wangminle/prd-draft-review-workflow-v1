# Usage Guide: requirement-insights

## Run Insights Analysis

```
python scripts/insights.py <classify_json> <analysis_dir> <output_json> [options]
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
| `--output-type` | `all` | Output type: evolution, gap, all |
| `--feature-dims` | none | Path to custom feature dimensions JSON (skips LLM extraction) |
| `--include-mermaid` | off | Include Mermaid flowchart in evolution output |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | required | API key for LLM calls |
| `TEXT_MODEL` | claude-sonnet-4-20250514 | Model for text analysis |

## Output Types

| Type | What It Produces |
|------|-----------------|
| `evolution` | Evolution chains with issue resolution tracking + optional Mermaid diagram |
| `gap` | Feature coverage matrix, gap list, overlap list |
| `all` | Both evolution and gap analysis (default) |

## Evolution Tracking Details

### How it works

1. For each version chain, iterate through versions in order
2. For each version's boundary-external issues, search subsequent versions for resolutions
3. Use LLM for semantic matching (same issue described differently across versions)
4. Mark resolution status: resolved / partial / unresolved
5. Optionally generate Mermaid flowchart

### Mermaid Visualization

Enable with `--include-mermaid`. Color coding:
- 🔴 Unresolved issues
- 🟡 Partially resolved
- 🟢 Resolved
- ⚠️ New issue raised

## Gap Analysis Details

### Feature Extraction

Two modes:
1. **LLM extraction** (default): Extract feature dimensions from document boundary_in fields
2. **User-provided** (`--feature-dims`): Skip LLM extraction, use user-defined dimensions

### Custom Feature Dimensions

Create a JSON file:
```json
{
  "feature_dimensions": [
    "服务预约",
    "模式控制",
    "场景联动",
    "数据采集"
  ]
}
```

### Coverage Matrix

Each feature is marked as:
- `covered` — covered by exactly one document
- `overlap` — covered by multiple documents
- `gap` — not covered by any document

## Output Structure

The output JSON matches the schema in `templates/output-schema.json`.

Key top-level fields:
- `evolution`: Evolution tracking results (when output-type includes evolution)
- `gap_analysis`: Gap analysis results (when output-type includes gap)
- `metadata`: Analysis metadata
