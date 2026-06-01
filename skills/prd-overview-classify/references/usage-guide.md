# Usage Guide: prd-overview-classify

## Command Reference

```
python scripts/classify.py <input_dir> <output_json> [options]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `input_dir` | Yes | Directory containing converted Markdown documents (output from docx-to-markdown) |
| `output_json` | Yes | Output JSON file path |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--categories` | `templates/default-categories.json` | Path to custom categories JSON config |
| `--version-pattern` | `V\d+\.\d+[\.\d]*` | Regex for version number extraction from filenames |
| `--use-llm` | off | Use LLM for uncertain classifications (requires ANTHROPIC_API_KEY) |
| `--keyword-only` | off | Use keyword-only classification (no LLM, no API cost) |
| `--include-excerpts` | off | Include document excerpts in output JSON |
| `--excerpt-lines` | 500 | Number of lines to read for excerpt/LLM context |

### Mutual Exclusivity

`--keyword-only` and `--use-llm` cannot be used together. If neither is specified, keyword matching runs first, then LLM is used as fallback for unmatched documents (when ANTHROPIC_API_KEY is available).

## Category Configuration

### Schema

```json
{
  "categories": [
    {
      "name": "string (required)",
      "keywords": ["string"],
      "description": "string"
    }
  ],
  "version_pattern": "regex string",
  "subcategory_pattern": "regex string with 2 capture groups"
}
```

### version_pattern

Regex applied to filenames to extract version numbers. Default matches patterns like `V1.0`, `V2.3.6`.

### subcategory_pattern

Regex with 2 capture groups applied to filenames to extract subcategory tags. Default matches Chinese brackets like `【核心策略v21】`:
- Group 1: subcategory name (e.g., "核心策略")
- Group 2: sequence number (e.g., 21)

Documents sharing the same subcategory name are grouped into the same version chain.

## Output Structure

The output JSON contains 5 top-level sections:

1. **categories**: List of categories with document counts and IDs
2. **version_chains**: Evolution chains linking related documents by version
3. **dependencies**: Inter-document relationships (currently version successors)
4. **documents**: Per-document metadata (id, filename, category, version, title, etc.)
5. **summary**: Aggregate statistics

## Title Extraction Strategy

Titles are extracted in order of priority:
1. **From filename**: Parse the part after the version number (e.g., "智能联动V2.3.6—智能判定流程V3" → "智能判定流程V3")
2. **From content**: First H1 heading in the Markdown file
3. **Fallback**: Empty string

This ensures titles reflect the document's actual topic rather than generic headings like "版本记录".

## LLM Configuration

- `ANTHROPIC_API_KEY`: Required for LLM classification
- `ANTHROPIC_MODEL`: Override default model (default: claude-sonnet-4-20250514)

## Error Handling

- Input directory not found → error exit
- No documents found → error exit
- Invalid categories JSON → falls back to empty categories
- LLM API failure → warning logged, keyword-only results used
- Missing ANTHROPIC_API_KEY → warning logged, LLM step skipped
