# 第六周计划日 2：Dense Top-100 直接重排

## 状态

- 完成日期：2026-09-01
- 实验 ID：`w6-d2-dense-direct-rerank`
- 目标版本：`v1.2.0`
- 数据：BEIR FiQA-2018 frozen archive
- Split：dev 映射为 validation；未读取 test
- 结论：通过预登记 validation 守门，保留为 Day 5 候选；不提前冻结为默认

## 实验边界

唯一主要变量为 Reranker 的候选来源：

```text
baseline: 等权 BM25 + Dense RRF Top-100
candidate: BGE-M3 Dense Top-100
```

两组共同使用 BGE Reranker v2 M3、Top-K 100、batch size 4、max length 512、seed 42 和同一
RTX 4070 Laptop GPU。没有修改模型、阈值、查询、qrels 或排序指标。

注册实验只校验 corpus、queries 和 dev qrels；train/test qrels 连哈希也不读取。因为本实验没有
需要拟合的参数，额外运行 5,500 条 train 查询不会产生调参信息，因此主对照只运行 500 条
validation 查询。

## Validation 结果

| 方法 | nDCG@10 | Recall@100 | MRR@10 | MAP@100 | Wall time |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.23470 | 0.47494 | 0.29391 | 0.19269 | 20.69s |
| BGE-M3 Dense | 0.42503 | 0.75491 | 0.50544 | 0.36953 | 6.64s |
| 等权 RRF | 0.36066 | 0.73930 | 0.44402 | 0.31240 | 0.05s |
| RRF Top-100 → Reranker | 0.45117 | 0.73930 | 0.52790 | 0.39326 | 342.08s |
| Dense Top-100 → Reranker | **0.45232** | **0.75491** | **0.52847** | **0.39381** | 343.15s |

Dense 直接重排相对 RRF 重排：

- nDCG@10：`+0.001151`；
- Recall@100：`+0.015613`，完整保留 Dense 候选召回；
- MRR@10：`+0.000574`；
- MAP@100：`+0.000554`；
- 平均重排延迟：`+2.15ms/query`；
- GPU peak allocated 约 1.19 GB，两组无实质差异。

预登记的三项 validation gate 均通过：主指标提高、Recall@100 不低于 Dense、平均时延回退不
超过 750ms/query。

## 配对稳定性

对 500 条查询的 nDCG@10 差值执行 seed 42、10,000 次 paired bootstrap：

- mean delta：`+0.001151`；
- 95% CI：`[-0.007196, 0.008637]`；
- bootstrap mean > 0：`62.81%`；
- 逐查询：62 胜、411 平、27 负。

置信区间覆盖 0，因此当前证据不能宣称 Dense 直接重排在 nDCG@10 上有稳定、显著优势。它的
主要确定收益是保留更高的 Recall@100，并且没有可见的延迟或显存代价。候选在 Day 2 形式晋级，
但保持 provisional，Day 5 再结合其他候选决定是否冻结。

## 错误切片

FiQA 是单一 finance 域，500 条 query 均落在 short 长度桶。相对 RRF 重排，Dense 直接重排：

- candidate miss：60 → 57；
- 无错误标签：229 → 237；
- multiple-evidence Recall@100：0.69217 → 0.72486；
- single-evidence Recall@100：0.81000 → 0.80000；
- partial-recall Case：160 → 156；
- top-10 ranking miss：83 → 84。

这说明总体召回收益主要来自多证据查询，但单证据和 top-10 排序仍存在轻微退化切片，不能只看
总体均值。

## 产物与隐私边界

本地忽略目录：

`backend/datasets/benchmarks/beir-fiqa-2018/runs/week06-day02/validation/`

其中包含五份 TREC run、原始 summary 和 `slice-summary.json`。五份 run 均为 500 查询 ×
100 行，文件 SHA-256 与 summary 一致。聚合切片报告不含 query ID、query text、document ID
或逐样本预测；原始 run、模型路径和硬件详情不会进入 Git。

最终 `slice-summary.json` SHA-256：
`00003d6949b8fc66f96628004e66f35fc8dcc8cefed72d5295f4b1d0d793805b`。

## 实现

- runner 支持注册约束下的 `dense-rerank`；
- 绑定实验后 test 在读取数据前被拒绝；
- 注册实验只校验允许的 qrels split；
- 聚合报告记录代码文件哈希、run 哈希、切片、守门结果和 paired bootstrap；
- Week 5 未绑定实验的历史 identity 保持兼容。

主要文件：

- `backend/scripts/run_retrieval_benchmark.py`
- `backend/tests/test_retrieval_benchmark.py`
- `backend/app/evaluation/experiment-registry.json`

## 质量门

- Day 1 + Day 2 针对性测试：16 项通过；
- 后端全量测试：276 项通过；
- Ruff 全量通过；
- mypy：100 个源文件通过；新增 runner 另以 `--strict` 通过；
- 五份 run 哈希、500 查询覆盖、聚合字段和文档链接复验通过。

## 下一入口

计划日 3 执行 `w6-d3-two-stage-completeness`：只使用 RAGBench train/validation，先比较
single-stage linear 与 relevant → utilized → completeness 两阶段建模。test 继续封存。
