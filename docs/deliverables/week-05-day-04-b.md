# 第 5 周计划日 4-B：RAGBench 综合评分基线

## 当前状态

计划日 4-B 已完成，等待用户独立验收。Agentic 已下载、校验并冻结 RAGBench 的固定版本，
在 12 个官方子集的完整 train / validation / test 上运行三组完全离线的经典 TRACe 评分基线，
同时复评 release 中已有的 TruLens、RAGAS 与 GPT 预计算分数。

本阶段没有读取资料空间、历史对话、自有候选测试集或任何私人数据；没有调用外部 Judge/API，
没有下载新模型。原始数据、manifest、特征缓存、预测与 summary 均位于 Git 忽略目录内。

## 官方来源、版本与许可

| 项目 | 固定值 |
|---|---|
| 数据源 | Galileo Technologies / RAGBench |
| 官方数据卡 | https://huggingface.co/datasets/galileo-ai/ragbench |
| 论文 | https://arxiv.org/abs/2407.11005 |
| 固定 revision | 97808f3e5fd16ede40bbff6c2949af8139b2eb7b |
| 许可 | CC BY 4.0 |
| 子集 | covidqa、cuad、delucionqa、emanual、expertqa、finqa、hagrid、hotpotqa、msmarco、pubmedqa、tatqa、techqa |
| 文件 | 36 个 Parquet，451,251,454 bytes |
| 本地目录 | backend/datasets/benchmarks/ragbench/ |
| 使用策略 | 仅本地研究评测；不再分发；不进入 Git；不与产品资料数据混合 |

下载器固定到 40 位提交 revision，对每个文件执行 HTTP 长度校验、可恢复暂存、Parquet schema
解析与 SHA-256 建档。36 个文件全部到齐并通过全量解析后，暂存目录才原子冻结为 raw 数据。
后续运行会先复验文件大小与 SHA-256，任何数据变化都会使 benchmark 拒绝继续。

## 数据规模与质量处理

| 切分 | 官方行数 | 完整标注行 | adherence 正例 |
|---|---:|---:|---:|
| train | 73,286 | 73,284 | 63,582 |
| validation | 10,293 | 10,292 | 8,823 |
| test | 11,802 | 11,802 | 10,125 |
| 合计 | 95,381 | 95,378 | 82,530 |

全量校验发现并显式处理以下 release 特征：

1. 3 行四项 gold 标签、annotating model、dataset name 和句子键列表同时为空。原始行和哈希保留，
   但这些行不进入训练、调参或指标计算；官方 test 没有缺失标签。
2. 39,560 个额外重复 source ID 行并非完全重复内容，而是同一问题对应不同生成响应。不能按 ID
   去重。预测使用“子集 / 切分 / 文件内行号 / 官方 ID”作为稳定唯一键，全部响应都保留。
3. 官方 continuous gold 中 71 个 relevance、7 个 utilization 超过声明的 [0,1] 区间，
   completeness 无异常。适配器保留原值；进入训练和指标计算时按预声明规则裁剪到 [0,1]，
   裁剪计数写入 summary。
4. release 预计算 scorer 中，TruLens groundedness 有 1 个 -1，GPT context relevance 有 11 个
   >1，GPT-3.5 utilization 有 23 个 >1。这些值作为无效覆盖排除，不裁剪后冒充原算法成绩；
   每个 scorer 的有效 test 覆盖和排除数量单独报告。
5. 官方 ID、文本、documents 和已标注行的标签结构均通过完整性校验；空 metadata 不能改变可信
   子集身份，子集与切分始终由固定文件路径决定。

## 固定实验协议

| 项目 | 固定值 |
|---|---|
| train | 仅拟合 Logistic Regression / Ridge |
| validation | 仅选择 adherence 阈值和 Ridge alpha |
| test | 仅最终报告；11,802 行全部有标注 |
| 随机种子 | 42 |
| continuous gold | relevance、utilization、completeness |
| binary gold | adherence |
| 文本边界 | 每个 question / context / response 最多 8,000 chars |
| 本地 embedding | BAAI/bge-m3，本地 revision 84790c1a606f60d06c6932e4ecdd174b466d84ac |
| 外部 Judge/API | 0 |
| 外部 token | 0 |
| 新模型下载 | 0 |

三组自建方法：

1. lexical_heuristic：直接组合回答—资料、问题—资料、回答—问题的 token、内容词、bigram、
   数字、专名、否定与长度特征；
2. lexical_linear：25 个词法特征输入 StandardScaler + class-balanced Logistic Regression
   与 Ridge；
3. lexical_dense_linear：在上述 25 个特征上加入 question-context、response-context、
   question-response 三个 BGE-M3 余弦相似度，共 28 个特征。

Ridge alpha 只在 validation 的 {0.1, 1, 10, 100} 中按 RMSE 选择，三项任务和两种线性方法均
选择 100。adherence 阈值只按 validation F1 选择。release scorer 若没有任何 validation 值，
binary 指标采用预声明固定阈值 0.5，同时保留 AUROC/AUPRC 等阈值无关指标；continuous scorer
不需要阈值，直接在有效 test 覆盖上评分。

## 官方 test：adherence 结果

test 正例率为 85.79%，因此“几乎全部判为正例”也能得到约 0.92 的 F1。F1 必须与 AUROC、
AUPRC、混淆矩阵和校准指标一起解释。

| 方法 | Precision | Recall | F1 | AUROC | AUPRC | Brier | ECE-10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 词法启发式 | 0.8580 | **0.9999** | 0.9235 | 0.5796 | 0.8955 | **0.1560** | **0.1495** |
| 词法线性 | 0.8628 | 0.9965 | **0.9249** | 0.7171 | 0.9258 | 0.2088 | 0.3013 |
| 词法 + BGE 线性 | **0.8629** | 0.9961 | 0.9247 | **0.7273** | **0.9292** | 0.2058 | 0.2968 |

三种方法对应 validation 阈值为 0.185、0.145、0.140。词法+BGE 线性获得最佳 AUROC/AUPRC，
但在固定阈值下仍产生 1,603 个 false positives，只识别出 74 个 true negatives。词法启发式
校准数值较好主要因为其分数接近数据先验，判别能力仍弱，不能据此认定它是更好的幻觉检测器。

## 官方 test：连续 TRACe 结果

每格为 RMSE / Spearman；RMSE 越低越好，Spearman 越高越好。

| 方法 | Relevance | Utilization | Completeness |
|---|---:|---:|---:|
| 词法启发式 | 0.4902 / -0.2120 | 0.5181 / -0.0160 | 0.4287 / 0.1826 |
| 词法线性 | 0.1895 / 0.7137 | 0.1291 / 0.7806 | 0.2637 / 0.3430 |
| 词法 + BGE 线性 | **0.1821 / 0.7577** | **0.1235 / 0.8099** | **0.2597 / 0.3967** |

BGE 三个稠密特征对所有连续任务都有稳定增益。Relevance 和 utilization 已形成可用的经典
下限基线；completeness 的 Spearman 仅 0.3967，仍是最明显的评分算法改进入口。

## release 预计算 scorer 对照

不同 scorer 的 test 覆盖并不相同，不能把下表当作同样本严格排名。

### Adherence

| Scorer | 有效 test | 阈值来源 | F1 | AUROC | AUPRC |
|---|---:|---|---:|---:|---:|
| TruLens groundedness | 11,718 | fixed 0.5；排除 1 个 -1 | 0.7643 | 0.5810 | 0.8982 |
| RAGAS faithfulness | 11,612 | fixed 0.5 | 0.9136 | 0.5534 | 0.8720 |
| GPT-3 adherence | 11,702 | validation F1，阈值 0.0 | 0.9231 | 0.5583 | 0.8717 |
| 本地词法 + BGE 线性 | 11,802 | validation F1 | **0.9247** | **0.7273** | **0.9292** |

GPT-3 scorer 的 validation 最优阈值为 0，最终把所有有效 test 行都判为正例；它的 F1
主要反映正类占比，不代表具备有效负例识别能力。

### Relevance / Utilization

| Scorer | 目标 | 有效 test | RMSE | Spearman |
|---|---|---:|---:|---:|
| TruLens context relevance | relevance | 9,970 | 0.6695 | 0.0501 |
| RAGAS context relevance | relevance | 11,728 | 0.2352 | 0.4840 |
| GPT-3 context relevance | relevance | 11,691；排除 11 个 >1 | 0.1864 | 0.7248 |
| 本地词法 + BGE 线性 | relevance | 11,802 | **0.1821** | **0.7577** |
| GPT-3.5 utilization | utilization | 11,679；排除 23 个 >1 | 0.1264 | **0.8197** |
| 本地词法 + BGE 线性 | utilization | 11,802 | **0.1235** | 0.8099 |

本地线性基线在完整覆盖上获得更低 relevance/utilization RMSE；utilization 的 rank correlation
略低于 GPT-3.5 scorer。release 没有 completeness 的对应预计算 scorer。

## 12 子集结果

下表使用当前综合最优的 lexical_dense_linear。连续列为 RMSE。

| 子集 | test 数 | Adherence F1 | Rel. | Util. | Comp. |
|---|---:|---:|---:|---:|---:|
| covidqa | 246 | 0.9139 | 0.1578 | 0.1088 | 0.2899 |
| cuad | 510 | 0.9602 | 0.2355 | 0.0998 | 0.3257 |
| delucionqa | 184 | 0.9663 | 0.1700 | 0.1155 | 0.2549 |
| emanual | 132 | 0.9516 | 0.2434 | 0.1640 | 0.2525 |
| expertqa | 203 | 0.6500 | 0.1949 | 0.1578 | 0.3394 |
| finqa | 2,294 | 0.9554 | **0.0872** | 0.0617 | 0.2179 |
| hagrid | 1,318 | 0.9129 | 0.2349 | 0.1632 | 0.2916 |
| hotpotqa | 390 | 0.9572 | 0.1182 | 0.0820 | 0.2809 |
| msmarco | 423 | 0.9291 | 0.1933 | 0.1055 | 0.2622 |
| pubmedqa | 2,450 | 0.8244 | 0.2195 | 0.1552 | 0.2591 |
| tatqa | 3,338 | **0.9823** | 0.1757 | 0.1222 | 0.2382 |
| techqa | 314 | 0.7619 | 0.1057 | **0.0539** | 0.3699 |

ExpertQA、TechQA 和 PubMedQA 是 adherence 的主要薄弱域；TechQA completeness RMSE 最高，
ExpertQA completeness 也明显偏弱。后续应在 train/validation 上进行分域误差分析和校准，
不能根据 test 子集表现反复改阈值。

## 耗时、资源与可复现性

| 项目 | 首次构建 | 缓存复跑 |
|---|---:|---:|
| 总耗时 | 3,446.55 s | 89.08 s |
| dense 阶段 | 3,338.27 s | 0.065 s |
| 峰值工作集 | 4,758,663,168 bytes | 1,388,122,112 bytes |
| GPU | RTX 4070 Laptop 8 GiB | cache hit，未重新编码 |
| 外部 API / token / 新模型下载 | 0 / 0 / 0 | 0 / 0 / 0 |

固定身份：

- BGE-M3 权重 SHA-256：993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e
- dense cache SHA-256：66506dd42e127131f5cbda55a99a50622ea9217407913e2ebe6e84c3e4998249
- dense cache key：406429d7a5dafe3ad530b4892f44c6c406ace8d2cc0e5d2b5951b1da906fc492
- 两次 test prediction SHA-256：
  4770b81defccb5019e38ffffd155db10bf751ba5f0ff919d72752cc413bbe04c
- 两次预测文件：均为 11,802 行，字节级哈希完全一致。

本地运行命令：

    cd backend
    .venv\Scripts\python.exe scripts\run_ragbench_benchmark.py --device cuda

## 结论与下一步算法入口

1. 当前 RAGBench 默认经典基线选择 lexical_dense_linear。它在完整 test 上获得最佳 adherence
   AUROC/AUPRC，并在 relevance、utilization、completeness 的 RMSE 与 Spearman 上全面超过
   词法线性基线。
2. 不把 adherence F1 0.9247 当作“已解决”。85.79% 的正类率和 99.04% 的预测正例率说明
   负例识别仍很差；下一轮应优先优化 balanced accuracy、MCC、负类 recall、PR 曲线和校准。
3. Completeness 是连续任务最弱项。可从句子级 evidence alignment、relevant/utilized 两阶段
   建模、NLI/蕴含特征和非线性交互开始，而不是继续增加简单余弦特征。
4. ExpertQA、TechQA、PubMedQA 需要分域 error taxonomy 与 validation-only 校准；可以研究
   分域 reweighting、hard negatives 和 domain-aware calibration。
5. 当前 28 维线性模型适合作为可解释下限。下一阶段可在相同 frozen protocol 上比较
   Gradient Boosting、轻量 cross-encoder、RoBERTa scorer 或多任务小模型微调；所有超参数必须
   只使用 train/validation。
6. test split 继续冻结。算法迭代期间只查看 train/validation；最终候选模型再做一次独立 test
   确认，避免 test 驱动优化。
7. RAGBench 以英文和发布生成回答为主，不能替代未来中文、多语言、真实用户交互和自有人工
   金标数据集；它是公开 benchmark 基线，不是最终验收集。

## 验证证据

- 固定 revision、36 个 Parquet、451,251,454 bytes、逐文件 SHA-256：通过；
- 95,381 行 schema、文本、documents、标签完整性与 split 精确计数：通过；
- 官方 test 11,802 行全部有完整标签，未用于拟合或阈值选择；
- RAGBench 专项测试：16 passed；
- 后端全量测试：259 passed；
- Ruff lint：通过；
- RAGBench 相关文件 Ruff format-check：通过；
- Mypy strict：107 个源文件通过；
- uv lock --check --offline：通过；
- git diff --check：通过；
- 首轮正式运行与缓存复跑：指标一致，预测 SHA-256 完全一致；
- 全仓库 Ruff format-check：53 个既有文件不符合当前 formatter，本阶段未大面积重排历史文件；
- 数据、manifest、缓存、预测与 summary：均受 /backend/datasets/ Git 忽略规则保护；
- 本阶段未 commit、未 push。

## 验收门

计划日 4-B 已提交用户验收。用户认可本报告后，计划日 4 的两阶段工作完成，可进入计划日 5：
汇总 FiQA 检索、RAGTruth 幻觉检测与 RAGBench TRACe 评分基线，冻结推荐默认参数，并形成
后续评分算法优化与微调平台的研究入口。

## 后续状态更新（2026-08-30）

用户已认可本阶段 benchmark 结果，并批准进入计划日 5。阶段 B 的冻结结果不再用于后续调参；
计划日 5 仅汇总结果、冻结研究 profile 和规划后续实验。
