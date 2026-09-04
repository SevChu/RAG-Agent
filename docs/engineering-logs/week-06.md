# 第 6 周工程日志：评分与检索算法优化

## 周信息

| 项目 | 内容 |
|---|---|
| 计划周次 | 第 6 周 |
| 实际实施周期 | 2026-08-31 ～ 2026-09-04 |
| 本周主题 | 实验治理、检索与评分候选优化、冻结 test 与 profile 版本化 |
| 当前状态 | 计划日 1～5 已实施并完成用户审核；Week 6 Extra 已完成但待用户后续单独审核 |
| 当前正式版本 | `v1.2.0` |
| 发布状态 | 已获用户最终批准并发布到 GitHub |
| 当前分支与 HEAD | `main` / `58f0c13fb91469928661785623168fff2f0f2d06` |
| 实验设计基线 | `60755dd3ca440b774322a5b0dc713234816ffaeb` |
| 数据原则 | train/validation 用于优化；候选冻结并获批后只允许一次隔离 test |
| 发布原则 | 本地冻结代码、报告和版本号；所有 Git 与 GitHub 写操作另行审批 |

## 历史基线与本周定位

第 5 周已完成 FiQA、RAGTruth 与 RAGBench 三套经典基线，`baseline profile 1.0.0` 随
`v1.1.0` 发布；`v1.1.1` 只修订许可边界。本周不重做经典基线，也不接入生产链路，而是评估：

1. Dense Top-100 直接送入现有 BGE Reranker 是否保留更高召回；
2. relevant → utilized → completeness 两阶段结构是否优于单阶段线性模型；
3. 句级 NLI 特征能否改善 RAGTruth 幻觉 span 定位并守住回答级指标和资源预算。

先建立机器可校验的实验治理，再逐日执行 validation 对照。只有通过稳定性门、经用户批准的最小
候选才可使用一次隔离 test。最终只有 NLI 候选进入 test，且只以 offline/advisory/span-focused
profile 冻结。

## 本周确认约束

1. 每项实验必须登记假设、唯一主要变量、数据/模型/代码 revision、seed、主指标和守门指标；
2. 参数、阈值、特征和停止条件只允许使用 train/validation；
3. 运行入口必须在读取数据前拒绝未获批准的 test split；
4. Git 只保存聚合指标、协议、哈希和限制，不保存原文、样本 ID、gold span 或逐样本预测；
5. 新模型必须先审查来源、许可、revision、哈希、下载范围和显存预算；
6. 下载批准与执行批准分离，下载后必须停下供用户复审；
7. validation 晋级不等于 profile 冻结，数值门通过也不等于生产可用；
8. commit、Tag、push 与 GitHub Release 不包含在计划日实施授权内。

## 本周目标

- 建立 Experiment Registry、split 防污染和统一五维错误切片；
- 完成三项同协议、单变量 validation 实验；
- 以稳定性、时延、显存和负向切片共同决定最小 test 候选；
- 对获批候选执行一次隔离 final test，并按结果条件式冻结 profile；
- 同步版本、技术文档和质量门，形成可供审核的 `v1.2.0` 本地候选。

## 本周验收标准

- Registry 与运行时共同阻止未批准的 test 访问；
- 三项候选均输出主指标、守门指标、稳定性、资源与脱敏切片；
- test-only 派生、运行和缓存均有固定身份与 SHA-256；
- 只有满足预登记门且获用户批准的候选可以新增 profile；
- 后端、前端、静态检查、依赖锁、OpenAPI、隐私与链接检查通过；
- 发布候选保留 precision/recall 权衡和统计不确定性；
- 发布前再次提交用户审核，未获批准前不写入 Git 或 GitHub 远端。

## 计划日 1：实验注册与错误切片

### 基本信息

- 实际日期：2026-08-31
- 状态：已完成并通过用户审核
- 目标版本：`v1.2.0`
- 实验设计基线：`60755dd3ca440b774322a5b0dc713234816ffaeb`
- 交付：[计划日 1 报告](../deliverables/week-06-day-01.md)

### 当日目标

在运行候选算法前，把实验身份、split 边界、审批状态和错误切片固化为机器契约。

### 当日明确不做

- 不运行 Dense、Completeness 或 NLI 候选；
- 不下载模型、调用外部 API、读取 test、修改 profile 或执行 Git/GitHub 写操作。

### 实际完成内容

新增三项登记：`w6-d2-dense-direct-rerank` 与 `w6-d3-two-stage-completeness` 为 ready，
`w6-d4-sentence-nli-spans` 因模型未审批保持 draft。schema 只允许 train/validation；registry
固定 `test_access=forbidden`；运行时 `require_optimization_split("test")` 在读取数据前拒绝。

统一 domain、class、length、evidence count、error type 五维匿名切片。`SliceObservation` 不提供
样本 ID 或文本字段，聚合层只输出 count、mean、minimum、maximum。

### 关键设计决策

- 先冻结协议再运行，避免看到结果后改变指标；
- 在配置与运行时两层阻止 test；
- 错误分析只保留聚合统计，保证报告可审计且不带出样本内容。

### 主要文件

| 文件 | 作用 |
|---|---|
| `backend/app/evaluation/experiment-registry.json` | 候选实验机器注册表 |
| `backend/app/evaluation/experiments.py` | 状态、split 与切片契约 |
| `backend/tests/test_experiments.py` | 注册表、拒绝边界和隐私测试 |

### 自动化验证

- 新增定向测试 6 passed；后端完整回归 271 passed；
- Ruff 与 mypy strict 通过；应用 100 个源文件通过。

### 问题、原因与处理

首轮 pytest 因系统 Temp 不可写在 fixture setup 失败；改用仓库内专用 `--basetemp` 后全量通过，
确认是执行环境权限而非业务回归。

### 用户验收

用户确认无需额外审批并授权进入计划日 2。

### 当前边界与下一计划日入口

Day 2 只用 FiQA dev→validation，正式 test 继续封存。

### Git 记录

未提交、未 Tag、未推送、未创建 Release。

## 计划日 2：Dense Top-100 直接重排

### 基本信息

- 实际日期：2026-09-01
- 状态：已完成并通过用户审核；结论 `provisional`
- 实验 ID：`w6-d2-dense-direct-rerank`
- 数据范围：BEIR FiQA-2018 dev→validation；test 零访问
- 交付：[计划日 2 报告](../deliverables/week-06-day-02.md)

### 当日目标

只改变 Reranker 候选来源，比较等权 BM25+Dense RRF Top-100 与 BGE-M3 Dense Top-100。

### 当日明确不做

- 不修改模型、Top-K、batch、max length、seed、qrels 或指标；
- 不运行 test，不新增 profile，不发布。

### 实际完成内容

| 方法 | nDCG@10 | Recall@100 | MRR@10 | MAP@100 | Wall time |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.23470 | 0.47494 | 0.29391 | 0.19269 | 20.69s |
| BGE-M3 Dense | 0.42503 | 0.75491 | 0.50544 | 0.36953 | 6.64s |
| 等权 RRF | 0.36066 | 0.73930 | 0.44402 | 0.31240 | 0.05s |
| RRF Top-100 → Reranker | 0.45117 | 0.73930 | 0.52790 | 0.39326 | 342.08s |
| Dense Top-100 → Reranker | 0.45232 | 0.75491 | 0.52847 | 0.39381 | 343.15s |

候选相对 RRF 重排 nDCG@10 `+0.001151`、Recall@100 `+0.015613`，平均重排延迟只增加
`2.15 ms/query`，三项数值门通过。但 500 查询、10,000 次 paired bootstrap 的 95% CI 为
`[-0.007196, 0.008637]`；62 胜、411 平、27 负。收益主要来自 multiple-evidence，single-evidence
与 top-10 排序存在轻微退化。

### 关键设计决策

实验无拟合参数，因此主对照只运行 validation；数值门通过但 CI 跨 0，只标记 `provisional`。

### 主要文件

| 文件 | 作用 |
|---|---|
| `backend/scripts/run_retrieval_benchmark.py` | Dense 直接重排与实验绑定 |
| `backend/tests/test_retrieval_benchmark.py` | split、身份、聚合和兼容测试 |

### 自动化与复现验证

- Day 1+2 定向测试 16 passed；后端完整回归 276 passed；
- Ruff、应用 100 源文件 mypy、新 runner strict mypy 通过；
- 五份 run 的行数、哈希、覆盖、聚合字段与忽略边界通过；
- slice SHA-256：`00003d6949b8fc66f96628004e66f35fc8dcc8cefed72d5295f4b1d0d793805b`。

### 问题、原因与处理

主指标提升很小且 CI 跨 0；没有改 seed、改指标或开启 test 寻找正向结果。

### 用户验收

用户完成报告审核，确认主要为 benchmark，无新增审批事项，并授权进入计划日 3。

### 当前边界与下一计划日入口

Day 3 只读 RAGBench train/validation，test Parquet 不哈希、不打开。

### Git 记录

未提交、未 Tag、未推送、未创建 Release。

## 计划日 3：Completeness 两阶段评分

### 基本信息

- 实际日期：2026-09-04
- 状态：已完成并通过用户审核；结论 `deferred`
- 实验 ID：`w6-d3-two-stage-completeness`
- 数据：RAGBench revision `97808f3e5fd16ede40bbff6c2949af8139b2eb7b`
- 数据范围：train 拟合、validation 决策；test 零访问
- 交付：[计划日 3 报告](../deliverables/week-06-day-03.md)

### 当日目标

在相同 27 维 lexical+dense 特征下，只把 Completeness 从 single-stage Ridge 改成 cross-fitted
Relevance/Utilization → Completeness 两阶段 Ridge。

### 当日明确不做

- 不同时更换特征和模型，不运行树模型或额外校准；
- 不复用含 test 的 Week 5 缓存，不生成逐样本 prediction，不修改 profile。

### 实际完成内容

第一阶段对 train 做 5 折交叉拟合；seed 42/43/44 分别运行后取平均。新缓存只绑定
train/validation，处理 73,284 条 train 和 10,292 条 validation。

| 指标 | Single-stage | Two-stage | Delta |
|---|---:|---:|---:|
| Completeness Spearman | 0.409943 | 0.413243 | +0.003300 |
| Completeness Pearson | 0.347820 | 0.352441 | +0.004620 |
| Completeness MAE | 0.221135 | 0.220042 | -0.001093 |
| Completeness RMSE | 0.262538 | 0.262114 | -0.000424 |
| 其他三项 TRACe | 基线 | 相同 | 0 |

形式门通过，但 12-domain bootstrap 95% CI `[-0.009684, 0.024870]`，7 胜 5 负。收益集中在
PubMedQA、DelucionQA，HotpotQA、TechQA 明显退化；逐样本误差为 4,852 改善、5,395 退化。

### 关键设计决策

- cross-fitting 避免中间标签泄漏；
- 其他三项 TRACe 完全不变，保证单变量对照；
- 跨域 CI 跨 0，最终保持 `deferred`。

### 主要文件

| 文件 | 作用 |
|---|---|
| `backend/scripts/run_ragbench_completeness_experiment.py` | 两阶段实验 runner |
| `backend/scripts/run_ragbench_benchmark.py` | split-aware 数据与缓存 |
| `backend/tests/test_ragbench_completeness_experiment.py` | 算法、隔离与复现测试 |

### 自动化与复现验证

- 后端完整回归 281 passed；Ruff 和 mypy strict 通过；
- 缓存命中复跑约 78 秒，指标、bootstrap 与哈希一致；
- dense SHA-256：`0230b67dfed86e45851a23740698b42a3b70332d87bab524f4f3ad0227a1a35e`；
- slice SHA-256：`ae40b75d75550dd0ac0d51f52da9a6b3f42baf862e7beb6ac1c3ab3ae36abc9a`。

### 问题、原因与处理

首次隔离缓存构建 2,610.23 秒、峰值工作集约 4.75 GB；保留可校验缓存把复跑降至约 78 秒。
跨域证据不足，因此没有消耗 test。

### 用户验收

用户审核并批准计划日 3，要求进入 Day 4 审批前置。

### 当前边界与下一计划日入口

Day 4 模型仍为 draft；下载和推理必须分别获批。

### Git 记录

未提交、未 Tag、未推送、未创建 Release。

## 计划日 4：句级 NLI 幻觉定位

### 基本信息

- 实际日期：2026-09-04
- 状态：审批、下载核验与 validation 已完成并通过用户审核
- 实验 ID：`w6-d4-sentence-nli-spans`
- 数据范围：RAGTruth train-only 派生；official test 零访问
- 交付：[审批前置](../deliverables/week-06-day-04-approval.md)、
  [下载与派生核验](../deliverables/week-06-day-04-readiness.md)、
  [实施报告](../deliverables/week-06-day-04.md)

### 当日目标

先完成模型与数据审查，再在相同 Logistic Regression 下只增加三个冻结 NLI 特征，评估 span、
回答级指标和资源开销。

### 当日明确不做

- 未获批前不下载；下载后不自动加载或运行；
- 不读取 official test；不把 validation 晋级当成 profile 或生产授权。

### 实际完成内容

比较 DeBERTa-v3-base/small 与 RoBERTa-large-MNLI 后推荐
`cross-encoder/nli-deberta-v3-base`。用户批准 A/B/C（下载、train-only 派生、注册表修订）并要求
下载后停止；完成 allowlist/revision/hash 核验并再次送审，用户第二次批准后才运行。

固定身份：revision `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`；权重 SHA-256
`d8148c6d49e0a7925134294c56326c71fe0ab1dc390e37355e00c7efbb488afa`；train-only manifest
`e70a891458a68861554da76dc9087b67356abf19b5e22b4ab5842545ff058cbc`。

2,515 sources、15,090 responses、123,184 句按 source+task 划分为 1,507/504/504 个
fit/calibration/validation source。candidate 只在 8 lexical + 1 dense 特征上新增
max contradiction/entailment/neutral。

| 指标 | Baseline | + NLI | Delta |
|---|---:|---:|---:|
| Span char F1 | 0.228140 | 0.243289 | +0.015149 |
| Span precision | 0.159386 | 0.185440 | +0.026054 |
| Span recall | 0.401210 | 0.353597 | -0.047613 |
| Response AUPRC | 0.557403 | 0.572814 | +0.015411 |
| Response Recall | 0.832965 | 0.843267 | +0.010302 |

增量时延 164.74 ms/response；source-cluster bootstrap 95% CI
`[+0.005455, +0.024323]`。数值门和 validation 稳定性门通过，机器决策 `promote`。

长时间 NLI 推理曾因额度达到上限中断；恢复时只从本地缓存/断点继续，未改变模型、数据、阈值、
seed 或协议。缓存命中复跑的指标、阈值、bootstrap 与哈希一致。

### 关键设计决策

- 选 NLI-DeBERTa-v3-base 是因为它在 4 GiB GPU 预算内提供明确的三类 NLI 特征，且可固定公开
  revision 与 safetensors 哈希；
- 只采用 NLISpan，因为证据支持字符定位改善，不支持替换 response 默认分类；
- span recall 下降、历史 lexical response AUPRC 更高，所以只晋级 Day 5。

### 主要文件

| 文件 | 作用 |
|---|---|
| `backend/scripts/prepare_ragtruth_train_only.py` | 安全派生 train-only 数据 |
| `backend/scripts/run_ragtruth_nli_experiment.py` | 冻结 validation 实验 |
| `backend/tests/test_ragtruth_nli_experiment.py` | NLI、资源与复现测试 |
| `THIRD_PARTY_NOTICES.md` | 模型与许可边界 |

### 自动化与复现验证

- Day 4 定向测试 10 passed；后端完整回归 287 passed；
- Ruff、应用 100 源文件及相关工具 strict mypy 通过；
- JSON/NPZ 隐私与文档链接检查通过；
- validation summary SHA-256：`babefd7f3eef7583dc37e4b0c1bfb2319ba688ce7c706ea6e0f38467e32c4143`。

### 问题、原因与处理

RAGTruth train/test 混在同一 JSONL，故用一次性 stream-filter 派生并以 manifest 绑定 runner；
span recall 下降不被隐藏，候选不得替换 lexical response profile。

### 用户验收

用户依次批准 A/B/C、下载后执行，并在断点恢复完成后审核通过 Day 4。

### 当前边界与下一计划日入口

只把冻结 NLI 候选带入 Day 5；official test 仍需独立审批。

### Git 记录

未提交、未 Tag、未推送、未创建 Release。

## 计划日 5：候选冻结、Final Test 与本地 RC

### 基本信息

- 实际日期：2026-09-04
- 状态：已完成并通过用户审核
- 最终机器决策：`accept_advisory_profile`
- Profile Registry：`1.1.0`
- 交付：[审批前置](../deliverables/week-06-day-05-approval.md)、
  [实施报告](../deliverables/week-06-day-05.md)

### 当日目标

综合 Day 2～4 稳定性，选择最小 test 候选；获批后执行一次隔离 test，并只在预登记门通过时冻结
advisory profile 与 `v1.2.0` 本地候选。

### 当日明确不做

- 不让 CI 跨 0 的 Day 2/3 使用 test；
- 不在 test 拟合、校准、改阈值或选模型；
- 不接入生产；不提交、Tag、推送或创建 GitHub Release。

### 审批前置

Day 2 nDCG paired CI 与 Day 3 domain CI 均跨 0；Day 4 是唯一在 validation 通过数值门和稳定性门
的候选。用户先批准 B（一次 test）与 C（条件冻结），要求进一步说明 A 为何只选 NLISpan。
补充其统计证据、span-focused 目标和 response 回退后，用户批准 A，并把 Day 2/3 新增证据移至
Week 6 Extra，不计入 Day 5。

### 实际完成内容

test-only transform 为 `ragtruth-stream-filter-test-v1`，manifest SHA-256
`e6bbcc20cd74cf39386d6caf4315125da05ea2bfa3317127b05adfaa2cd7b2f2`。数据为 450 sources、
2,700 responses、943 hallucinated responses、1,533 spans；0 次拟合、0 次校准、0 个逐样本
prediction、0 次外部 API。final summary SHA-256
`5af902172dc86df3c8346a7be0879b8a79cc7be017656030955e0d1a5760babd`。

| 指标 | Baseline | NLI candidate | Delta | 门 |
|---|---:|---:|---:|---|
| Span char F1 | 0.176380 | 0.184802 | +0.008421 | 通过 |
| Response AUPRC | 0.445373 | 0.460838 | +0.015465 | 通过 |
| Response Recall | 0.826087 | 0.841994 | +0.015907 | 通过 |
| NLI 增量时延 | — | 153.242 ms/response | — | 通过 |

反向证据：span recall `0.347892 → 0.302058`；source-cluster bootstrap 95% CI
`[-0.000657, +0.017168]` 跨 0；历史 lexical coverage response AUPRC `0.504173` 高于候选。

新增 `ragtruth-nli-span-localization`，冻结模型身份、12 维特征、Logistic 参数、阈值和 test 聚合。
其角色严格为 offline/advisory/span-focused，不替换 `ragtruth-lexical-hallucination`，不得作为
production blocking 或在线默认。Day 2 保持 provisional，Day 3 保持 deferred。

### 关键设计决策

- 四门通过只触发 advisory profile，不推导统计显著性或生产适用性；
- test 在 Week 5 已用于经典基线，因此只能称 Week 6 candidate-isolated test；
- Registry 升到 1.1.0，但既有三个 profile 的数值和角色保持不变。

### 主要文件

| 文件 | 作用 |
|---|---|
| `backend/scripts/prepare_ragtruth_test_only.py` | 安全派生 test-only 数据 |
| `backend/scripts/run_ragtruth_nli_final_test.py` | 禁止拟合和重复运行的 final runner |
| `backend/app/evaluation/baseline-profiles.json` | 四个冻结 profile |
| `docs/releases/v1.2.0.md` | 本地候选发布说明 |

### 自动化与复现验证

- Day 5 核心后端完整回归 294 passed；Ruff 全量通过；
- 应用 100 源文件与 Day 5 两脚本 strict mypy 通过；`uv lock --check --offline` 通过；
- 前端 Vitest 10 passed；Vue TypeScript、Oxlint、ESLint 通过；
- Vite build 1,748 modules；OpenAPI 1.2.0、19 paths；
- Git 忽略、聚合隐私、JSON schema、关键哈希与 diff 检查通过；
- profile registry SHA-256：`b0e549b98c36b39d13b58dcec07bbc64f11ecbb1edee8ea02ace948e84aa4f35`。

### 问题、原因与处理

均值改善过门但 bootstrap CI 跨 0、span recall 下降。处理方式是缩小 profile 角色、保留 lexical
默认，并在发布说明保留限制，而不是降低门槛。

### 用户验收

用户审核 Day 5 报告后确认没有问题，并要求重写本周日志、准备发布但发布前再次审核。

### 当前边界与下一入口

本地候选进入发布复审；所有 Git/GitHub 写操作仍未获授权。

### Git 记录

未提交、未 Tag、未推送、未创建 Release。

## Week 6 Extra：Day 2 / Day 3 补充证据

### 基本信息

- 实际日期：2026-09-04
- 技术状态：已完成
- 审核状态：待用户后续单独审核
- 发布状态：不计入 `v1.2.0`，待审核后作为 `v1.2.1` 候选
- 交付：本地 Extra 报告已生成，待审核后纳入 `v1.2.1`

Extra 只复评既有 FiQA validation run 与 RAGBench train/validation 聚合，official test 访问为 0，
也没有改变 Day 5 的 NLI 选择。由于结果尚待用户独立审核，本日志不提前公开 p-value、切片结论、
决策或摘要哈希；完整证据保留在本地，待 `v1.2.1` 审批时再进入发布材料。

## 本周累计成果

1. 建立候选注册、状态、split 防污染和匿名切片契约；
2. 完成三项单变量 validation，并保留稳定性不足和分层退化；
3. 建立 RAGTruth train-only/test-only 安全派生流程；
4. 固定 NLI 模型身份、资源预算、缓存复现和断点恢复；
5. 只让 NLI 消耗一次 final test，冻结一个有限角色 advisory profile；
6. Profile Registry 升至 1.1.0，应用版本同步并发布为 `v1.2.0`；
7. 完成发布说明、技术文档、回归、隐私、依赖锁与 OpenAPI 校验。

## 与原计划的差异

- Day 2/3 虽过形式门，但稳定性 CI 跨 0，没有冻结；
- Day 4 因新增模型和混合 split 风险拆成审批、下载核验、执行三段；
- 下载批准不等于推理授权；NLI 中断后从断点恢复且协议不变；
- Day 5 只选 NLISpan，不让所有 validation 候选进入 test；
- Day 2/3 新增证据按用户要求移到 Extra，且 Extra 仍待单独审核。

## 已知问题与技术债务

1. NLI test span recall 下降约 0.0458，span F1 delta bootstrap CI 跨 0；
2. NLI response AUPRC 低于历史 lexical coverage，不能替换现有 response 参考；
3. FiQA 直接重排均值收益小、paired CI 跨 0，单证据切片有负向风险；
4. 两阶段 Completeness 跨域异质性高，去掉强正向域后可转负；
5. RAGTruth test 在 Week 5 已用于经典基线，本周只是候选隔离，不是全新盲测；
6. 英文公开 Benchmark 不代表中文真实流量或生产阻断精度；
7. scorer 均未接入生产、UI 或 AgentProfile；
8. Extra 尚未通过用户审核，不能进入 `v1.2.0`，后续作为 `v1.2.1` 独立发布。

## v1.2.0 发布记录

### 候选身份

- 发布前正式版本：`v1.1.1`；发布前 HEAD：`58f0c13fb91469928661785623168fff2f0f2d06`；
- backend、frontend、OpenAPI 发布版本：`1.2.0`；
- annotated Tag：`v1.2.0`；
- 远端：`https://github.com/SevChu/RAG-Agent.git`；
- 发布标题：`Agentic v1.2.0`；
- 提交信息：`feat: add governed NLI span evaluation profile`；
- 发布正文：[v1.2.0 Release Notes](../releases/v1.2.0.md)；
- 审核清单：[v1.2.0 GitHub 发布审核清单](../releases/v1.2.0-release-checklist.md)。

### 拟纳入范围

- Day 1～5 的实验治理、runner、测试、profile、版本元数据和报告；
- NLI 第三方声明与 offline/advisory 限制；
- 不包含 Extra 专用脚本、测试和报告；Extra 待单独审核后作为 `v1.2.1` 发布。

### 发布授权与边界

用户于 2026-09-04 完成日志、范围、Release 正文与安全审查复核，并明确授权 commit、annotated
Tag、push 和 GitHub Release。发布只包含上列 Day 1～5 核心范围；没有上传原始数据、缓存、模型
权重或 Extra 专用文件。

## 下一阶段交接

- `v1.2.0` 发布后回读 commit、Tag 与 GitHub Release，确认远端身份一致；
- Extra 保留为独立待审项目，审核后作为 `v1.2.1` 发布；
- 第 7 周 AgentProfile 只能显式、版本化、可回滚地绑定评测 profile；
- NLI 在获得中文/真实流量 validation 前不得升级为 production/default。

## 第 6 周收口结论

计划日 1～5 已完成并经用户审核。本周不是“三项算法全部升级”，而是建立可复现、可拒绝 test
污染的实验治理，并通过负向证据淘汰或延后两个不稳定候选，只冻结一个角色受限的 NLI span
advisory profile。`v1.2.0` 已经用户最终批准并发布；Extra 待审并计划进入 `v1.2.1`。
