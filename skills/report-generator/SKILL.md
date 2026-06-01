---
name: report-generator
description: "Generate structured Markdown and PDF reports from analysis results. Use when (1) rendering per-document analysis results into a readable report, (2) generating a full system review report from 7-dimension analysis, (3) producing a next-directions report from evolution tracking and gap analysis, (4) generating a PM development suggestion report with scoring cards, (5) producing a PRD draft report based on historical analysis, (6) creating Mermaid diagrams for evolution chains and dependency graphs, (7) converting Markdown reports to PDF. Also use when a user mentions 'generate report', 'export report', 'PDF report', 'review report', or 'analysis report'."
license: MIT
compatibility: opencode
---

# Report Generator

Generate structured Markdown and PDF reports from all upstream Skill analysis results. The final deliverable step.

## Report Types

| Report | Source Skills | Description |
|--------|-------------|-------------|
| Per-Analysis Report | Skill 2 + 3 | Per-document 6-dimension analysis with quality scores |
| Full Review Report | Skill 4 (full_report) | Complete 7-dimension system review |
| Next Directions Report | Skill 4 + 5 | Requirement direction recommendations |
| PM Development Report | Skill 4 (quality_assessment) | PM writing/thinking scoring card + growth path |
| PRD Draft Report | Skill 4 (prd_draft) | New PRD draft based on historical analysis |
| Insights Report | Skill 5 | Evolution tracking + gap analysis with coverage matrix |

## Output Formats

| Format | Description |
|--------|-------------|
| Markdown | Structured .md file with tables, headings, Mermaid code blocks |
| PDF | Converted from Markdown with Chinese font support |

## Quick Start

All commands below assume the working directory is the **skill root** (`skills/report-generator/`).
Install dependencies first: `pip install -r requirements.txt`

### Generate reports

```bash
python scripts/generate.py <classify_json> <analysis_dir> <review_json> <output_dir> [options]

# Generate all reports from all upstream results
python scripts/generate.py classify.json ./analysis/ review.json ./reports/

# Specific report type only
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --report-type per_analysis
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --report-type full_review
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --report-type pm_development
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --report-type next_directions
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --report-type insights

# Include insights data (Skill 5 output)
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --insights-json insights.json

# Generate PDF output
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --format pdf

# Both MD and PDF
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --format all

# Polish report with LLM (optional)
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --polish

# Select specific sections
python scripts/generate.py classify.json ./analysis/ review.json ./reports/ --sections overview,per_analysis,evolution
```

## Input

### Required

1. **Classify result JSON** — from `prd-overview-classify`
2. **Analysis directory** — containing `prd-per-analysis` output JSONs
3. **Review result JSON** — from `system-review`
4. **Output directory** — where reports will be written

### Optional

- **Insights JSON** — via `--insights-json` from `requirement-insights` (adds evolution/gap sections)
- **Report type** — via `--report-type` (default: `all`)
- **Output format** — via `--format` (`md`, `pdf`, `all`; default: `md`)
- **Section selection** — via `--sections` for cherry-picking sections
- **Polish** — via `--polish` flag to run LLM-based report polishing

## Output Format

```json
{
  "project_name": "智能联动",
  "files": [
    {
      "type": "markdown",
      "path": "/output/逐篇分析报告.md",
      "size": 94822
    },
    {
      "type": "markdown",
      "path": "/output/体系Review报告.md",
      "size": 48988
    },
    {
      "type": "pdf",
      "path": "/output/体系Review报告.pdf",
      "size": 89000
    }
  ],
  "mermaid_charts": [
    {
      "type": "evolution",
      "chart_id": "dynamic-delay",
      "code": "flowchart TD\n  ..."
    }
  ],
  "summary": {
    "total_reports": 3,
    "total_md_size": 143810,
    "chart_count": 5
  }
}
```

## Report Structures

### Per-Analysis Report

```markdown
# {{project_name}} 需求文档逐篇分析报告

## 一、文档概览
（文档数量、分类分布、版本链概要）

## 二、逐篇分析
### 2.1 {{doc_title}}
- 核心问题：...
- 边界外问题：⚠️ 未解决 / ✅ 已解决
- 质量评分：★★★★☆ 4/5

## 三、边界外问题追踪汇总
| 问题 | 来源版本 | 解决状态 | 解决版本 |

## 四、需求演进脉络
（Mermaid 演进图）

## 五、文档质量评价

## 六、产品经理特征总结
```

### Full Review Report

Same structure as Skill 4's `generate_full_report_md()` output — 7 sections matching the 7 dimensions.

### Insights Report

```markdown
# {{project_name}} 需求洞察报告

## 一、演进链追踪
（Mermaid 演进图 × N + 问题收敛统计）

## 二、功能覆盖矩阵
| 功能维度 | 覆盖文档 | 状态 |

## 三、需求缺口
（缺口列表 + 严重程度 + 建议）

## 四、功能重叠
（重叠列表 + 评估）
```

## Key Features

- **Template-driven rendering**: Data tables auto-generated from JSON, no LLM needed for basic reports
- **Mermaid diagram builder**: Evolution chains, dependency graphs from structured data
- **Optional LLM polish**: `--polish` flag for human-like report refinement
- **PDF support**: Markdown → PDF with Chinese fonts
- **Selective generation**: `--report-type` and `--sections` for cherry-picking
- **Composable**: Each report type is independent, can be generated separately

## Dependencies

```bash
pip install -r requirements.txt
# Core: pydantic
# PDF: reportlab (optional, for PDF output)
```

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `generate.py` | Main entry: render reports + optional PDF |
| `mermaid_builder.py` | Mermaid diagram code generation |

## Prompts Reference

| Prompt | Purpose |
|--------|---------|
| `report-polish.md` | Optional LLM-based report polishing |

For detailed API and customization, see [references/usage-guide.md](references/usage-guide.md).
