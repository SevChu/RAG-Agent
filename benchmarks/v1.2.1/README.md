# Agentic v1.2.1 Week 6 Extra 聚合结果

本目录公开 Week 6 Extra 的聚合证据与最终决策。它记录了 Day 2 检索候选经补充证据晋级后，
在一次性 FiQA official test 上被拒绝，以及 Day 3 两阶段 Completeness 候选在外层留一领域确认
中仍证据不足的结果。

## 最终结论

| 候选 | 补充证据 | 最终状态 | Profile |
|---|---|---|---|
| Dense Top-100 → BGE Reranker | 未使用 FiQA train queries 通过最小 test 资格门；一次 official test 主门失败 | \`reject\` | 不进入 |
| Two-stage Completeness | RAGBench 外层留一领域四门全部失败 | \`deferred\` | 不进入 |

Day 2 official test 的候选相对基线 nDCG@10 delta 为 \`-0.000510\`，paired bootstrap 95% CI
为 \`[-0.005411, 0.004049]\`。Day 3 外层确认的 macro Spearman delta 为 \`-0.003987\`，95% CI
为 \`[-0.030626, 0.021197]\`。

## 文件

- \`results.json\`：聚合指标、预登记门、决策、限制与 artifact SHA-256；
- \`metrics.csv\`：便于表格工具读取的数值子集。

## 数据边界

这里不包含原始 Benchmark、查询或文档 ID、文本、qrels 内容、逐条预测、模型权重、缓存、本机
路径或用户数据。哈希只用于绑定本地冻结产物，不代表重新分发上游数据。FiQA 仍受非商业研究
使用限制，其他数据和模型仍遵循 \`THIRD_PARTY_NOTICES.md\` 中的上游条款。

这些结果的价值是固定否决证据、避免重复访问 test，并为以后更换假设或取得真正独立数据时提供
对照；它们不是生产质量门，也不会自动进入 AgentProfile。
