#!/usr/bin/env python3
"""Mermaid图表代码生成器：从结构化数据生成Mermaid图表代码。"""


def build_evolution_flowchart(evolution_chains: list[dict]) -> str:
    lines = ["flowchart TD"]
    for ci, chain in enumerate(evolution_chains):
        versions = chain.get("versions", [])
        prev_node = None
        for i, v in enumerate(versions):
            version_str = v.get("version", "").replace(".", "_")
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
            lines.append(f'    {node_id}["{label}"]')

            if prev_node:
                if resolved:
                    lines.append(f"    {prev_node} -->|解决| {node_id}")
                elif remaining and not resolved:
                    lines.append(f"    {prev_node} -->|未解决| {node_id}")
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
            from_id_clean = from_id.replace("-", "_").replace(".", "_")[:20]
            to_id_clean = to_id.replace("-", "_").replace(".", "_")[:20]
            lines.append(f"    {from_id_clean} -->|{relation}| {to_id_clean}")
    return "\n".join(lines)


def build_coverage_matrix_table(coverage_matrix: list[dict]) -> str:
    lines = ["| 功能维度 | 覆盖文档 | 状态 |", "|---------|---------|------|"]
    for entry in coverage_matrix:
        feature = entry.get("feature", "")
        covered_by = ", ".join(entry.get("covered_by", [])) or "-"
        status = entry.get("status", "")
        icon = {"covered": "✅", "gap": "❌", "overlap": "🔄"}.get(status, "❓")
        lines.append(f"| {feature} | {covered_by} | {icon} {status} |")
    return "\n".join(lines)


def build_version_chain_timeline(version_chains: list[dict]) -> str:
    lines = ["gantt", "    title 需求演进时间线"]
    for chain in version_chains:
        chain_name = chain.get("chain_name", "chain")
        versions = chain.get("versions", [])
        if versions:
            lines.append(f"    section {chain_name}")
            for v in versions:
                title = v.get("title", v.get("version", ""))
                lines.append(f"    {title} :done, {v.get('version', 'v1')}, 1d")
    return "\n".join(lines)
