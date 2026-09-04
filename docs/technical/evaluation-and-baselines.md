# 公开 Benchmark 与冻结基线

本章描述 Agentic 当前的离线评测架构、三套已批准公开 Benchmark、冻结基线配置，以及后续评分
算法实验必须遵守的边界。这里的 profile 是研究复现入口，不是在线回答链路的生产门控。

## 1. 评测分层

Agentic 把评测拆为三个相互独立的层级：

| 层级 | 数据集 | 回答的问题 | 当前默认研究基线 |
|---|---|---|---|
| 检索 | BEIR FiQA-2018 | 相关证据是否进入候选集、排序是否合理？ | BGE-M3 Dense Top-100 |
| 幻觉检测 | RAGTruth | 回答是否包含资料不支持的断言，位置在哪里？ | lexical coverage |
| 综合评分 | RAGBench | 回答的 adherence、relevance、utilization、completeness 如何？ | lexical + BGE-M3 linear |

三套结果不能合并成一个“Agent 总分”。检索遗漏、资料本身证据不足、生成幻觉、错误拒答和评分器
误判必须分别记录，否则无法判断应优化检索器、生成器还是评分器。

## 2. 代码与数据边界

受 Git 管理的评测代码和元数据位于：

```text
backend/app/evaluation/
├─ registry.json                 # 数据集来源、许可、revision 与审批状态
├─ benchmark.py                  # 统一 Benchmark 数据契约与适配器
├─ baseline-profiles.json        # 冻结的推荐研究基线
├─ baseline_profiles.py          # 严格基线配置加载与校验
├─ experiment-registry.json      # v1.2.0 候选实验、变量、revision 与指标
└─ experiments.py                # 实验治理、split 防污染与统一切片聚合

backend/scripts/
├─ run_retrieval_benchmark.py
├─ run_hallucination_benchmark.py
├─ run_ragbench_benchmark.py
├─ run_ragbench_completeness_experiment.py
├─ run_ragtruth_nli_experiment.py
├─ prepare_ragtruth_test_only.py
└─ run_ragtruth_nli_final_test.py
```

公开原始数据、frozen manifest、向量缓存、TREC run、预测和 summary 保存在
`backend/datasets/` 下，并由 Git 忽略。它们不得与 `data/` 中的资料空间、对话、SQLite 或自有测试
数据混合，也不得上传仓库。配置文件只记录可复现身份，不包含 API Key、本地模型绝对路径和样本文本。

## 3. 冻结配置

`baseline-profiles.json` 的 release version 为 `1.1.0`，文件 SHA-256 为
`b0e549b98c36b39d13b58dcec07bbc64f11ecbb1edee8ea02ace948e84aa4f35`。四个 profile 为：

| Profile ID | 关键配置 | 参考结果 | 用途限制 |
|---|---|---|---|
| `fiqa-dense-retrieval` | BGE-M3 exact cosine；Top-K 100；seed 42 | Recall@100 0.7188；nDCG@10 0.4126 | 英文金融域；优先候选召回，不是通用生产默认值 |
| `ragtruth-lexical-hallucination` | response 0.57；span 0.66 | F1 0.6245；AUROC 0.7248；span F1 0.1547 | 误报较高，只能离线分析，不可自动拦截回答 |
| `ragbench-lexical-dense-linear` | 28 features；adherence 0.14；Ridge alpha 100 | AUROC 0.7273；AUPRC 0.9292；三项 Spearman 0.7577/0.8099/0.3967 | 类别不平衡且负例识别弱，不可作为生产门控 |
| `ragtruth-nli-span-localization` | lexical+dense+NLI；response 0.585；span 0.71 | test span F1 0.1848；delta +0.0084；AUPRC 0.4608 | advisory only；span recall 下降且 bootstrap CI 跨 0；不替换 lexical profile |

加载器会拒绝未知字段、重复或缺失 profile、版本不一致、非有限指标和不完整模型身份：

```python
from app.evaluation import load_baseline_profiles

registry = load_baseline_profiles()
retrieval = registry.get("fiqa-dense-retrieval")
print(retrieval.parameters["top_k"])
```

修改参数或算法时必须创建新 profile 版本或明确标记实验候选；不能静默覆盖已冻结的参考数值。

## 4. 运行与复现

在 `backend` 目录执行。下列命令会读取已获批准且已冻结的本地数据，不会读取资料空间或对话：

```powershell
# 数据完整性和注册表测试
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_dataset.py

# 三套正式基线；具体参数以各脚本 --help 和冻结报告为准
.\.venv\Scripts\python.exe -m scripts.run_retrieval_benchmark --help
.\.venv\Scripts\python.exe -m scripts.run_hallucination_benchmark --help
.\.venv\Scripts\python.exe -m scripts.run_ragbench_benchmark --help

# 冻结 profile 契约
.\.venv\Scripts\python.exe -m pytest tests/test_baseline_profiles.py

# 候选实验、test 防污染和切片契约
.\.venv\Scripts\python.exe -m pytest tests/test_experiments.py
```

完整公开 benchmark 可能使用本地 BGE-M3 GPU 推理并持续数十分钟。优先保留已校验缓存，复跑后必须
比较指标、预测或 TREC run 的 SHA-256，而不是只比较终端摘要。

## 5. 实验治理

固定规则是：`test splits are final-report-only; optimization uses train and validation only`。

一个新评分算法进入最终 test 前必须先登记：假设、唯一主要变量、数据 revision、特征版本、随机
种子、主指标、守门指标、时延和停止条件。阈值、特征、域权重、超参数与早停只使用 train 和
validation；候选冻结后才允许一次性生成 test 报告。经典基线和自研方案必须使用相同切分与指标。

`experiment-registry.json` 是第六周候选的机器入口。状态为 ready/running/completed 时，数据、
模型与代码 revision 必须全部冻结；仍待许可或下载审批的模型只能处于 draft。运行代码还必须通过
`require_optimization_split`，因此不能用普通参数把 test 混入优化。

统一错误分析使用 domain、positive/negative class、length、evidence count 和 error type 五类
切片。`SliceObservation` 不保存样本 ID 或文本，只接收 train/validation 的切片元数据与有限
数值指标；聚合输出 count、mean、minimum 和 maximum，避免把逐样本内容带入受 Git 管理报告。

报告不能只给单一 F1。分类任务至少报告 Precision、Recall、F1、AUROC、AUPRC 和校准；连续
任务至少报告 MAE、RMSE、Pearson、Spearman；检索至少报告 Recall、Precision、MRR、MAP、
nDCG。所有任务还应记录 wall time、缓存状态、模型身份、硬件和失败限制。

## 6. 当前结论与下一研究入口

- 检索下一候选：对 Dense Top-100 直接重排，在不降低 Recall@100 的前提下改善 nDCG@10。
- 幻觉候选：句级 DeBERTa NLI 已完成一次冻结 test，四项数值门通过并以 advisory profile
  冻结；但 span recall 下降且 test bootstrap CI 跨 0，不得替换 lexical response reference。
- 综合评分下一候选：先优化 completeness，再验证域感知校准与非线性 28 维特征融合。
- 产品侧下一入口：`AgentProfile`、逐智能体评测套件、训练数据治理、微调任务和 Adapter 注册表。

公开集用于横向可比，自有人工金标集用于中文、拒答、证据充分性和真实资料空间场景。后者按
50 条标注规范试标、200 条 pilot、800 条开发集、1,000 条封存 test、季度 200 条 shadow 的
渐进方案建设，且封存 test 不参与研发调参。

正式结果和决策依据见：

- [FiQA 经典检索基线](../deliverables/week-05-day-03.md)
- [RAGTruth 幻觉检测基线](../deliverables/week-05-day-04-a.md)
- [RAGBench 综合评分基线](../deliverables/week-05-day-04-b.md)
- [计划日 5 统一基线与研究入口](../deliverables/week-05-day-05.md)
- [第六周计划日 2 Dense Top-100 直接重排](../deliverables/week-06-day-02.md)
- [第六周计划日 3 Completeness 两阶段评分](../deliverables/week-06-day-03.md)
- [第六周计划日 4 句级 NLI 幻觉定位](../deliverables/week-06-day-04.md)
- [第六周计划日 5 NLI 最终 Test 与条件冻结](../deliverables/week-06-day-05.md)
