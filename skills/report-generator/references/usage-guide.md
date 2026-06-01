# Usage Guide: report-generator

## Generate Reports

```
python scripts/generate.py <classify_json> <analysis_dir> <review_json> <output_dir> [options]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `classify_json` | Yes | Path to prd-overview-classify output JSON |
| `analysis_dir` | Yes | Directory containing prd-per-analysis output JSONs |
| `review_json` | Yes | Path to system-review output JSON |
| `output_dir` | Yes | Output directory for reports |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--insights-json` | none | Path to requirement-insights output JSON |
| `--report-type` | `all` | Report type: per_analysis, full_review, next_directions, pm_development, prd_draft, insights, all |
| `--format` | `md` | Output format: md, pdf, all |
| `--sections` | all | Comma-separated sections to include |
| `--polish` | off | Use LLM to polish the report |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | required for --polish | API key for LLM polishing |
| `TEXT_MODEL` | claude-sonnet-4-20250514 | Model for polishing |

## Report Types

| Type | Description |
|------|-------------|
| `per_analysis` | Per-document 6-dimension analysis with quality scores and issue tracking |
| `full_review` | Complete 7-dimension system review report |
| `next_directions` | Next requirement direction recommendations |
| `pm_development` | PM writing/thinking scoring card with growth path |
| `prd_draft` | New PRD draft based on historical analysis |
| `insights` | Evolution tracking + gap analysis with coverage matrix |
| `all` | All report types |

## Mermaid Builder

The `mermaid_builder.py` module provides standalone Mermaid diagram generation:

```python
from mermaid_builder import build_evolution_flowchart, build_dependency_graph

evolution_chart = build_evolution_flowchart(evolution_chains)
dependency_chart = build_dependency_graph(dependencies, documents)
```

### Chart Types

| Function | Chart Type | Input |
|----------|-----------|-------|
| `build_evolution_flowchart` | flowchart TD | Evolution chains from requirement-insights |
| `build_dependency_graph` | graph LR | Dependencies from prd-overview-classify |
| `build_coverage_matrix_table` | Markdown table | Coverage matrix from requirement-insights |
| `build_version_chain_timeline` | gantt | Version chains from prd-overview-classify |

## PDF Generation

PDF generation requires `reportlab`:

```bash
pip install reportlab
```

If reportlab is not installed, PDF generation is silently skipped and Markdown output is still produced.

## Polishing

The `--polish` flag uses an LLM to refine the report text. This:
- Preserves all facts and data
- Improves paragraph transitions
- Unifies terminology
- Does NOT add new conclusions

Requires `ANTHROPIC_API_KEY` environment variable.
