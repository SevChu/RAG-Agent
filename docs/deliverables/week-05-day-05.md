# 第 5 周计划日 5：统一基线报告与后续研究入口

## 当前状态

计划日 5 已完成，等待用户验收。计划日 2～4 已获批准并形成三条独立证据链：

- FiQA-2018：经典检索 benchmark；
- RAGTruth：回答级幻觉检测与字符级 span 定位；
- RAGBench：adherence、relevance、utilization、completeness 综合评分。

本计划日不重新读取 test 样本内容、不重新选择 test 阈值，也不调用模型 API。工作内容是汇总已冻结
结果、建立统一错误分类、冻结研究基线版本、提出只使用 train/validation 的算法实验，并明确
AgentProfile、长上下文、资料空间记忆、微调界面和自有人工金标集的后续路线。

## 统一结论

| 任务 | 冻结默认研究基线 | 主要指标 | 当前结论 |
|---|---|---|---|
| 检索 | FiQA BGE-M3 Dense Top-100 | Recall@100 0.7188；nDCG@10 0.4126 | 当前最高证据召回；作为候选生成默认参考 |
| 幻觉回答检测 | RAGTruth lexical coverage | F1 0.6245；AUROC 0.7248；AUPRC 0.5042 | 回答级经典下限；仅离线分析，不作生产阻断 |
| 幻觉 span | RAGTruth lexical coverage | char F1 0.1547 | 句子边界过粗；不具备生产定位精度 |
| TRACe 综合评分 | RAGBench lexical+dense linear | Adherence AUROC 0.7273；AUPRC 0.9292 | 当前整体最优经典 scorer |
| Relevance | 同上 | RMSE 0.1821；Spearman 0.7577 | 已形成可用研究下限 |
| Utilization | 同上 | RMSE 0.1235；Spearman 0.8099 | 当前最强连续评分维度 |
| Completeness | 同上 | RMSE 0.2597；Spearman 0.3967 | 当前最弱连续评分维度，优先优化 |

三条默认基线不是同一产品流水线的三个强制开关。它们分别服务于检索候选质量、回答幻觉研究和
评分器研究。任何基线进入在线回答门控前，都必须先在自有金标数据上验证误报、漏报、拒答和中文
场景，不能直接用公开 test 结果替代产品验收。

## 为什么选择这些默认基线

### 检索：Dense Top-100，而不是等权 RRF 或当前 RRF + Reranker

FiQA 上 BGE-M3 Dense 的 Recall@100 为 0.7188，是四种已测方法最高值。RRF + Reranker 的
nDCG@10 提升到 0.4299，但候选来自等权 RRF，Recall@100 降到 0.6993，同时重排增加约
705 ms/查询。RAG 回答首先受“相关证据是否进入候选集”约束，因此默认研究基线优先冻结 Dense
Top-100。

RRF + Reranker 保留为排序质量参考，不删除、不冒充失败方案。下一轮应验证“Dense Top-100
直接进入 Reranker”，它有机会保留 Dense 召回上限并改善前排排序；该组合尚未正式 benchmark，
不能提前写成默认。

### 幻觉检测：词法覆盖，而不是 Dense 或线性融合

RAGTruth 上 lexical coverage 的回答级 F1、AUROC 和 AUPRC 均为本轮最高。BGE-M3 Dense
Recall 达到 0.9152，但把 79.81% 的回答判为幻觉，产生 1,292 个 false positives；线性融合
也没有超过词法法。词法覆盖因此作为最清晰、最可解释的经典参考。

其 Precision 仅 0.4858，字符级 F1 仅 0.1547，不能作为“拦截回答”或“自动删除句子”的生产规则。
冻结阈值只用于复现实验。

### RAGBench：词法 + BGE 线性

28 维词法+BGE 线性模型相对 25 维词法模型，在 adherence AUROC/AUPRC 和三项连续任务的
RMSE、Spearman 上都有稳定增益。它是当前最适合继续做非线性融合、校准和小模型微调的基线。

RAGBench test 的 adherence 正例率为 85.79%，当前阈值把 99.04% 的回答判为正例，只识别
74 个 true negatives。F1 0.9247 主要受类别先验影响，后续提升目标不能只写“提高 F1”。

## 冻结的机器基线版本

新增受 Git 管理的配置：

- 文件：backend/app/evaluation/baseline-profiles.json
- release version：1.0.0
- SHA-256：d4874b327c5df503d010792848cd7ad5b6f30a761b41fd31c3cfb1e5e7cefe24
- 加载器：backend/app/evaluation/baseline_profiles.py
- test policy：test splits are final-report-only；优化只使用 train / validation。

冻结 profile：

| Profile ID | 方法 | 关键参数 |
|---|---|---|
| fiqa-dense-retrieval | BGE-M3 normalized exact cosine | Top-K 100；batch 8；seed 42 |
| ragtruth-lexical-hallucination | lexical coverage | response 0.57；span 0.66；sentence boundary |
| ragbench-lexical-dense-linear | balanced Logistic / Ridge | 28 features；adherence 0.14；Ridge alpha 100；max 8000 chars |

配置同时记录数据 revision、模型 revision、模型权重/config SHA-256、参考指标、限制和允许用途。
加载器拒绝重复 ID、缺少必需任务、版本不一致、非有限指标、未知字段和不完整模型身份。配置不包含
API Key、模型本地绝对路径、私人数据路径或 test 文本。

这里冻结的是 evaluation baseline 1.0.0，不修改 Agentic 应用版本号，也不宣称三种研究方法已接入
在线回答链路。

## 统一错误分类

| 层级 | 错误类型 | 已有证据 | 当前可测性 | 后续责任指标 |
|---|---|---|---|---|
| 检索 | omission：相关证据未进入 Top-K | Dense Recall@100 0.7188 | FiQA 可测 | Recall@K、漏检 query 比例 |
| 检索 | noise：候选含大量不相关片段 | Dense P@10 0.1127 | FiQA 可测 | Precision@K、nDCG、候选冗余 |
| 排序 | 正确证据进入候选但排名过低 | Reranker 提高 nDCG@10 | 部分可测 | nDCG@10、MRR、Top-6 recall |
| 证据 | evidence insufficiency：资料本身不足 | 公开集未形成统一 answerability 标签 | 当前不可完整测 | Answerability、evidence sufficiency |
| 决策 | 正确拒答 | 当前公开集不覆盖真实 Agent 决策 | 不可测 | Abstention precision / recall |
| 决策 | false refusal：有证据却拒答 | 当前公开集不覆盖 | 不可测 | False-refusal rate |
| 生成 | unsupported claim / hallucination | RAGTruth test 943 个幻觉回答 | 可测 | AUROC、AUPRC、span F1 |
| 生成 | 引用存在但不支持断言 | RAGBench adherence / utilization | 可测 | Adherence、utilization |
| 生成 | 回答遗漏关键证据 | RAGBench completeness 最弱 | 可测 | Completeness RMSE / Spearman |
| 评分 | scorer false positive | RAGTruth lexical：872 FP | 可测 | Precision、specificity、校准 |
| 评分 | scorer false negative | RAGTruth lexical：119 FN | 可测 | Recall、FN 分域分布 |
| 评分 | 类别不平衡造成虚高 F1 | RAGBench 正类率 85.79% | 可测 | AUROC、AUPRC、MCC、balanced accuracy |
| 评分 | 跨域失真 | ExpertQA、TechQA、PubMedQA 较弱 | 可测 | per-domain metrics、worst-group score |

检索失败、证据不足和生成幻觉必须分层记录。检索未召回时，生成器不应承担全部错误；证据充分但
回答仍错误时，才归入生成或评分层。自有数据必须显式标注 answerability 和 evidence sufficiency，
否则拒答准确率无法被公平计算。

## 后续评分算法实验

所有实验先在 train/validation 注册假设、主要变量、主指标和停止条件。test 在候选方案冻结前
保持不可见，不用于挑特征、阈值、域权重或早停。

| 优先级 | 假设 | 唯一主要变化 | validation 主指标 | 守门条件 |
|---|---|---|---|---|
| P0 | Dense 候选直接重排可兼顾召回与排序 | Dense Top-100 → 现有 Reranker | Recall@100、nDCG@10 | Recall 不低于 Dense 基线；延迟单列 |
| P0 | 两阶段 relevant → utilized 建模可改善 completeness | 将 relevance/utilization 先建模，再推导 completeness | Completeness Spearman / RMSE | Relevance、utilization 不退化 |
| P0 | 句子级 NLI/蕴含比余弦支持度更适合幻觉定位 | 增加 entailment / contradiction 特征 | RAGTruth AUPRC、span F1 | 回答 recall 不低于 0.87 |
| P1 | validation 学习的融合权重优于等权 RRF | 只替换固定 RRF 权重 | Recall@100、nDCG@10 | 相同候选预算、相同模型 |
| P1 | 域感知校准可改善 ExpertQA/TechQA | 分域 calibration，不改特征 | worst-domain AUROC、ECE | aggregate 指标不显著下降 |
| P1 | Gradient Boosting 可学习 28 维非线性交互 | 线性模型替换为树模型 | 四项 validation 指标 | 参数量、时延和过拟合单列 |
| P2 | 多任务小型 scorer 微调优于手工融合 | 共享 encoder + 四个 TRACe heads | AUROC + 三项 Spearman | 与经典基线同 split、同输入 |
| P2 | hard negative 可改善 scorer specificity | 只增加 train hard negatives | specificity、MCC、AUPRC | 不使用 test mining |

推荐首先实施三个 P0 实验。它们直接对应当前最清晰的瓶颈：候选召回与排序冲突、completeness
弱、span 定位弱。微调 scorer 放在经典非线性方法之后，确保能区分“模型规模收益”和“算法设计收益”。

## 晋级规则

候选算法只有满足以下条件才可以请求一次最终 test：

1. 数据 revision、train/validation 切分、输入字段和主要指标与 baseline 1.0.0 一致；
2. 实验前记录唯一主要变量，不在同一轮同时改模型、特征、阈值和数据；
3. 至少使用 3 个随机种子或确定性重复运行，报告均值、离散度与资源成本；
4. validation 主指标超过基线，且守门指标不发生实质退化；
5. 输出配置、模型、代码、数据、预测和 run 的哈希；
6. test 只在候选冻结后运行一次；失败后不能继续根据 test 误差迭代；
7. 生产门控还需通过自有中文/真实流量金标集，公开 benchmark 通过不等于上线批准。

## 产品与研究里程碑

### M1：AgentProfile 与多智能体

新增 AgentProfile 领域实体，至少包含名称、系统提示、供应商/模型、资料空间范围、检索 profile、
评分 profile、工具权限、上下文策略和版本。会话绑定 profile revision，而不是只绑定当前全局配置。
第一阶段不做多用户权限，但必须区分“创建新版本”和“覆盖历史版本”。

### M2：动态长上下文与资料空间记忆

将短期消息窗口、检索证据、对话摘要和长期记忆分层。长期记忆只允许写入指定资料空间，写入前
显示来源、目的、保留期和删除入口。不能把快速对话或外部网页默认写入资料空间记忆。

### M3：微调数据治理

建立 TrainingDataset Registry：数据来源、许可、AgentProfile、任务类型、语言、PII 状态、
去重结果、train/validation 哈希和审核状态。公开 benchmark test、最终自有 test、真实私密资料
默认禁止进入训练集。

### M4：逐智能体微调界面

界面建议分为五个步骤：

1. 选择 AgentProfile revision 与训练目标；
2. 选择已审核数据集，展示许可、条数、语言、重复率和 split；
3. 配置 base model、LoRA/QLoRA、rank、alpha、dropout、learning rate、epoch、batch 与 seed；
4. 显示显存/时间估算，启动可取消训练任务；
5. 比较 base / adapter 的 validation 与冻结 benchmark，审核后注册 Adapter。

训练任务状态至少包括 draft、queued、running、evaluating、failed、cancelled、review_required、
approved、rejected。Adapter Registry 保存 base model revision、训练配置、数据哈希、代码版本、
评测结果、作者、创建时间和回滚关系。任何 Adapter 不得训练完成后自动成为默认模型。

### M5：评分算法与微调联合门

每个 AgentProfile 可选择 baseline scorer 或经过批准的 scorer revision。微调 Agent 的验收必须
同时报告回答质量、幻觉、引用、拒答、延迟、显存和 API/训练成本，防止只优化某个单项分数。

## 自有人工金标集建设

### 标签契约

每个 case 至少包含：

- query、语言、领域、任务类型和难度；
- 可用资料快照及 SHA-256；
- relevant document / chunk；
- answerable 与 evidence_sufficient；
- reference answer、required key points 和允许的答案变体；
- expected citation / source；
- 正确拒答条件；
- response-level hallucination；
- unsupported span 与对应证据；
- adherence、relevance、utilization、completeness；
- 生成模型、AgentProfile revision、标注者、复核者和争议记录。

### 分阶段规模

| 阶段 | 建议规模 | 用途 | 是否允许调参 |
|---|---:|---|---|
| 0. 指南校准 | 50 | 编写标签指南、发现歧义 | 不训练；可改指南 |
| 1. Pilot | 200 | 双人标注、错误分类、UI 验证 | 只作开发分析 |
| 2. Development | 800 | scorer 训练/validation、阈值与校准 | 允许，必须固定 split |
| 3. Sealed Gold Test | 1,000 | 最终项目验收与模型晋级 | 禁止 |
| 4. Shadow 增量 | 每季度 200 | 监测分布漂移和新失败模式 | 独立版本，不回填旧 test |

建议覆盖中文为主的资料问答、跨文档综合、表格/数字、长上下文、相似概念干扰、资料不足、
正确拒答、错误拒答、带外部补充和多轮追问。训练/validation/test 应按原始文档或资料来源分组，
避免同一内容的改写问题跨 split。

### 标注质量门

- Pilot 和 sealed test 采用双人独立标注，所有冲突必须仲裁；
- 分类标签报告 Cohen kappa 或 Krippendorff alpha；
- 连续标签报告相关性与绝对误差；
- span 标签报告字符/Token overlap；
- 对问题、资料、答案和近似改写做去重与污染检查；
- 检查版权、许可、PII、密钥、内部标识和可删除性；
- 每个版本生成 manifest、split hash、schema version 和变更日志；
- sealed test 只由评测执行器读取，不进入训练 UI 的可选数据列表。

## 成本、稳定性与限制

| Benchmark | 首次主要成本 | 缓存复跑 | 外部 API / Token |
|---|---:|---:|---:|
| FiQA | 语料向量 735.02 s；236 MB cache | 查询与 run 可复用 cache | 0 / 0 |
| RAGTruth | 614.65 s | 45.40 s | 0 / 0 |
| RAGBench | 3,446.55 s | 89.08 s | 0 / 0 |

已确认预测/run 哈希在复跑中一致。当前结论仍受以下限制：

- 三个公开 benchmark 均不是中文真实用户流量；
- FiQA 是单一金融检索域；
- RAGTruth 句子级定位无法代表精确短语定位；
- RAGBench 高正类率会虚高 F1；
- benchmark runner 是离线研究工具，尚未成为产品 UI；
- 当前机器配置冻结的是研究参考，不是生产 SLA；
- 发布代码由不可变 `v1.1.0` Tag 标识；公开结果包保留数据、模型、配置和本地产物哈希。

## 验证证据

- 冻结 profile 专项测试：4 passed；
- 后端全量回归：263 passed；
- Ruff lint：通过；
- 日 5 Python 文件 Ruff format-check：通过；
- Mypy strict：108 个源文件通过；
- `uv lock --check --offline`：通过；
- `git diff --check`：通过；
- baseline profile SHA-256 复核：与文档冻结值一致；
- `backend/datasets/`、本地数据库和上传目录的 Git 忽略规则：通过；
- 未运行前端回归：日 5 未修改前端代码；
- pytest 仅报告 `.pytest_cache` 无写权限警告，不影响 263 项测试结果。

## 交付物

- 机器配置：backend/app/evaluation/baseline-profiles.json
- 严格加载器：backend/app/evaluation/baseline_profiles.py
- 专项测试：backend/tests/test_baseline_profiles.py
- 技术运行说明：docs/technical/evaluation-and-baselines.md
- 本报告：docs/deliverables/week-05-day-05.md
- 第五周计划与工程日志同步更新。

## GitHub 版本节点

本阶段与第五周其余已完成内容共同随 `v1.1.0` 发布，没有覆盖已发布的 `v1.0.0`。发布包含经过
白名单脱敏的聚合 Benchmark JSON/CSV；原始数据、run、缓存和逐条预测均不进入 GitHub。
## 验收结论

计划日 5 的实施目标已完成：

- 三套经典 benchmark 已汇总；
- 检索遗漏、噪声、证据不足、拒答、幻觉和 scorer 误判已分层；
- 推荐基线和版本化参数已机器冻结；
- 后续算法实验遵守 train/validation 优化、test 一次性确认；
- 多智能体、长上下文、资料空间记忆和逐智能体微调界面已形成里程碑；
- 自有人工金标集已有标签契约、规模、质量门和隔离策略。

建议下一阶段先进入评分算法优化 P0，再建设训练数据治理与微调任务后端，最后实现逐智能体微调
界面。用户也可以选择先建设 AgentProfile 与微调平台；两条路线共享本报告冻结的数据和评测协议。