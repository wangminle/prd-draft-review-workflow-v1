---
name: prd-overview-classify
description: "Classify and overview a batch of Markdown PRD documents by category, build version evolution chains, and detect inter-document dependencies. Use when categorizing PRD or requirement documents by topic, extracting version numbers, finding document relationships, or generating overview summaries. Also use when you need to understand the structure of a document set before deep analysis, or when a user mentions 'overview', 'categorize', 'classify documents', 'version chain', or 'document relationships'."
license: MIT
compatibility: opencode
---

# PRD Overview & Classification

Automatically classify PRD documents by category, extract version numbers, build version chains, and identify inter-document dependencies.

## Workflow Overview

```
1. Document scanning    → Extract metadata (version, title, excerpt)
2. Classification       → Assign each doc to a category (keyword + LLM)
3. Version chain build  → Link docs in same evolution line
4. Dependency detect    → Find cross-doc references/resolutions
5. Summary output       → Generate structured JSON result
```

## Quick Start

All commands below assume the working directory is the **skill root** (`skills/prd-overview-classify/`).
Install dependencies first: `pip install -r requirements.txt`

### Classify a batch of Markdown documents

```bash
python scripts/classify.py <input_dir> <output_json> [options]

# Basic usage
python scripts/classify.py /path/to/converted_docs result.json

# With custom category config
python scripts/classify.py /path/to/converted_docs result.json --categories templates/default-categories.json

# With LLM fallback for uncertain classifications (requires ANTHROPIC_API_KEY)
python scripts/classify.py /path/to/converted_docs result.json --use-llm

# Override version pattern
python scripts/classify.py /path/to/converted_docs result.json --version-pattern "V\\d+\\.\\d+\\.\\d+"

# Skip LLM, use keyword-only classification (faster, no API cost)
python scripts/classify.py /path/to/converted_docs result.json --keyword-only

# Include document excerpts in output (disabled by default to keep JSON small)
python scripts/classify.py /path/to/converted_docs result.json --include-excerpts

# Customize excerpt length for LLM context
python scripts/classify.py /path/to/converted_docs result.json --excerpt-lines 300
```

### Input directory structure

Expected input is the output of `docx-to-markdown` skill:

```
input_dir/
├── DocumentName1/
│   ├── DocumentName1.md
│   └── assets/
├── DocumentName2/
│   ├── DocumentName2.md
│   └── assets/
└── ...
```

## Output Format

```json
{
  "categories": [
    {
      "name": "核心策略",
      "doc_count": 11,
      "doc_ids": ["doc1", "doc2"]
    }
  ],
  "version_chains": [
    {
      "chain_name": "响应时延",
      "versions": [
        {"version": "V1.8.0", "doc_id": "doc1", "title": "智能联动响应时延V1"},
        {"version": "V2.1.0", "doc_id": "doc2", "title": "智能联动响应时延V2"}
      ]
    }
  ],
  "dependencies": [
    {
      "from_doc_id": "doc2",
      "to_doc_id": "doc1",
      "relation": "version_successor",
      "description": "V2.1.0 is successor to V1.8.0 in chain '响应时延'"
    }
  ],
  "documents": [
    {
      "doc_id": "doc1",
      "filename": "智能联动V2.3.6—智能判定流程V3",
      "md_path": "/path/to/doc.md",
      "category": "核心策略",
      "version": "V2.3.6",
      "subcategory_name": "核心策略",
      "subcategory_seq": 21,
      "title": "智能判定流程V3—兼容新旧算法",
      "line_count": 122,
      "file_size": 156000
    }
  ],
  "summary": {
    "total_docs": 29,
    "total_categories": 5,
    "total_chains": 5,
    "total_dependencies": 3
  }
}
```

> **Note**: The `excerpt` field in `documents` is excluded by default to keep output JSON compact. Use `--include-excerpts` to include it. Downstream skills should read the original `.md` files directly via `md_path`.

## Classification Strategy

### Two-phase approach

1. **Keyword matching** (fast, deterministic): Match document titles against configurable keyword lists
2. **LLM semantic classification** (accurate, costs API calls): For documents not matched by keywords, use LLM to classify based on title + excerpt

When `--keyword-only` is used, unmatched documents get category `"未分类"`.

### Default category keywords

See `templates/default-categories.json`. For domain-specific examples (smart home, SaaS, etc.), see `references/category-examples.md`.

### Custom categories

Create a JSON file with your own category definitions:

```json
{
  "categories": [
    {
      "name": "Your Category",
      "keywords": ["keyword1", "keyword2"],
      "description": "What this category covers"
    }
  ],
  "version_pattern": "V\\d+\\.\\d+[\\.\\d]*",
  "subcategory_pattern": "【(.+?)v(\\d+)】"
}
```

Then pass it with `--categories your-categories.json`.

## Version Chain Detection

Two strategies, used in order:

1. **Subcategory tag clustering**: Extract tags from brackets like `【核心策略v21】`, group by same tag name
2. **Name prefix clustering** (fallback): When no subcategory tags, group by filename prefix before version number (e.g., "功能预约V2.0" and "功能预约V2.1" → same chain)

Steps:
1. Extract version numbers from filenames using regex (configurable)
2. Extract subcategory tags (if present)
3. Cluster documents by semantic topic
4. Sort by version number within each cluster
5. When `--use-llm` is enabled, LLM validates whether semantically related docs belong to the same chain

## Key Features

- **Configurable categories**: Override default keywords via JSON config file
- **Version pattern flexibility**: Regex for version extraction is configurable
- **Compact output**: Excerpts excluded by default, included on demand
- **No LLM required for basic use**: Keyword-only mode works offline with zero API cost
- **Dual chain strategy**: Subcategory tags + name prefix fallback for different doc naming conventions

## Dependencies

```bash
pip install -r requirements.txt
# Core: pydantic (data validation)
# Optional: anthropic (LLM fallback classification)
```

Set `ANTHROPIC_API_KEY` environment variable for LLM mode.
Set `ANTHROPIC_MODEL` to override the default model (default: claude-sonnet-4-20250514).

## Scripts Reference

| Script | Purpose | Dependencies |
|--------|---------|-------------|
| `classify.py` | Main entry: scan + classify + chain build + output | `requirements.txt` |

## Prompts Reference

| Prompt | Purpose | Used When |
|--------|---------|-----------|
| `classify.md` | LLM document classification | `--use-llm` and keyword unmatched |
| `version-chain.md` | LLM version chain validation | `--use-llm` and chain ambiguous |

For detailed API and customization, see [references/usage-guide.md](references/usage-guide.md).
