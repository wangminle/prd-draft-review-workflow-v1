# Usage Guide: report-generator

## Generate Reports

```
python3 scripts/generate.py <classify_json> <analysis_dir> <review_json> <output_dir> [options]
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
| `--format` | `md` | Output format: `md`（仅 Markdown）、`pdf`（仅 PDF）、`all`（两者） |
| `--sections` | (none) | 逗号分隔的章节别名，覆盖 `--report-type` 进行筛选（见下表） |
| `--polish` | off | Use LLM to polish the report |

### `--sections` 别名

指定 `--sections` 时，将覆盖 `--report-type`，只生成列出的报告类型。别名不区分大小写：

| 别名 | 报告类型 |
|------|---------|
| `overview`, `doc_overview`, `per_analysis`, `analysis` | per_analysis |
| `full_review`, `review`, `system_review` | full_review |
| `next_directions`, `directions` | next_directions |
| `pm_development`, `pm` | pm_development |
| `prd_draft`, `draft` | prd_draft |
| `insights`, `evolution`, `gap` | insights |

```bash
# 只生成逐篇分析和洞察报告
python3 scripts/generate.py classify.json ./analysis/ review.json ./reports/ --sections per_analysis,insights
```

### 输出格式行为

| `--format` | 磁盘文件 | 说明 |
|-----------|---------|------|
| `md` | 仅 `.md` | 默认 |
| `pdf` | 仅 `.pdf` | 不输出 Markdown 文件 |
| `all` | `.md` + `.pdf` | 同时输出两种格式 |

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

## Output Summary

`_generate_result.json` 的 `summary` 字段：

| 字段 | 说明 |
|------|------|
| `total_reports` | 生成的**报告类型数量**（逻辑报告份数） |
| `total_files` | 写入磁盘的**文件数量**（MD 和 PDF 分别计数） |
| `total_md_size` | 所有 Markdown 内容的总字节数 |
| `chart_count` | 收集到的 Mermaid 图表数量 |

## Mermaid Builder

The `mermaid_builder.py` module provides standalone Mermaid diagram generation with automatic escaping of special characters (quotes, pipes, brackets, newlines) to prevent broken chart syntax:

```python
from mermaid_builder import build_evolution_flowchart, build_dependency_graph

evolution_chart = build_evolution_flowchart(evolution_chains)
dependency_chart = build_dependency_graph(dependencies, documents)
```

Main `generate.py` automatically collects three chart types from upstream data:
- **Evolution flowchart** — from `insights.evolution` (falls back to building from `evolution_chains`)
- **Dependency graph** — from `classify.dependencies`
- **Version chain timeline** — from `classify.version_chains`

### Chart Types

| Function | Chart Type | Input |
|----------|-----------|-------|
| `build_evolution_flowchart` | flowchart TD | Evolution chains from requirement-insights |
| `build_dependency_graph` | graph LR | Dependencies from prd-overview-classify |
| `build_coverage_matrix_table` | Markdown table | Coverage matrix from requirement-insights |
| `build_version_chain_timeline` | gantt | Version chains from prd-overview-classify |

## PDF Generation

PDF generation requires `reportlab` and uses the built-in **STSong-Light** CID font for Chinese character support:

```bash
pip3 install reportlab
```

If reportlab is not installed, PDF generation is silently skipped and Markdown output is still produced.

## Polishing

The `--polish` flag uses an LLM to refine the report text. This:
- Preserves all facts and data
- Improves paragraph transitions
- Unifies terminology
- Does NOT add new conclusions

Requires `ANTHROPIC_API_KEY` environment variable and the `anthropic` package (`pip3 install anthropic`).
