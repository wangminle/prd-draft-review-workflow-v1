#!/usr/bin/env python3
"""prd-per-analysis: 逐篇 6+1 维度分析 PRD 文档，支持图片理解。

用法:
    python analyze.py <md_path> <output_json> [options]

输入: Markdown文件（docx-to-markdown输出）及可选上下文
输出: 包含 6 个基础维度和 1 个专家意见维度的 JSON
"""

import argparse
import base64
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

DEFAULT_TEXT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_VISION_MODEL = "claude-sonnet-4-20250514"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

DECORATIVE_IMAGE_HEURISTICS = [
    lambda name: name.startswith("emoji"),
    lambda name: name.startswith("icon"),
    lambda name: "logo" in name.lower(),
    lambda name: "divider" in name.lower(),
    lambda name: "separator" in name.lower(),
]


class Resolution(BaseModel):
    status: str = "unresolved"
    resolved_by: Optional[str] = None
    evidence: Optional[str] = None
    note: Optional[str] = None


class BoundaryIssue(BaseModel):
    issue: str
    severity: str = "medium"
    resolution: Resolution = Field(default_factory=Resolution)


class KeyPoints(BaseModel):
    type: str = "technical"
    solution_highlights: list[str] = Field(default_factory=list)
    key_parameters: list[dict] = Field(default_factory=list)


class ImageInsight(BaseModel):
    image_path: str
    image_type: str = "other"
    description: str = ""
    relevant_dimensions: list[str] = Field(default_factory=list)


class ExpertReviewCheck(BaseModel):
    rule_key: str
    rule_name: str
    status: str = "risk"
    evidence: str = ""
    suggestion: str = ""


class ExpertReview(BaseModel):
    summary: str = ""
    checks: list[ExpertReviewCheck] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    doc_id: str = ""
    core_problem: str = ""
    category: str = ""
    boundary_in: list[str] = Field(default_factory=list)
    boundary_out: list[str] = Field(default_factory=list)
    boundary_issues: list[BoundaryIssue] = Field(default_factory=list)
    key_points: KeyPoints = Field(default_factory=KeyPoints)
    expert_review: ExpertReview = Field(default_factory=ExpertReview)
    image_insights: list[ImageInsight] = Field(default_factory=list)
    quality_score: float = 0.0
    confidence: float = 0.0


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("错误：需要设置 ANTHROPIC_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)
    return key


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def read_md_content(md_path: Path) -> str:
    try:
        return md_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"错误：读取文件失败 {md_path}：{e}", file=sys.stderr)
        return ""


def find_images(md_path: Path) -> list[Path]:
    assets_dir = md_path.parent / "assets"
    if not assets_dir.exists():
        return []
    images = []
    for f in sorted(assets_dir.iterdir()):
        if f.suffix.lower() in IMAGE_EXTENSIONS and f.stat().st_size > 0:
            images.append(f)
    return images


def is_decorative(image_path: Path) -> bool:
    name = image_path.stem.lower()
    for heuristic in DECORATIVE_IMAGE_HEURISTICS:
        if heuristic(name):
            return True
    if image_path.stat().st_size < 500:
        return True
    return False


def encode_image_base64(image_path: Path) -> tuple[str, str]:
    ext = image_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = media_types.get(ext, "image/png")
    data = image_path.read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    return media_type, encoded


def classify_image_with_vision(client, image_path: Path, model: str) -> tuple[str, str]:
    media_type, encoded = encode_image_base64(image_path)
    response = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": encoded},
                },
                {
                    "type": "text",
                    "text": "Classify this image in one word: flowchart, ui_screenshot, data_chart, photo, or decorative. Then describe it in one sentence. Format: TYPE|DESCRIPTION",
                },
            ],
        }],
    )
    text = response.content[0].text.strip()
    if "|" in text:
        img_type, desc = text.split("|", 1)
        return img_type.strip().lower(), desc.strip()
    return "other", text


def analyze_images(client, md_path: Path, vision_model: str) -> list[ImageInsight]:
    images = find_images(md_path)
    if not images:
        return []

    insights = []
    for img_path in images:
        if is_decorative(img_path):
            continue
        try:
            img_type, desc = classify_image_with_vision(client, img_path, vision_model)
            if img_type == "decorative":
                continue
            insights.append(ImageInsight(
                image_path=f"assets/{img_path.name}",
                image_type=img_type,
                description=desc,
            ))
        except Exception as e:
            print(f"  警告：图片分析失败 {img_path.name}：{e}", file=sys.stderr)

    return insights


def build_image_descriptions(image_insights: list[ImageInsight]) -> str:
    if not image_insights:
        return "无图片"
    lines = []
    for ins in image_insights:
        lines.append(f"- [{ins.image_type}] {ins.image_path}: {ins.description}")
    return "\n".join(lines)


def analyze_with_llm(client, md_content: str, category: str, version: str,
                      image_descriptions: str, text_model: str) -> dict:
    system_prompt = load_prompt("per-doc-analysis.md")
    if not system_prompt:
        system_prompt = "你是一位资深产品经理，擅长分析需求文档。"

    user_msg = f"""## 文档全文
{md_content}

## 文档分类
{category or "未分类"}

## 版本号
{version or "未知"}

## 图片描述
{image_descriptions}"""

    response = client.messages.create(
        model=text_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = response.content[0].text
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {"raw_output": text}


def track_resolutions(client, issues: list[dict], other_docs_excerpts: list[dict],
                       text_model: str) -> list[dict]:
    if not issues or not other_docs_excerpts:
        return issues

    system_prompt = load_prompt("resolution-tracking.md")
    docs_str = json.dumps(other_docs_excerpts, ensure_ascii=False, indent=2)

    updated_issues = []
    for issue in issues:
        issue_str = issue.get("issue", "")
        user_msg = f"## 边界外问题描述\n{issue_str}\n\n## 后续版本文档摘要\n{docs_str}"

        try:
            response = client.messages.create(
                model=text_model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = response.content[0].text
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                result = json.loads(json_match.group())
                issue["resolution"] = result.get("resolution", issue.get("resolution"))
        except Exception as e:
            print(f"  警告：解决追踪失败：{e}", file=sys.stderr)

        updated_issues.append(issue)

    return updated_issues


def main():
    parser = argparse.ArgumentParser(description="逐篇 6+1 维度分析 PRD 文档")
    parser.add_argument("md_path", help="Markdown文档路径")
    parser.add_argument("output_json", help="输出JSON文件路径")
    parser.add_argument("--doc-id", default="", help="文档ID（来自prd-overview-classify）")
    parser.add_argument("--category", default="", help="文档分类")
    parser.add_argument("--version", default="", help="文档版本号")
    parser.add_argument("--enable-vision", action="store_true", help="启用图片理解引擎")
    parser.add_argument("--context", help="上下文JSON路径（其他文档摘要，用于解决追踪）")
    args = parser.parse_args()

    md_path = Path(args.md_path)
    if not md_path.exists():
        print(f"错误：文件不存在：{md_path}", file=sys.stderr)
        sys.exit(1)

    api_key = get_api_key()
    try:
        import anthropic
    except ImportError:
        print("错误：需要 anthropic，请运行 pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    text_model = os.environ.get("TEXT_MODEL", DEFAULT_TEXT_MODEL)
    vision_model = os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL)

    print("=== PRD 逐篇分析 ===")
    print(f"文档：{md_path.name}")
    print(f"文本引擎：{text_model}")
    print(f"图片理解：{'已启用' if args.enable_vision else '未启用'}")

    md_content = read_md_content(md_path)
    if not md_content:
        print("错误：文档为空或无法读取", file=sys.stderr)
        sys.exit(1)

    image_insights = []
    image_descriptions = "无图片"
    if args.enable_vision:
        print(f"正在分析图片（引擎：{vision_model}）...")
        image_insights = analyze_images(client, md_path, vision_model)
        image_descriptions = build_image_descriptions(image_insights)
        print(f"  发现 {len(image_insights)} 张相关图片")

    print(f"正在分析文档（引擎：{text_model}）...")
    raw_result = analyze_with_llm(client, md_content, args.category, args.version,
                                   image_descriptions, text_model)

    if "raw_output" in raw_result:
        print("警告：LLM未返回有效JSON，已保存原始输出", file=sys.stderr)

    other_docs = []
    if args.context:
        try:
            with open(args.context, "r", encoding="utf-8") as f:
                ctx = json.load(f)
                other_docs = ctx.get("other_docs_excerpts", [])
        except Exception as e:
            print(f"警告：加载上下文失败：{e}", file=sys.stderr)

    if other_docs and raw_result.get("boundary_issues"):
        print(f"正在追踪解决情况（跨 {len(other_docs)} 篇文档）...")
        raw_result["boundary_issues"] = track_resolutions(
            client, raw_result["boundary_issues"], other_docs, text_model
        )

    raw_result.setdefault("doc_id", args.doc_id or md_path.stem)
    raw_result.setdefault("image_insights", [ins.model_dump() for ins in image_insights])

    try:
        result = AnalysisResult(**raw_result)
    except Exception as e:
        print(f"警告：结果校验问题：{e}，保存原始结果", file=sys.stderr)
        result = AnalysisResult(doc_id=args.doc_id or md_path.stem)

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2, ensure_ascii=False))

    print(f"\n结果已保存至：{output_path}")
    print(f"质量评分：{result.quality_score} | 置信度：{result.confidence}")
    print(f"边界外问题：{len(result.boundary_issues)} 条 | 图片洞察：{len(result.image_insights)} 条")


if __name__ == "__main__":
    main()
