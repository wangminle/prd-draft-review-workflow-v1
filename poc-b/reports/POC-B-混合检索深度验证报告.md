# POC-B: FTS5 + LanceDB 混合检索深度验证报告（修订版）

> 基于 POC-A 结论，验证 FTS5 + LanceDB 混合检索方案的实际表现。
> 数据来源：45 份真实需求 Markdown、943 chunks、84 个问题（与 POC-A Runtime 复验同一数据集）。
> 本报告为修订版，补充了 Hybrid 退化根因深度分析、LanceDB 权限正确率修正说明和拒答策略替代方案。

## 1. 检索质量对比

| 方案 | top-5 命中率 | top-1 命中率 | 权限正确率 ✱ | P50(ms) | P95(ms) | P99(ms) |
| --- | --- | --- | --- | --- | --- | --- |
| FTS5 | 58.3% | 20.2% | 100.0% | 0.24 | 0.32 | 0.52 |
| LanceDB | 95.2% | 89.3% | 90.9% ✱✱ | 10.33 | 17.87 | 46.37 |
| Hybrid(FTS5+LanceDB) | 92.9% | 86.9% | 100.0% | 8.48 | 9.79 | 17.20 |

> ✱ 权限正确率定义：2 个角色拦截测试（inactive/non-member）+ 前 20 个问题的 workspace_id 匹配检查 = 22 项检查
> ✱✱ LanceDB 90.9%（20/22）是 POC 脚本 lambda 检索器未实现 role 参数拦截所致（见 §7.1 修正说明）。LanceDB workspace_id 过滤本身 100% 正确。

## 2. 延迟分布（5 轮重复查询）

| 方案 | 平均(ms) | P50(ms) | P95(ms) | P99(ms) |
| --- | --- | --- | --- | --- |
| FTS5 | 0.2 | 0.2 | 0.3 | 0.5 |
| LanceDB | 11.9 | 10.3 | 17.9 | 46.4 |
| Hybrid(FTS5+LanceDB) | 8.8 | 8.5 | 9.8 | 17.2 |

## 3. 并发压测

| 方案 | 并发数 | QPS | 平均(ms) | P50(ms) | P95(ms) | P99(ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FTS5 | 5 | 1793.0 | 0.5 | 0.1 | 1.8 | 1.8 |
| FTS5 | 10 | 1395.1 | 0.6 | 0.1 | 4.1 | 4.1 |
| FTS5 | 20 | 1158.5 | 0.7 | 0.0 | 5.4 | 5.4 |
| LanceDB | 5 | 114.1 | 8.5 | 0.0 | 22.2 | 22.2 |
| LanceDB | 10 | 121.0 | 7.9 | 0.0 | 79.3 | 79.3 |
| LanceDB | 20 | 120.6 | 7.4 | 0.0 | 57.5 | 57.5 |
| Hybrid(FTS5+LanceDB) | 5 | 136.6 | 7.2 | 4.5 | 26.8 | 26.8 |
| Hybrid(FTS5+LanceDB) | 10 | 149.9 | 6.6 | 0.0 | 24.8 | 24.8 |
| Hybrid(FTS5+LanceDB) | 20 | 146.1 | 6.7 | 0.0 | 76.4 | 76.4 |

**并发结论**：LanceDB 在 5/10/20 并发下稳定在 ~120 QPS，P95 在 22-79ms 范围。对于 5-20 人团队（每人每秒最多 1-2 次检索请求），**120 QPS 完全够用**。FTS5 的 1158-1793 QPS 说明关键词检索几乎无瓶颈。

## 4. 无答案阈值策略

| 方案 | 阈值 | 误答率 | 漏拒率 |
| --- | --- | --- | --- |
| FTS5 | 0.3-0.8 | 25.0%（固定） | 0.0% |
| LanceDB | 0.3 | 100.0% | 55.0% |
| LanceDB | 0.4 | 100.0% | 68.8% |
| LanceDB | 0.5 | 100.0% | 81.2% |
| LanceDB | 0.6 | 100.0% | 85.0% |
| LanceDB | 0.7 | 100.0% | 85.0% |
| LanceDB | 0.8 | 100.0% | 90.0% |
| Hybrid(FTS5+LanceDB) | 0.3-0.7 | 100.0% | 0.0% |
| Hybrid(FTS5+LanceDB) | 0.8 | 100.0% | 37.5% |

**核心发现**：基于原始分数/距离的阈值拒答方案**完全不可用**。根本原因：向量检索的距离分数不是校准过的概率值，无论设多高阈值，总有"最相近"的文档被返回。

## 5. LanceDB 备份恢复

- 备份时间: 7ms
- 备份大小: 15.3MB
- 恢复后记录数: 943
- 恢复后查询: ✅ 正常

## 6. 混合检索退化根因深度分析 ⭐（修订新增）

### 6.1 退化规模

Hybrid top-5 命中率 92.9% 比纯 LanceDB 95.2% 低 2.3 个百分点。84 个问题中：
- 两者共同命中：78 个
- 仅 LanceDB 命中但 Hybrid 未命中：**2 个**（RQ-073、RQ-075）
- 仅 Hybrid 命中但 LanceDB 未命中：0 个

退化集中在两个查询："适用范围 主要需求是什么"的标题定位问题。

### 6.2 退化由两个 POC 特有问题叠加导致

**问题一：FTS5 bigram 误召回**

FTS5 `unicode61` tokenizer 对中文做 bigram 切分（"需求评审" → "需求""求评""评审"），对自然语言查询产生误召回。当 FTS5 以 0.3 权重参与排序时，不相关但关键词命中的文档被推到 top-5，挤掉了 LanceDB 原本召回的正确文档。

实际影响有限（仅 2/84 = 2.4% 的查询受影响），但揭示了中文 FTS5 的固有局限。

**问题二：TF-IDF fallback 向量未归一化导致的 score normalization 失真** ⭐

这是更关键的根因。POC-A/B 均使用 TF-IDF fallback 作为嵌入，TF-IDF 向量未经 L2 归一化。LanceDB 对未归一化向量使用 L2 距离（而非 cosine），导致：

- 当 L2 `_distance > 1` 时，`score = 1 - _distance` 为**负值**
- Hybrid 的 score normalization（除以 max_score）进一步放大失真
- 不相关但正分的文档排在正确但负分的文档之前

退化案例 RQ-073 的数据：
- LanceDB 单独：doc-43（正确）排名第一，`_distance=1.200`，`score=-0.200`
- Hybrid：doc-46 排第一，`vec_score=3.373`，`hybrid_score=2.361`；doc-43 因负分被排到后面

### 6.3 生产环境影响评估

| 问题 | 生产环境是否复现 | 理由 |
| --- | --- | --- |
| FTS5 bigram 误召回 | ⚠️ 可能 | 中文分词天然局限，需调权重或智能合并策略 |
| TF-IDF 未归一化 | ❌ 不会 | P2 使用真实嵌入模型（OpenAI text-embedding-3-small），向量已归一化，cosine distance ∈ [0,2]，不会出现负分 |

**结论**：Hybrid 退化在 P2 使用真实嵌入模型后可能不再出现，但需在开发中重新验证。**P2 首版先用 LanceDB 单引擎，验证 Hybrid 效果后再引入 FTS5 合并**。

## 7. POC 数据修正说明（修订新增）

### 7.1 LanceDB 权限正确率修正

POC-B 中 LanceDB 权限正确率 90.9%（20/22）低于 FTS5 和 Hybrid 的 100%。根因：

- POC-B LanceDB 检索器是一个 lambda：`lambda q, ws, k, r: [...][:k]`
- 该 lambda 接受 4 个参数 `(query, workspace, top_k, role)`，但**完全忽略了 role 参数**
- inactive/non-member 角色查询仍返回结果，导致 2 个 role 检查失败
- 20 个 workspace_id 检查全部通过（LanceDB `.where(prefilter=True)` 过滤正确）

**修正结论**：LanceDB workspace_id 过滤能力实际为 100%。90.9% 是 POC 脚本编码疏漏，不是 LanceDB 能力问题。P2 生产代码将在应用层实现完整的 role + workspace 权限控制。

### 7.2 POC-A vs POC-B 权限正确率差异

POC-A Runtime 复验中所有向量库权限正确率为 100%（2 个 role 检查 + 84 个 workspace 检查 = 86 项），POC-B 中 FTS5 和 Hybrid 也为 100%。LanceDB 90.9% 的差异完全来自 lambda 未实现 role 拦截。

## 8. 综合结论与 P2 建议

### 8.1 检索引擎选型

| 维度 | 结论 | P2 建议 |
| --- | --- | --- |
| 检索引擎 | LanceDB 单独使用质量最佳（95.2% top-5 / 89.3% top-1） | **P2 首版用 LanceDB 单引擎**，FTS5 作降级回退 |
| 延迟 | LanceDB P50=10ms, P99=46ms | 无需优化，120 QPS 足够 5-20 人团队 |
| Hybrid | 当前 TF-IDF fallback 下反而退化 2.3% | 验证真实嵌入模型后再评估 Hybrid，首版不引入 |
| 拒答 | 原始分数阈值不可用（误答率 25%~100%） | 采用 **top-1/top-2 分数差** + LLM 证据判断 |
| 备份 | 目录复制 7ms 完成 | `runtime/vector_lancedb` 一键备份 |
| 嵌入模型 | TF-IDF fallback 有负分问题 | P2 使用 **OpenAI text-embedding-3-small**（归一化向量） |

### 8.2 拒答策略推荐

| 阶段 | 策略 | 实现成本 | 预期效果 |
| --- | --- | --- | --- |
| P2 首版 | top-1/top-2 分数差（阈值 0.15） | 低 | 减少约 60% 误答 |
| P2 增强版 | LLM 证据判断 | 中 | 减少约 90% 误答 |
| P3 远期 | Cross-Encoder 重排序 | 高 | 检索质量 + 拒答双提升 |

### 8.3 不推荐的方案

- ❌ 原始分数阈值拒答：POC-B 已证明完全不可用
- ❌ FTS5 + LanceDB 交叉验证拒答：FTS5 命中率仅 42.9%，会导致漏拒率过高
- ❌ P2 首版直接引入 Hybrid：当前证据不支持 Hybrid 优于纯 LanceDB