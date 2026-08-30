# Agentic v1.1.0 公开 Benchmark 聚合结果

本目录提供 Agentic v1.1.0 的可复现、机器可读 Benchmark **聚合结果**。它用于方法比较和研究
参考，不包含原始数据、问题、上下文、回答、逐条预测、资料空间内容、对话、本地路径、模型权重
或 API Key。

## 文件

| 文件 | 内容 | SHA-256 |
|---|---|---|
| `results.json` | 完整协议、方法参数、聚合指标、分任务/分子集结果、运行资源和产物指纹 | `2615be9ca32717eb28d209f65ec8949a7ba0278f35589274825100d646f71f06` |
| `metrics.csv` | 599 行长表指标，便于 pandas、R、Excel 或数据库导入 | `4ff8bac3afa782af575c0e69d77cebc407c616b66f8ed7d0a8482e2246566ef0` |

原始 TREC run 和逐条 prediction 的 SHA-256 保存在 `results.json` 中作为复现指纹，但对应文件不
随仓库发布。哈希只能证明本地复跑产物的一致性，不能用于恢复原始文本。

## 核心结果

### BEIR FiQA-2018 检索

| 方法 | nDCG@10 | Recall@100 | MRR@10 | MAP@100 |
|---|---:|---:|---:|---:|
| BM25 | 0.2309 | 0.4976 | 0.2871 | 0.1855 |
| BGE-M3 Dense | 0.4126 | **0.7188** | 0.5039 | 0.3538 |
| BM25 + Dense RRF | 0.3523 | 0.6993 | 0.4316 | 0.2959 |
| RRF + BGE Reranker | **0.4299** | 0.6993 | **0.5162** | **0.3682** |

Dense Top-100 是 v1.1.0 的候选召回基线。Reranker 改善候选内排序，但当前 RRF 候选的
Recall@100 低于纯 Dense，且增加约 705 ms/查询。

### RAGTruth 幻觉检测

| 方法 | 回答级 F1 | AUROC | AUPRC | span char F1 |
|---|---:|---:|---:|---:|
| Lexical coverage | **0.6245** | **0.7248** | **0.5042** | 0.1547 |
| BGE-M3 Dense | 0.5571 | 0.5664 | 0.3632 | 0.1325 |
| Logistic fusion | 0.6062 | 0.6800 | 0.4466 | **0.1777** |

Lexical coverage 只作为离线经典参考。其 Precision 约 0.486，不能直接拦截生产回答；句子边界
span 也不能代表精确短语定位。

### RAGBench TRACe 评分

| 方法 | Adherence F1 | AUROC | AUPRC | Rel. Spearman | Util. Spearman | Comp. Spearman |
|---|---:|---:|---:|---:|---:|---:|
| Lexical heuristic | 0.9235 | 0.5796 | 0.8955 | -0.2120 | -0.0160 | 0.1826 |
| Lexical linear | **0.9249** | 0.7171 | 0.9258 | 0.7137 | 0.7806 | 0.3430 |
| Lexical + BGE linear | 0.9247 | **0.7273** | **0.9292** | **0.7577** | **0.8099** | **0.3967** |

RAGBench test 的 adherence 正例率约 85.79%，F1 会受到类别先验影响。`results.json` 同时提供
Precision、Recall、AUROC、AUPRC、Brier、ECE、混淆矩阵和分子集连续指标，避免只比较单一 F1。

## 脱敏与发布边界

导出器采用字段白名单，并由自动测试拒绝样本级字段和本地路径。公开结果包满足：

- 只含 aggregate、task slice 和 subset slice；
- 不含 query、answer、context、document、prompt、row ID 或 source ID；
- 不含 `D:\...`、`C:\...`、用户目录或预测文件名；
- 不含原始数据集、资料空间、对话、数据库或上传内容；
- 不含模型权重，仅记录公开模型名称、revision 和哈希；
- 不含外部 API 调用内容，本轮外部 API/Token 均为 0。

可使用以下命令从本地冻结 summary 重新生成相同结构：

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m scripts.export_public_benchmark_results
.\.venv\Scripts\python.exe -m pytest tests/test_public_benchmark_results.py
```

导出器读取的 summary 位于 Git 忽略目录；它不会读取原始样本文本或逐条 prediction 文件。

## 数据来源、许可与引用

- **BEIR FiQA-2018**：FiQA 官方训练/测试数据限制为非商业使用；本仓库不再分发数据，只发布
  本地研究评测产生的聚合指标。引用 Maia et al. (2018) 与 Thakur et al. (2021)。
- **RAGTruth**：发布仓库为 MIT；其 MS MARCO、Yelp、CNN/DailyMail 和新闻等底层内容仍保留
  原权利。本仓库不上传底层文本。引用 Wu et al. (ACL 2024)。
- **RAGBench**：CC BY 4.0；组成数据集的 notice 仍分别适用。本仓库提供归属、revision 和聚合
  衍生指标，不上传 Parquet 或逐条预测。引用 Friel, Belyi and Sanyal (2024)。

完整来源 URL、revision、许可文字、切分、模型身份、方法参数和限制均在 `results.json` 中。

## 解释限制

- 三套数据均为英文公开 Benchmark，不代表中文真实用户流量；
- FiQA 是金融检索域，不能推出通用领域的绝对质量；
- RAGTruth 当前 span 预测边界较粗；
- RAGBench 类别不平衡，且 Completeness 仍是最弱维度；
- 公开 Benchmark 通过不等于生产上线批准，最终仍需自有中文人工金标集。
