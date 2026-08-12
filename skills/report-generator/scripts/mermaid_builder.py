#!/usr/bin/env python3
"""Mermaid图表代码生成器：从结构化数据生成Mermaid图表代码。

所有面向 Mermaid 的文本（节点标签、边标签、关系名称）在输出前
都会经过 ``_escape_mermaid_label`` 清洗，避免引号、竖线、方括号和
换行等特殊字符破坏图表语法。
"""

# Mermaid 节点标签和边标签中需要转义的字符。
# HTML 实体形式可以安全地嵌入 Mermaid 的 ["..."] 和 |...| 上下文。
_MERMAID_ESCAPE_MAP = {
    '"': "&quot;",
    "|": "&verbar;",
    "[": "&#91;",
    "]": "&#93;",
    "(": "&#40;",
    ")": "&#41;",
    "{": "&#123;",
    "}": "&#125;",
    "<": "&lt;",
    ">": "&gt;",
    "#": "&#35;",
    "\n": " ",
    "\r": " ",
}


def _escape_mermaid_label(text: str) -> str:
    """转义 Mermaid 节点标签和边标签中的特殊字符。

    - 引号、方括号、花括号、尖括号等会破坏 Mermaid 语法；
    - 竖线会截断边标签；
    - 换行会导致图表解析中断。

    统一替换为 HTML 实体或空格，保证生成的代码可以被 Mermaid 渲染器接受。
    """
    if not text:
        return ""
    result = text
    for char, replacement in _MERMAID_ESCAPE_MAP.items():
        result = result.replace(char, replacement)
    return result


def _sanitize_node_id(raw: str) -> str:
    """把任意字符串清洗为合法的 Mermaid 节点 ID。

    Mermaid 节点 ID 只能包含字母、数字、下划线，因此把其余字符替换为 ``_``，
    并保证非空（空值回退为 ``node``）。
    """
    if not raw:
        return "node"
    cleaned = []
    for ch in str(raw):
        if ch.isalnum() or ch == "_":
            cleaned.append(ch)
        else:
            cleaned.append("_")
    node_id = "".join(cleaned)
    return node_id or "node"


def build_evolution_flowchart(evolution_chains: list[dict]) -> str:
    lines = ["flowchart TD"]
    for ci, chain in enumerate(evolution_chains):
        versions = chain.get("versions", [])
        prev_node = None
        for i, v in enumerate(versions):
            version_str = _sanitize_node_id(v.get("version", f"v{i}"))
            title = v.get("title", "")
            remaining = v.get("boundary_issues_remaining", [])
            resolved = v.get("boundary_issues_resolved")

            if remaining and resolved:
                label = f"🟡 {title}"
            elif remaining:
                label = f"🔴 {title}"
            elif resolved:
                label = f"🟢 {title}"
            else:
                label = title

            node_id = f"chain{ci}_{version_str}"
            lines.append(f'    {node_id}["{_escape_mermaid_label(label)}"]')

            if prev_node:
                if resolved:
                    lines.append(f"    {prev_node} -->|{_escape_mermaid_label('解决')}| {node_id}")
                elif remaining and not resolved:
                    lines.append(f"    {prev_node} -->|{_escape_mermaid_label('未解决')}| {node_id}")
                else:
                    lines.append(f"    {prev_node} --> {node_id}")
            prev_node = node_id

    return "\n".join(lines)


def build_dependency_graph(dependencies: list[dict], documents: list[dict]) -> str:
    lines = ["graph LR"]
    for dep in dependencies:
        from_id = dep.get("from_doc_id", "")
        to_id = dep.get("to_doc_id", "")
        relation = dep.get("relation", "depends")
        if from_id and to_id:
            from_id_clean = _sanitize_node_id(from_id)[:40]
            to_id_clean = _sanitize_node_id(to_id)[:40]
            lines.append(
                f"    {from_id_clean} -->|{_escape_mermaid_label(relation)}| {to_id_clean}"
            )
    return "\n".join(lines)


def build_coverage_matrix_table(coverage_matrix: list[dict]) -> str:
    lines = ["| 功能维度 | 覆盖文档 | 状态 |", "|---------|---------|------|"]
    for entry in coverage_matrix:
        feature = entry.get("feature", "")
        covered_by = ", ".join(entry.get("covered_by", [])) or "-"
        status = entry.get("status", "")
        icon = {"covered": "✅", "gap": "❌", "overlap": "🔄"}.get(status, "❓")
        lines.append(
            f"| {_escape_md_cell(feature)} | {_escape_md_cell(covered_by)} | "
            f"{icon} {_escape_md_cell(status)} |"
        )
    return "\n".join(lines)


def build_version_chain_timeline(version_chains: list[dict]) -> str:
    lines = ["gantt", "    title 需求演进时间线"]
    for chain in version_chains:
        chain_name = chain.get("chain_name", "chain")
        versions = chain.get("versions", [])
        if versions:
            lines.append(f"    section {_escape_mermaid_label(chain_name)}")
            for v in versions:
                title = v.get("title", v.get("version", ""))
                version_id = _sanitize_node_id(v.get("version", "v1"))
                lines.append(
                    f"    {_escape_mermaid_label(title)} :done, {version_id}, 1d"
                )
    return "\n".join(lines)


# ── Markdown 表格单元转义 ──────────────────────────────────────────────


def _escape_md_cell(text) -> str:
    """转义 Markdown 表格单元格中的特殊字符。

    - 竖线 ``|`` 会截断列；
    - 换行会破坏表格行；
    - 连续空格在 Markdown 表格中无意义。

    返回安全的单行字符串。
    """
    if text is None:
        return ""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()
