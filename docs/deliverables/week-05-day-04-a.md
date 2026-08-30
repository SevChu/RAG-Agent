# 第 5 周计划日 4-A：RAGTruth 幻觉检测基线

## 当前状态

计划日 4 按用户要求拆分为两次独立验收。本阶段 A 已完成：Agentic 已接入并冻结 RAGTruth，
实现三组完全离线的经典幻觉检测基线，并在官方 test split 上完成回答级检测与字符级定位评估。

本阶段未访问、下载或接入 RAGBench。RAGBench 仍为 candidate，必须在用户验收本报告并再次
明确批准后，才能进入计划日 4-B。

## 数据冻结与安全边界

| 项目 | 固定值 |
|---|---|
| 数据源 | ParticleMedia/RAGTruth |
| 源版本 | c103204b9ce28d6bbad859304bf30de72b8ed8fe |
| 本地目录 | backend/datasets/benchmarks/ragtruth/ |
| source 数 | 2,965 |
| response 数 | 17,790 |
| 官方 train / test | 15,090 / 2,700 responses |
| test 幻觉回答 | 943 / 2,700，正例率 34.93% |
| 细粒度标注 | 全集 14,289 spans；test 1,533 spans |
| 许可边界 | 发布仓库标注 MIT；底层 MS MARCO、Yelp、CNN/DailyMail 和新闻内容保留原权利 |
| 使用策略 | 仅本地研究评测，不再分发，不进入 Git，不与资料空间数据混合 |

冻结文件：

| 文件 | bytes | SHA-256 |
|---|---:|---|
| response.jsonl | 21,458,735 | e4c2e4ac24fff676d8984cc61c35d791612fadc58015335d97dd632375e18073 |
| source_info.jsonl | 15,117,971 | 0dffc26ea9f3c1c3d7c7e8336b56ef1646e3cec876edffcca3c9c624d12d578b |

下载器采用临时目录、HTTP 长度校验、分段续传、JSONL 结构校验、标签文本精确匹配和原子冻结。
第一次与第二次网络响应分别出现截断，均因长度或 JSON 校验失败而被拒绝；只有完整、可解析且
引用一致的数据才写入 frozen manifest。

## 固定实验协议

| 项目 | 固定值 |
|---|---|
| 官方测试集 | 450 sources，2,700 responses；全程不参与训练或阈值选择 |
| 训练 / 开发 | 从官方 train 按 source_id 分组切分，2,011 / 504 sources |
| 回答数 | fit 12,066；dev 3,024；test 2,700 |
| 分层 | 按任务类型保持 Data2txt、QA、Summary 分布 |
| 开发集比例 | 20% |
| 随机种子 | 42 |
| 回答级正例 | 一个回答含至少一个发布标签 span |
| span 指标 | micro character overlap Precision / Recall / F1 |
| 预测边界 | 句子级；命中后标记整句，因此属于保守的经典定位基线 |
| implicit_true | 依照发布标签保留为 unsupported |
| 外部 Judge/API | 0 |
| 新模型下载 | 0 |

三种方法：

1. lexical_coverage：词、内容词、二元词组、数字、专名与否定词的资料覆盖启发式；
2. bge_m3_dense：用项目内已有 BGE-M3 计算句子与资料块的最大语义支持度；
3. logistic_fusion：在 fit split 上以 class-balanced Logistic Regression 融合 8 个词法特征
   与 1 个 dense 特征。

回答级和 span 阈值都只在 dev split 上选择；official test 只评估一次。三个方法共享同一数据、
切分、标签与评估实现，保证算法对比公平。

## 官方 test 正式结果

### 回答级：是否存在幻觉

| 方法 | Precision | Recall | F1 | AUROC | AUPRC | Brier | ECE-10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 词法覆盖 | **0.4858** | 0.8738 | **0.6245** | **0.7248** | **0.5042** | 0.2755 | 0.2825 |
| BGE-M3 Dense | 0.4005 | **0.9152** | 0.5571 | 0.5664 | 0.3632 | **0.2473** | **0.1312** |
| 逻辑回归融合 | 0.4637 | 0.8749 | 0.6062 | 0.6800 | 0.4466 | 0.2781 | 0.2666 |

对应阈值分别为：词法 0.57、Dense 0.39、融合 0.535。若当前目标是优先压低漏检，
BGE-M3 Dense 的 Recall 最高；但它把 79.81% 的回答判为有幻觉，误报明显。综合 F1、AUROC
和 AUPRC，当前最可靠的回答级经典基线是词法覆盖。

### 字符级：幻觉 span 定位

| 方法 | Precision | Recall | F1 |
|---|---:|---:|---:|
| 词法覆盖 | 0.0963 | 0.3923 | 0.1547 |
| BGE-M3 Dense | 0.0828 | 0.3312 | 0.1325 |
| 逻辑回归融合 | **0.1138** | **0.4048** | **0.1777** |

span 阈值分别为 0.66、0.42、0.65。融合模型提供当前最佳字符级 F1，但绝对值仍低，主要原因是
输出以整句为边界，而 RAGTruth 标签往往只覆盖句中的短语。该结果适合作为后续 span scorer
改进的下限基线，不适合直接作为生产拦截器。

### 分任务回答级 F1

| 方法 | Data2txt | QA | Summary |
|---|---:|---:|---:|
| 词法覆盖 | **0.7826** | **0.4416** | **0.4065** |
| BGE-M3 Dense | 0.7785 | 0.3501 | 0.3732 |
| 逻辑回归融合 | 0.7807 | 0.4204 | 0.3810 |

Data2txt 正例率为 64.33%，三种方法都倾向高召回；QA 与 Summary 的正例率较低，误报对 F1
影响更大。词法法在三个任务上均是本轮回答级最优，说明当前 dense 最大相似度不能充分表达
“整句话是否被证据支持”。

## 与论文结果的边界化对照

RAGTruth 论文报告的回答级 F1 参考值包括 GPT-4 提示法 0.634、SelfCheckGPT 0.588 和微调
Llama2-13B 0.787；字符级 F1 包括 GPT-4 提示法 0.283 和微调 Llama2-13B 0.527。

这些数字仅用于定位量级，不能作严格同表排名：论文方法、提示、模型规模和算力均不同。本地词法
回答级 F1 0.6245 接近论文 GPT-4 提示法的 0.634，但字符级定位差距明显；这进一步说明下一步
不应只优化回答级阈值，而应研究短语边界和证据蕴含。

## 耗时、资源与可复现性

| 项目 | 首次构建 | 缓存复跑 |
|---|---:|---:|
| 总耗时 | 614.65 s | 45.40 s |
| dense 特征阶段 | 570.32 s | 0.01 s |
| 峰值工作集 | 4,616,998,912 bytes | 结果文件记录 |
| 峰值 CUDA allocated | 1,244,339,200 bytes | 无需重新编码 |
| 外部 API / token | 0 / 0 | 0 / 0 |

运行环境：Python 3.11.15、PyTorch 2.11.0+cu128、scikit-learn 1.9.0、
NVIDIA RTX 4070 Laptop GPU 8 GiB。BGE-M3 revision 为
84790c1a606f60d06c6932e4ecdd174b466d84ac，权重 SHA-256 为
993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e。

缓存复跑后所有指标保持一致：

- 预测 SHA-256：ab6d0bb03c441887d03bdd750b490efff9eef6f999fb9df40a1ca6bc48dcb373
- dense 缓存 SHA-256：dd4b50f89d23ccdab6a222e8e0d3928580ef7f384672edbe57e923233dcd1cac
- dense 缓存键：b06590f694840db1924f29e2eaea8d5bedb318ebf1a67198761b1413645e6edd

本地 summary、预测和缓存位于
backend/datasets/benchmarks/ragtruth/runs/week05-day04-ragtruth/，整个目录受 Git 忽略规则保护。

运行命令：

    cd backend
    uv run --offline python scripts/run_hallucination_benchmark.py

运行器会先复验 frozen manifest、文件哈希、统计数和标签边界；缓存键与数据或模型身份不一致时
会拒绝旧缓存并重新计算。

## 结论与算法改进入口

1. 当前回答级默认经典基线选择 lexical_coverage：F1、AUROC、AUPRC 均为本轮最高。
2. 若阶段目标是极端重视“少漏掉幻觉”，可把 bge_m3_dense 作为高召回报警器，但必须接受
   1,292 个 false positives 和 79.81% 的预测正例率。
3. logistic_fusion 没有超过词法法，表明线性融合与最大余弦相似度不足；不能因为加入模型特征
   就默认质量更高。
4. span 级最优 F1 仅 0.1777。后续优先方向应为 token/span 分类、NLI/蕴含特征、hard negative、
   分任务校准，以及在 train/dev 上选择的非线性融合。
5. test split 必须继续冻结。任何算法、特征和阈值优化只在 train/dev 进行，最终方案再对 test
   做一次独立确认。
6. RAGTruth 是英文、合成/模型生成回答为主的基准，不能代表中文、多语言、真实用户对话或最终
   自有人工金标集，后续仍需交叉验证。

## 验证证据

- RAGTruth 下载文件长度、SHA-256、JSONL 结构、response/source 引用：通过；
- hallucination span 整数边界与原文精确匹配：通过；
- 专项单元测试：12 passed；
- Ruff：通过；
- Mypy strict：104 个源文件通过；
- 首次正式运行：完成，预测与 summary 已生成；
- 缓存复跑：质量指标和两个 SHA-256 完全一致；
- 数据、缓存、预测、summary：均受 /backend/datasets/ Git 忽略规则保护。

## 计划日 4-B 审批门

阶段 A 现已提交用户验收。阶段 B 仍未开始，RAGBench 仍为 candidate，没有下载、没有访问数据
端点、没有实现其正式 benchmark。只有用户在看完本报告后再次明确批准，才会接入 RAGBench，
并对相关性、利用率、完整性与忠实性评分进行第二次独立验收。

## 后续状态更新（2026-08-30）

用户已认可本阶段 A 的 benchmark 结果，并随后明确批准计划日 4-B。RAGBench 阶段 B 现已完成，
其固定协议、数据质量处理、正式指标和复跑证据见
[RAGBench 综合评分基线](week-05-day-04-b.md)。本节只更新后续状态；上方“审批门”保留的是
阶段 A 提交验收时的真实历史边界。