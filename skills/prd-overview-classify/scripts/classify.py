#!/usr/bin/env python3
"""prd-overview-classify: 分类 PRD 文档并构建版本演化链。

用法:
    python classify.py <input_dir> <output_json> [options]

输入: 转换后的 Markdown 文档目录（docx-to-markdown 技能的输出）
输出: 包含分类、版本链、依赖关系、文档、摘要的 JSON
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("错误：需要 pydantic，请运行 pip install pydantic", file=sys.stderr)
    sys.exit(1)

DEFAULT_CATEGORIES_PATH = Path(__file__).parent.parent / "templates" / "default-categories.json"
DEFAULT_VERSION_PATTERN = r"V\d+\.\d+[\.\d]*"
DEFAULT_SUBCATEGORY_PATTERN = r"【(.+?)v(\d+)】"
DEFAULT_LLM_MODEL = "claude-sonnet-4-20250514"
EXCERPT_LINES_DEFAULT = 500


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    md_path: str
    category: str = "未分类"
    version: Optional[str] = None
    subcategory_name: Optional[str] = None
    subcategory_seq: Optional[int] = None
    title: str = ""
    excerpt: str = ""
    line_count: int = 0
    file_size: int = 0


class CategoryResult(BaseModel):
    name: str
    doc_count: int = 0
    doc_ids: list[str] = Field(default_factory=list)


class VersionEntry(BaseModel):
    version: str
    doc_id: str
    title: str


class VersionChain(BaseModel):
    chain_name: str
    versions: list[VersionEntry] = Field(default_factory=list)


class Dependency(BaseModel):
    from_doc_id: str
    to_doc_id: str
    relation: str
    description: str


class ClassifyResult(BaseModel):
    categories: list[CategoryResult] = Field(default_factory=list)
    version_chains: list[VersionChain] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    documents: list[DocumentInfo] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


def generate_doc_id(filename: str) -> str:
    return hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]


def extract_version(filename: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, filename)
    return m.group(0) if m else None


def extract_subcategory(filename: str, pattern: str) -> tuple[Optional[str], Optional[int]]:
    m = re.search(pattern, filename)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def extract_title_from_filename(filename: str, version: Optional[str], subcategory_pattern: str = DEFAULT_SUBCATEGORY_PATTERN) -> str:
    if not version:
        return ""
    parts = filename.split(version, 1)
    if len(parts) < 2:
        return ""
    after_version = parts[1].strip("—–-_· ")
    after_version = re.sub(subcategory_pattern, "", after_version).strip("—–-_· ")
    if after_version:
        return after_version
    return ""


def extract_title_from_content(md_path: Path) -> str:
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# ") and len(line) > 2:
                    return line[2:].strip()
    except Exception:
        pass
    return ""


def extract_excerpt(md_path: Path, max_lines: int = EXCERPT_LINES_DEFAULT) -> tuple[str, int]:
    lines = []
    total_lines = 0
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                total_lines += 1
                if i < max_lines:
                    lines.append(line.rstrip())
    except Exception:
        pass
    return "\n".join(lines), total_lines


def load_categories(categories_path: Optional[str] = None) -> dict:
    path = Path(categories_path) if categories_path else DEFAULT_CATEGORIES_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"categories": [], "version_pattern": DEFAULT_VERSION_PATTERN, "subcategory_pattern": DEFAULT_SUBCATEGORY_PATTERN}


def classify_by_keywords(filename: str, title: str, categories_config: list[dict]) -> tuple[str, float]:
    text = f"{filename} {title}".lower()
    best_category = "未分类"
    best_score = 0.0
    for cat in categories_config:
        matched = sum(1 for kw in cat.get("keywords", []) if kw.lower() in text)
        if matched > 0:
            score = matched / len(cat.get("keywords", []))
            if score > best_score:
                best_score = score
                best_category = cat["name"]
    confidence = min(best_score * 2, 1.0) if best_score > 0 else 0.0
    return best_category, confidence


def scan_documents(input_dir: Path, categories_config: dict, version_pattern: str, subcategory_pattern: str, excerpt_lines: int) -> list[DocumentInfo]:
    docs = []
    if not input_dir.exists():
        print(f"错误：输入目录不存在：{input_dir}", file=sys.stderr)
        return docs

    for entry in sorted(input_dir.iterdir()):
        if not entry.is_dir():
            continue
        md_files = list(entry.glob("*.md"))
        if not md_files:
            continue
        md_path = md_files[0]
        filename = entry.name

        version = extract_version(filename, version_pattern)
        subcategory_name, subcategory_seq = extract_subcategory(filename, subcategory_pattern)

        title = extract_title_from_filename(filename, version)
        if not title:
            title = extract_title_from_content(md_path)

        excerpt, line_count = extract_excerpt(md_path, excerpt_lines)

        doc = DocumentInfo(
            doc_id=generate_doc_id(filename),
            filename=filename,
            md_path=str(md_path),
            version=version,
            subcategory_name=subcategory_name,
            subcategory_seq=subcategory_seq,
            title=title,
            excerpt=excerpt,
            line_count=line_count,
            file_size=md_path.stat().st_size,
        )
        docs.append(doc)

    print(f"扫描完成：{len(docs)} 篇文档")
    return docs


def classify_documents(docs: list[DocumentInfo], categories_config: dict, keyword_only: bool = True, use_llm: bool = False) -> None:
    cat_list = categories_config.get("categories", [])
    for doc in docs:
        category, confidence = classify_by_keywords(doc.filename, doc.title, cat_list)
        doc.category = category

    if use_llm and not keyword_only:
        _classify_with_llm(docs, cat_list)

    classified = sum(1 for d in docs if d.category != "未分类")
    unclassified = sum(1 for d in docs if d.category == "未分类")
    print(f"分类完成：{classified} 篇已分类，{unclassified} 篇未分类")


def _classify_with_llm(docs: list[DocumentInfo], cat_list: list[dict]) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("警告：未设置 ANTHROPIC_API_KEY，跳过 LLM 分类", file=sys.stderr)
        return

    try:
        import anthropic
    except ImportError:
        print("警告：未安装 anthropic 包，跳过 LLM 分类", file=sys.stderr)
        return

    unclassified = [d for d in docs if d.category == "未分类"]
    if not unclassified:
        return

    prompts_dir = Path(__file__).parent.parent / "prompts"
    classify_prompt_path = prompts_dir / "classify.md"
    system_prompt = ""
    if classify_prompt_path.exists():
        system_prompt = classify_prompt_path.read_text(encoding="utf-8")

    cat_keywords = "\n".join(
        f"- {c['name']}: {', '.join(c.get('keywords', []))}" for c in cat_list
    )
    doc_list_str = "\n".join(
        f"- [{d.doc_id}] {d.filename}: {d.excerpt[:200]}..." for d in unclassified
    )

    user_msg = f"## 分类体系及关键词\n{cat_keywords}\n\n## 待分类文档列表\n{doc_list_str}"

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_LLM_MODEL)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            result = json.loads(json_match.group())
            id_to_cat = {c["doc_id"]: c["category"] for c in result.get("classifications", [])}
            for doc in unclassified:
                if doc.doc_id in id_to_cat:
                    doc.category = id_to_cat[doc.doc_id]
    except Exception as e:
        print(f"警告：LLM 分类失败：{e}", file=sys.stderr)


def _extract_name_prefix(filename: str, version: Optional[str]) -> Optional[str]:
    if not version:
        return None
    prefix = filename.split(version)[0].strip("—–-_ ")
    return prefix if len(prefix) >= 2 else None


def build_version_chains(docs: list[DocumentInfo], use_llm: bool = False) -> list[VersionChain]:
    chains_dict: dict[str, list[VersionEntry]] = {}
    chained_doc_ids: set[str] = set()

    for doc in docs:
        if doc.subcategory_name and doc.version:
            key = doc.subcategory_name
            if key not in chains_dict:
                chains_dict[key] = []
            chains_dict[key].append(VersionEntry(
                version=doc.version,
                doc_id=doc.doc_id,
                title=doc.title or doc.filename,
            ))
            chained_doc_ids.add(doc.doc_id)

    prefix_groups: dict[str, list[VersionEntry]] = {}
    for doc in docs:
        if doc.doc_id in chained_doc_ids or not doc.version:
            continue
        prefix = _extract_name_prefix(doc.filename, doc.version)
        if prefix:
            if prefix not in prefix_groups:
                prefix_groups[prefix] = []
            prefix_groups[prefix].append(VersionEntry(
                version=doc.version,
                doc_id=doc.doc_id,
                title=doc.title or doc.filename,
            ))

    for prefix, entries in prefix_groups.items():
        if len(entries) >= 2:
            chains_dict[prefix] = entries

    chains = []
    for name, entries in chains_dict.items():
        entries.sort(key=lambda e: _version_sort_key(e.version))
        if len(entries) >= 2:
            chains.append(VersionChain(chain_name=name, versions=entries))

    single_count = sum(
        1 for doc in docs
        if doc.version and doc.doc_id not in {
            v.doc_id for c in chains for v in c.versions
        }
    )

    print(f"版本链：{len(chains)} 条链，{single_count} 篇独立版本")
    return chains


def _version_sort_key(version: str) -> tuple:
    nums = re.findall(r"\d+", version)
    return tuple(int(n) for n in nums)


def detect_dependencies(docs: list[DocumentInfo], chains: list[VersionChain]) -> list[Dependency]:
    deps = []
    for chain in chains:
        for i in range(1, len(chain.versions)):
            prev = chain.versions[i - 1]
            curr = chain.versions[i]
            deps.append(Dependency(
                from_doc_id=curr.doc_id,
                to_doc_id=prev.doc_id,
                relation="version_successor",
                description=f"{curr.version} is successor to {prev.version} in chain '{chain.chain_name}'",
            ))
    print(f"依赖关系：检测到 {len(deps)} 条")
    return deps


def build_category_results(docs: list[DocumentInfo]) -> list[CategoryResult]:
    cat_dict: dict[str, list[str]] = {}
    for doc in docs:
        cat_dict.setdefault(doc.category, []).append(doc.doc_id)
    results = []
    for name, doc_ids in sorted(cat_dict.items()):
        results.append(CategoryResult(name=name, doc_count=len(doc_ids), doc_ids=doc_ids))
    return results


def main():
    parser = argparse.ArgumentParser(description="分类 PRD 文档并构建版本链")
    parser.add_argument("input_dir", help="包含转换后 Markdown 文档的目录")
    parser.add_argument("output_json", help="输出 JSON 文件路径")
    parser.add_argument("--categories", help="自定义分类 JSON 配置文件路径")
    parser.add_argument("--version-pattern", default=DEFAULT_VERSION_PATTERN, help="版本号提取正则表达式")
    parser.add_argument("--use-llm", action="store_true", help="使用 LLM 进行不确定分类")
    parser.add_argument("--keyword-only", action="store_true", help="仅使用关键词分类（不使用 LLM）")
    parser.add_argument("--include-excerpts", action="store_true", help="在输出 JSON 中包含文档摘要（默认不包含）")
    parser.add_argument("--excerpt-lines", type=int, default=EXCERPT_LINES_DEFAULT, help=f"用于摘要/LLM 上下文的读取行数（默认：{EXCERPT_LINES_DEFAULT}）")
    args = parser.parse_args()

    if args.keyword_only and args.use_llm:
        parser.error("--keyword-only 和 --use-llm 不能同时使用")

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"错误：输入目录不存在：{input_dir}", file=sys.stderr)
        sys.exit(1)

    config = load_categories(args.categories)
    version_pattern = config.get("version_pattern", args.version_pattern)
    subcategory_pattern = config.get("subcategory_pattern", DEFAULT_SUBCATEGORY_PATTERN)

    print("=== PRD 概览与分类 ===")
    print(f"输入：{input_dir}")
    print(f"版本号模式：{version_pattern}")

    docs = scan_documents(input_dir, config, version_pattern, subcategory_pattern, args.excerpt_lines)
    if not docs:
        print("未找到文档", file=sys.stderr)
        sys.exit(1)

    classify_documents(docs, config, keyword_only=args.keyword_only, use_llm=args.use_llm)

    chains = build_version_chains(docs, use_llm=args.use_llm)

    deps = detect_dependencies(docs, chains)

    categories = build_category_results(docs)

    if not args.include_excerpts:
        for doc in docs:
            doc.excerpt = ""

    result = ClassifyResult(
        categories=categories,
        version_chains=chains,
        dependencies=deps,
        documents=docs,
        summary={
            "total_docs": len(docs),
            "total_categories": len(categories),
            "total_chains": len(chains),
            "total_dependencies": len(deps),
        },
    )

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2, ensure_ascii=False))

    print(f"\n结果已保存至：{output_path}")
    print(f"摘要：{result.summary}")


if __name__ == "__main__":
    main()
