# 第 5 周工程日志：通用智能体迁移与公开 Benchmark 基线

## 方向调整

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际调整日期 | 2026-08-25 |
| 用户确认 | 改为通用智能体；公开数据逐项审批；研究聚焦微调与评分算法改进 |
| 数据下载 | 未批准，实际下载 0 |
| 外部模型调用 | 0 |
| 数据库迁移 | 无 |
| 兼容策略 | 暂时保留 `Course`、`course_id`、`/courses` 和既有引用协议 |

原计划日 1 已完成的 100 条本地候选数据、评测契约、恢复执行和 token 账本继续保留，但不再作为
唯一 Benchmark。原实施记录归档到 `week-05-evaluation-infrastructure.md`，对应验收说明归档到
`week-05-day-01-evaluation-infrastructure.md`。

## 计划日 1：产品定位与界面语义迁移

### 当日目标与边界

1. 将课程学习产品调整为通用智能体实验平台；
2. 完成用户可见界面的第一阶段语义迁移；
3. 明确资料空间、智能体、评测套件和微调任务的目标模型；
4. 不修改数据库字段、API 路径、向量 payload 和既有本地数据；
5. 不下载任何候选公开数据，不调用外部模型。

### 实际完成

- 品牌调整为 Agentic；
- 主导航调整为“智能体对话”和“资料空间”；
- 资料空间创建、删除、进入、空状态和资料管理文案完成迁移；
- 智能体对话的空间选择、来源范围、结果类型和输入提示完成迁移；
- 快速对话和设置页移除课程专属产品描述；
- README 和第五周计划改为公开 Benchmark 与经典评分器基线；
- 新增通用智能体平台迁移设计决策；
- 原有总结和组卷能力作为资料总结与内容生成模板继续保留。

### 兼容技术债

- `Course`、`course_id`、`/api/courses` 仍是内部协议；
- `[课n]`、`course_only` 等生成与引用协议尚未迁移；
- 尚未建立真实 `AgentProfile` 实体，一个对话仍使用当前固定 Agent；
- 组件和 store 文件名尚未重命名。

这些内容需要在有数据迁移、兼容 API 和回滚测试的独立里程碑中处理，不能通过全局字符串替换完成。

### 验证证据

本计划日完成前运行后端全量测试、Ruff、Mypy，以及前端单元测试、类型检查和生产构建。验证结果
记录在 `week-05-day-01.md`。

### 下一步

等待用户逐项审批 BEIR SciFact、RGB refined、RAGBench、RAGTruth 等候选数据。计划日 2 可以先
实现不联网的注册表和适配器契约，但下载、解压和接入真实数据必须在审批后执行。

## 多模型供应商预留接口

### 调整目标

在不要求用户立即提供全部 API Key 的前提下，将生成模型从单一 DeepSeek 配置扩展为四个独立的
OpenAI-compatible 供应商：DeepSeek、Qwen、Kimi 和 GLM。此次不调用任何真实模型，也不写入
用户密钥。

### 实际完成

- 保留既有 `LLM_*` 变量作为 DeepSeek 兼容配置；
- 新增 Qwen、Kimi、GLM 的独立 Base URL、API Key 和模型白名单变量；
- 后端根据模型白名单解析供应商，并把请求发送到对应地址与 Key；
- DeepSeek 专属 `thinking` 参数不会发送给其他供应商；
- 设置页展示四个供应商的已配置/待配置状态和环境变量名，但不返回密钥；
- 快速对话和智能体对话按供应商分组展示可用模型，未配置供应商的模型不可选择；
- DeepSeek Web Search 与最终生成模型解耦，选择其他供应商时仍使用 DeepSeek 默认搜索模型；
- 无数据库迁移、无模型下载、无外部模型调用。

### 验证

- 后端全量测试：231 passed；
- Ruff：通过；Mypy strict：98 个源文件通过；
- 前端单元测试：10 passed；
- Vue TypeScript 检查：通过；
- Vite 生产构建：通过；
- 本地 `GET /api/llm/config` 返回 4 个供应商，响应未包含任何 `api_key` 字段；
- 浏览器自动视觉验收因本机浏览器连接进程连续中断未完成，未改用其他浏览器自动化替代。

## 计划日 2：公开 Benchmark 契约与 FiQA 选型

### 实际进度

- 对比 SciFact、NFCorpus、FiQA、RGB、RAGBench 和 RAGTruth 的任务目标与规模；
- 首个正式检索集由 SciFact 调整为 FiQA-2018，SciFact 保留为可选冒烟集；
- 新增版本化 Benchmark 注册表和 candidate → approved → downloaded → verified → frozen 状态机；
- 新增统一 corpus、query、reference answer、qrels、response 和细粒度标签契约；
- 新增无第三方数据依赖的 BEIR Adapter；
- 新增只允许下载 approved 数据集的安全下载、校验与冻结清单脚本；
- 新增注册表、格式归一化、引用完整性和压缩包路径穿越测试；
- 数据目录继续受 Git 忽略规则保护。

### 审批与下载状态

FiQA 官方页规定训练和测试数据仅限非商业使用。本项目仅将其用于本地研究评测，不上传仓库，
不并入产品资料。用户于 2026-08-25 明确批准下载 BEIR FiQA 到项目文件夹。
官方压缩包共 17,948,027 bytes，MD5 与 BEIR 公布值一致；归档和逐文件 SHA-256 已写入本地
frozen manifest。注册表状态为 approved，本地数据状态为 frozen；其他候选数据没有被访问。
语料中的 38 条官方空占位文档原样保留，并作为后续基线报告的数据质量限制。

完整选型、下载哈希和 split 统计见 week-05-day-02.md。

### 验证证据

- 新增测试：5 passed；
- Ruff：通过；
- Mypy strict：通过；
- 后端全量测试：236 passed；
- 官方 MD5 与归档 SHA-256：通过；
- 5 个数据文件 SHA-256：通过；
- 57,638 条语料、6,648 条 split 查询与 17,110 条 qrels 引用校验：通过；
- 独立 frozen manifest 复验：通过；
- Git 忽略检查：压缩包、raw 数据和 manifest 均被忽略。

### 下一步

进入计划日 3：先在冻结的 FiQA 完整 corpus 和 qrels 上运行 BM25，再运行 BGE-M3 Dense、融合
检索与 BGE Reranker 基线，并记录 nDCG、Recall、MRR、MAP、延迟和资源占用。

## 计划日 3：FiQA 经典检索基线

### 实际完成

- 新增依赖无关的 Okapi BM25 倒排索引、确定性英文 tokenizer 和 RRF 融合；
- 新增 Precision、Recall、MRR、MAP、nDCG 的统一多 K 评分；
- 新增标准 TREC run 读写和脱离模型的重复评分能力；
- 新增可恢复的 FiQA 运行器，冻结数据、模型、参数、硬件、延迟和资源身份；
- 使用本地 BGE-M3 建立 57,638 × 1,024 的归一化语料向量缓存；
- 将现有 BGE Reranker 抽取出不带课程证据规则的通用 passage 评分接口；
- 完成 BM25、Dense、等权 RRF 和 RRF + Reranker 四组 test split 正式基线；
- 完整复跑重排，并核对四个 run 的独立评分和 SHA-256。

### 核心结果

| 方法 | nDCG@10 | Recall@100 | MRR@10 | MAP@100 |
|---|---:|---:|---:|---:|
| BM25 | 0.2309 | 0.4976 | 0.2871 | 0.1855 |
| BGE-M3 Dense | 0.4126 | **0.7188** | 0.5039 | 0.3538 |
| BM25 + Dense RRF | 0.3523 | 0.6993 | 0.4316 | 0.2959 |
| RRF + BGE Reranker | **0.4299** | 0.6993 | **0.5162** | **0.3682** |

Dense 是当前最高召回基线。等权 RRF 没有改善 Dense，反而降低召回与排序指标；重排修复了
RRF 候选内的顺序，但不能找回候选集合外的相关文档，并增加约 705 ms/查询延迟。

### 可复现性与边界

- FiQA manifest、corpus、query、qrels 哈希在每次运行前校验；
- BGE-M3 与 Reranker revision、权重 SHA-256 和 batch size 写入 summary；
- 每组结果保存为 Top-100 TREC run，四个 run 均完成独立复评分；
- 语料向量缓存 236,085,376 bytes，编码耗时 735.02 s；
- 38 条官方空占位文档保留为零向量；
- 未调用生成模型，未下载新数据或模型，未读取资料空间或对话；
- dataset、cache、run 和 summary 继续受 Git 忽略规则保护；
- 详细协议、资源、哈希和结论见 week-05-day-03.md。

### 验证证据

- 后端全量测试：242 passed；
- Ruff 全量检查：通过；
- Mypy strict：102 个源文件通过；
- 检索与重排定向测试：11 passed；
- 四个 TREC run 的独立复评分与 SHA-256：全部一致；
- 重排完整复跑：指标和 run 哈希与首次运行一致。


### 下一步

用户决定计划日 4 分为两次验收：优先批准 RAGTruth，先完成幻觉检测 benchmark；看到结果后
再决定是否批准 RAGBench。RAGBench 在第二次明确批准前保持 candidate，不访问数据端点。

## 计划日 4-A：RAGTruth 幻觉检测基线

### 实际完成

- 将 RAGTruth 固定到源 revision c103204b9ce28d6bbad859304bf30de72b8ed8fe；
- 新增支持 HTTP 长度校验、Range 续传、临时暂存和原子冻结的安全下载路径；
- 校验 2,965 个 source、17,790 个 response、14,289 个标签 span，以及全部引用和文本边界；
- 保持官方 2,700 条 test response 完全独立，从官方 train 按 source_id 分组切出 20% dev；
- 实现词法覆盖、BGE-M3 Dense 支持度和 Logistic Regression 特征融合三组经典基线；
- 实现回答级分类、分任务分类、校准和 micro character-level span 评分；
- 冻结数据、模型、切分、阈值、硬件、缓存和预测哈希；
- 首次正式运行完成，并使用缓存复跑确认结果可复现。

### 核心结果

| 方法 | 回答级 F1 | AUROC | AUPRC | span char F1 |
|---|---:|---:|---:|---:|
| 词法覆盖 | **0.6245** | **0.7248** | **0.5042** | 0.1547 |
| BGE-M3 Dense | 0.5571 | 0.5664 | 0.3632 | 0.1325 |
| 逻辑回归融合 | 0.6062 | 0.6800 | 0.4466 | **0.1777** |

词法覆盖是当前回答级默认经典基线；BGE-M3 Dense 的 Recall 最高（0.9152），但产生 1,292 个
false positives；融合模型提供最佳 span F1，但整句预测边界使精确定位仍明显不足。

### 可复现性与边界

- 首次总耗时 614.65 s，其中 dense 特征 570.32 s；
- 缓存命中复跑总耗时 45.40 s，dense 读取 0.01 s；
- 预测 SHA-256：ab6d0bb03c441887d03bdd750b490efff9eef6f999fb9df40a1ca6bc48dcb373；
- dense 缓存 SHA-256：dd4b50f89d23ccdab6a222e8e0d3928580ef7f384672edbe57e923233dcd1cac；
- 外部 API、外部 token、新模型下载均为 0；
- 数据、缓存、预测和 summary 均受 Git 忽略，不读取资料空间、对话或自有测试集；
- 完整报告见 [week-05-day-04-a.md](../deliverables/week-05-day-04-a.md)。

### 验证证据

- RAGTruth 下载长度、SHA-256、JSONL、引用和 span 边界校验：通过；
- 专项测试：12 passed；
- Ruff：通过；
- Mypy strict：104 个源文件通过；
- 首次运行与缓存复跑的指标、预测哈希：一致。

### 下一步与审批门

计划日 4-A 交由用户验收。RAGBench 仍为 candidate，未下载、未访问；只有用户看到本次
benchmark 后再次明确批准，才进入计划日 4-B，验证相关性、利用率、完整性与忠实性评分。


## 计划日 4-B：RAGBench 综合评分基线

### 审批与实际进度

用户在认可计划日 4-A 的 RAGTruth benchmark 后，明确批准进入阶段 B。RAGBench 的固定 release
于 2026-08-26 下载并完成首次全量运行；2026-08-30 从断点恢复后，完成缓存复跑、发布 scorer
修正复评、文档和最终质量门。未调用外部 Judge/API，未读取资料空间、对话或自有测试集。

### 实际完成

- 固定官方 revision 97808f3e5fd16ede40bbff6c2949af8139b2eb7b；
- 下载并冻结 12 个子集、36 个 Parquet、451,251,454 bytes；
- 校验官方 95,381 行与 train 73,286、validation 10,293、test 11,802 的精确切分；
- 保留 3 个完全未标注行但排除训练/评测，test 11,802 行全部有标注；
- 识别 39,560 个同问题多响应的重复 source ID 行，保留全部响应并构造稳定行键；
- 显式记录并规范化 71 个 relevance、7 个 utilization gold 上溢值；
- 实现词法启发式、25 维词法线性、28 维词法+BGE-M3 线性三组 TRACe 基线；
- 使用 train 拟合、validation 选择阈值/alpha、test 最终报告；
- 按有效覆盖复评 release 的 TruLens、RAGAS、GPT 预计算分数，排除并记录越界输出；
- 冻结数据、模型、特征、配置、硬件、预测和缓存身份；
- 完成首次 GPU 编码与 cache-hit 复跑，两次预测字节级一致。

### 核心结果

| 方法 | Adherence F1 | AUROC | AUPRC | Rel. Spearman | Util. Spearman | Comp. Spearman |
|---|---:|---:|---:|---:|---:|---:|
| 词法启发式 | 0.9235 | 0.5796 | 0.8955 | -0.2120 | -0.0160 | 0.1826 |
| 词法线性 | **0.9249** | 0.7171 | 0.9258 | 0.7137 | 0.7806 | 0.3430 |
| 词法 + BGE 线性 | 0.9247 | **0.7273** | **0.9292** | **0.7577** | **0.8099** | **0.3967** |

test adherence 正例率为 85.79%，三种方法都趋向判正，因此 F1 不能单独作为质量结论。当前默认
经典基线选择词法+BGE 线性，依据是最佳 AUROC/AUPRC 和三项连续任务的整体表现；它仍只识别
74 个 true negatives，负例识别和校准是下一步重点。

### 可复现性与边界

- 首次总耗时 3,446.55 s，其中 dense 3,338.27 s；
- 缓存命中复跑总耗时 89.08 s，其中 dense 读取 0.065 s；
- 两次 11,802 行 test 预测 SHA-256 均为
  4770b81defccb5019e38ffffd155db10bf751ba5f0ff919d72752cc413bbe04c；
- dense 缓存 SHA-256 为
  66506dd42e127131f5cbda55a99a50622ea9217407913e2ebe6e84c3e4998249；
- 外部 API、外部 token、新模型下载均为 0；
- 原始数据、manifest、缓存、预测和 summary 均受 Git 忽略；
- 完整报告见 [week-05-day-04-b.md](../deliverables/week-05-day-04-b.md)。

### 验证证据

- 固定 revision、逐文件长度、SHA-256、Parquet schema 与切分计数：通过；
- RAGBench 专项测试：16 passed；
- 后端全量测试：259 passed；
- Ruff lint：通过；
- RAGBench 相关文件 Ruff format-check：通过；
- Mypy strict：107 个源文件通过；
- uv lock --check --offline：通过；
- git diff --check：通过；
- 首轮与缓存复跑指标、预测哈希：一致；
- 全仓库 Ruff format-check 仍有 53 个历史文件不符合当前 formatter，本阶段未重排无关代码。

### 下一步与验收门

计划日 4-B 交由用户独立验收。用户认可后进入计划日 5，汇总 FiQA、RAGTruth 与 RAGBench，
冻结推荐默认参数，并形成评分算法优化、轻量 scorer 微调和智能体微调平台的后续研究入口。

## 计划日 5：统一基线报告与后续研究入口

### 实际完成

用户认可计划日 4-B 后进入本阶段。日 5 没有重新调 test 阈值或运行外部模型，而是统一冻结和
解释前三个 benchmark 的研究结论：

- 检索默认研究基线冻结为 FiQA BGE-M3 Dense Top-100，优先保证候选召回；
- 幻觉回答级默认参考冻结为 RAGTruth lexical coverage，仅用于离线分析；
- TRACe 默认研究基线冻结为 RAGBench lexical+BGE 线性模型；
- 新增机器可读 `baseline-profiles.json` 和严格 Pydantic 加载器；
- 统一检索遗漏/噪声、证据不足、拒答、幻觉、评分器误判与跨域失真分类；
- 登记 Dense 直接重排、两阶段 completeness、NLI span 三个 P0 实验；
- 输出 AgentProfile、长上下文/资料空间记忆、训练数据治理、逐智能体微调 UI 与 Adapter Registry
  里程碑；
- 制定 50 → 200 → 800 → 1,000 sealed test → 季度 200 shadow 的自有人工金标集路线。

机器配置版本为 1.0.0，SHA-256 为
`d4874b327c5df503d010792848cd7ad5b6f30a761b41fd31c3cfb1e5e7cefe24`。test 固定为最终报告专用，
后续特征、阈值、模型和域权重只能用 train/validation 优化。

### 验证证据

- 冻结 profile 专项测试：4 passed；
- 后端全量测试：263 passed；
- Ruff：通过；日 5 Python 文件 format-check 通过；
- Mypy strict：108 个源文件通过；
- uv lock 离线检查、git diff 检查、配置哈希复核：通过；
- `backend/datasets/`、本地数据库与上传目录继续被 Git 忽略；
- 未下载新数据、未调用外部 API、未读取资料空间或对话；
- pytest 存在 `.pytest_cache` 无写权限警告，但不影响测试结果。

完整统一结论、成本、限制、晋级规则和后续路线见
[week-05-day-05.md](../deliverables/week-05-day-05.md)，运行契约见
[evaluation-and-baselines.md](../technical/evaluation-and-baselines.md)。

### 状态与下一入口

计划日 5 与第五周成果随 `v1.1.0` 发布。公开仓库加入白名单导出的聚合 Benchmark JSON/CSV，
原始数据、缓存、run 和逐条预测继续留在 Git 忽略目录。后续优先进入评分算法 P0；AgentProfile、
微调平台、长上下文、资料空间记忆与金标集按第 6～11 周路线推进。
