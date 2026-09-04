# 第六周计划日 3：Completeness 两阶段评分

## 状态

- 完成日期：2026-09-04
- 实验 ID：`w6-d3-two-stage-completeness`
- 目标版本：`v1.2.0`
- 数据：RAGBench frozen revision `97808f3e5fd16ede40bbff6c2949af8139b2eb7b`
- Split：train 拟合、validation 选参与决策；未读取 test Parquet
- 结论：通过预登记 validation 形式门，保留为 Day 5 候选；跨领域证据不足，不冻结为默认

## 实验边界

唯一主要变量为 Completeness 的建模架构：

```text
baseline: 27 维 lexical + BGE-M3 特征 → single-stage Ridge
candidate: 相同 27 维特征
           → 5-fold cross-fitted Relevance / Utilization
           → 5 维中间表示
           → Completeness Ridge
```

中间表示包含预测 Relevance、预测 Utilization、两者最小值、乘积和绝对差。候选与基线共用
BGE-M3、最大文本长度 8,000、Ridge alpha 网格 `0.1/1/10/100` 和相同原始特征。候选只替换
Completeness 分支；Adherence、Relevance、Utilization 分数原样复用基线，避免同时更换第二个
变量。

第一阶段对 train 使用 5 折交叉拟合，避免把同一行标签拟合出的分数直接送入第二阶段。注册的
seed 42、43、44 分别拟合，最终取三者算术平均。三个 seed 都选择 alpha 100，validation
Completeness Spearman 分别为 0.413242、0.413217、0.413273，结果稳定。

## Test 隔离

Week 5 的 `dense-features.npz` 同时包含 train、validation、test，计划日 3 没有复用该缓存。
本次新增 split-aware 数据校验、数据装载和 dense 缓存：

- 只哈希并打开 12 个子集各自的 train/validation，共 24 个 Parquet；
- train 73,284 条、validation 10,292 条已完整标注记录；
- test 文件不哈希、不打开、不解析，runner 中没有可选择 test 的参数；
- 新缓存 key 显式绑定 `("train", "validation")`；
- 单元测试验证数据适配器只收到 train、validation 两次 split 请求。

## Validation 结果

| 指标 | Single-stage linear | Two-stage candidate | Delta |
|---|---:|---:|---:|
| Completeness Spearman | 0.409943 | **0.413243** | **+0.003300** |
| Completeness Pearson | 0.347820 | **0.352441** | +0.004620 |
| Completeness MAE | 0.221135 | **0.220042** | -0.001093 |
| Completeness RMSE | 0.262538 | **0.262114** | **-0.000424** |
| Relevance Spearman | 0.777828 | 0.777828 | 0 |
| Utilization Spearman | 0.825792 | 0.825792 | 0 |
| Adherence AUPRC | 0.940770 | 0.940770 | 0 |

预登记门禁全部通过：Completeness Spearman 提高、RMSE 不提高，其余三维没有超过 0.01 的
回归。候选是小幅改善，不应把 `+0.0033` 描述为显著跃升。

## 跨领域稳定性

| RAGBench 子集 | N | Spearman delta | RMSE delta |
|---|---:|---:|---:|
| covidqa | 267 | +0.00213 | -0.00233 |
| cuad | 510 | +0.00400 | -0.00089 |
| delucionqa | 182 | +0.06448 | +0.00705 |
| emanual | 132 | +0.03384 | -0.00062 |
| expertqa | 203 | -0.00748 | -0.00053 |
| finqa | 1,766 | +0.01173 | -0.00039 |
| hagrid | 322 | -0.01050 | +0.00062 |
| hotpotqa | 424 | -0.04901 | +0.00312 |
| msmarco | 397 | +0.01266 | -0.00266 |
| pubmedqa | 2,449 | +0.05495 | -0.00510 |
| tatqa | 3,336 | -0.00128 | +0.00179 |
| techqa | 304 | -0.02598 | +0.00549 |

以 12 个子集为 cluster、seed 42 执行 10,000 次 bootstrap：

- macro Spearman mean delta：`+0.007462`；
- 95% CI：`[-0.009684, 0.024870]`；
- bootstrap mean > 0：`79.93%`；
- 领域胜负：7 胜、0 平、5 负。

收益集中在 PubMedQA 与 DelucionQA；HotpotQA、TechQA 有明显退化。置信区间覆盖 0，所以当前
不能宣称两阶段架构具有稳定的跨领域优势。

## 五维错误切片

脱敏切片使用 domain、class、response length、evidence count、error type 五个预登记维度。
按逐条 absolute error 比较，候选 4,852 条更好、5,395 条更差、45 条持平；改善样本的平均
绝对误差收益大于退化样本的平均损失，因此总体 MAE 仍下降。

平均 absolute-error improvement：

- completeness < 0.5：`+0.003842`；completeness ≥ 0.5：`+0.000707`；
- long response：`+0.005360`；medium：`+0.000380`；short：`+0.000152`；
- single evidence：`+0.002070`；multiple evidence：`+0.001027`。

说明候选对较低 completeness 和长回答更有帮助，但逐条退化数量仍略多，不能只看平均误差。

## 产物与复现

本地忽略目录：

`backend/datasets/benchmarks/ragbench/runs/week06-day03/validation/`

目录仅包含 train/validation dense 缓存、聚合 `summary.json` 与 `slice-summary.json`，不生成逐条
prediction。聚合文件未发现 ID、问题、回答、文档、gold 或逐条 score 字段。

- dense cache SHA-256：
  `0230b67dfed86e45851a23740698b42a3b70332d87bab524f4f3ad0227a1a35e`；
- slice summary SHA-256：
  `ae40b75d75550dd0ac0d51f52da9a6b3f42baf862e7beb6ac1c3ab3ae36abc9a`；
- experiment runner SHA-256：
  `9b196ecabe46ca2ecd306468ef954e9445101b7413012798a831b46c09bde82c`；
- shared RAGBench runner SHA-256：
  `20440efe9eb9e56b377e560b7f437754e2cb791fddd9ee843d7bfdb391788464`。

首次隔离缓存构建耗时 2,610.23 秒，其中 dense 2,531.99 秒，峰值工作集约 4.75 GB。缓存命中
复跑约 78 秒；总体指标、bootstrap、dense 哈希和 slice 哈希完全一致。没有下载新模型、调用
外部 API 或消耗外部 token。

## 实现与质量门

主要文件：

- `backend/scripts/run_ragbench_completeness_experiment.py`
- `backend/scripts/run_ragbench_benchmark.py`
- `backend/tests/test_ragbench_completeness_experiment.py`
- `backend/tests/test_ragbench_runner.py`
- `backend/app/evaluation/experiment-registry.json`

验证结果：

- 第 3 日定向测试 14 项通过；最终相关测试 8 项通过；
- 后端全量 281 项测试通过；
- Ruff 全量通过；
- mypy 对 100 个应用源文件通过；新 runner `--strict` 通过；
- 缓存命中复跑的指标与聚合哈希一致；
- test、逐条 prediction、外部 API、模型下载、Git 提交和远端写入均为 0。

## 下一入口

计划日 4 是 `w6-d4-sentence-nli-spans`。该实验仍为 draft，句级 NLI 模型的来源、许可、大小、
revision、哈希和显存适配尚未审批；进入下载或实施前必须先向用户提交独立审查。
