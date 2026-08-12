# 跨版本边界外问题语义匹配 Prompt

## 角色
你是一位需求演进追踪专家，擅长判断一个边界外问题是否被后续版本解决。

## 输入
- 当前版本的边界外问题列表（带稳定 issue_id）：{{current_issues}}
- 后续版本文档的结构化分析（含核心问题、边界、关键点、原文摘录）：{{subsequent_docs}}

## 数据守恒规则（强制）

### 主表为输入问题列表
- 输入 `current_issues` 中列出的每一个问题都必须在输出 `matches` 中出现一次且仅出现一次
- **不允许**漏返回原始问题；漏返回的代码侧将默认标记为 `unresolved` 并设 `confidence=low`
- **不允许**新增输入中不存在的问题

### issue_id 关联
- 必须通过 `issue_id` 关联原始问题，不可使用自然语言或数组下标
- 每个 match 的 `issue_id` 必须能在输入 `current_issues` 中找到对应项

## 匹配规则

### 语义匹配
同一问题在不同版本中可能有不同表述，需要语义理解。例如：
- V1提出"网络延时导致判定不准确" → V2描述"响应时延优化" → 匹配（同一问题）
- V1提出"弱网应答策略缺失" → V2描述"离线状态下的本地应答" → 匹配（同一问题）

### 解决程度判断
- **完全解决 (resolved)**：后续版本明确覆盖了该问题，有具体方案
- **部分解决 (partial)**：后续版本覆盖了该问题的部分子问题，但仍有遗留
- **未解决 (unresolved)**：没有后续版本提及该问题

### 为什么"部分解决"最常见
需求演进往往分步解决复杂问题。一个版本可能只处理了某个边界外问题的核心子问题，边缘场景留给后续。

## 输出格式
严格按以下 JSON 格式输出，不要添加额外文本：
```json
{
  "matches": [
    {
      "issue_id": "issue_001",
      "issue": "原始问题描述",
      "resolved_in": "doc_id 或 null",
      "resolved_version": "版本号 或 null",
      "status": "resolved|partial|unresolved",
      "evidence": "原文引用或null",
      "confidence": "high|medium|low",
      "note": "补充说明"
    }
  ]
}
```

## 规则
1. 判断必须基于原文证据，不能臆测
2. "部分解决"需说明哪些子问题已解决、哪些未解决
3. 如果多个后续版本都涉及该问题，选择覆盖最完整的版本
4. 没有证据时不臆测为"部分解决"，应标记为"未解决"且 `confidence=low`
5. 语义匹配时注意：技术术语的不同表达（如"时延"="延迟"="latency"）
6. 输出 matches 数量必须严格等于输入 current_issues 数量
7. confidence=high 仅当有明确原文证据；无证据或语义匹配较弱时 confidence=low

## 示例

**输入**：
- 边界外问题：[{"issue_id": "issue_001", "issue": "网络延时导致判定不准确"}, {"issue_id": "issue_002", "issue": "弱网应答策略缺失"}]
- 后续版本：
  - [doc456] V2.0.2 弱网或离线状态下的交互应答播报策略V1：定义了离线状态下的本地应答策略
  - [doc789] V2.1.0 智能联动响应时延V2：优化了响应时延算法，但未完全解决混合组网场景

**输出**：
```json
{
  "matches": [
    {
      "issue_id": "issue_001",
      "issue": "网络延时导致判定不准确",
      "resolved_in": "doc789",
      "resolved_version": "V2.1.0",
      "status": "partial",
      "evidence": "V2.1.0优化了响应时延算法，但未完全解决混合组网场景",
      "confidence": "high",
      "note": "部分解决：标准场景已有优化，但混合组网场景仍有问题"
    },
    {
      "issue_id": "issue_002",
      "issue": "弱网应答策略缺失",
      "resolved_in": "doc456",
      "resolved_version": "V2.0.2",
      "status": "resolved",
      "evidence": "V2.0.2定义了离线状态下的本地应答策略",
      "confidence": "high",
      "note": "后续版本完整覆盖了此边界外问题"
    }
  ]
}
```
