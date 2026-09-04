# 第六周计划日 5：候选冻结与最终 Test 审批前置

## 当前状态

- 前置审查日期：2026-09-04
- 审批结果：用户于 2026-09-04 批准 A/B/C
- 目标版本：`v1.2.0`
- Day 2～4 validation 已完成并通过用户审核
- 官方 test：本阶段尚未打开、哈希、解析或运行
- Git/Release：未创建提交、Tag、推送或 GitHub Release

本文件用于决定哪些候选有资格消耗一次最终 test。它不是 test 或发布授权。

## 候选晋级矩阵

| 候选 | Validation 主结果 | 稳定性 | 风险 | 推荐 |
|---|---|---|---|---|
| Day 2 Dense Top-100 → Reranker | nDCG@10 `+0.001151`；Recall@100 `+0.015613` | paired bootstrap 95% CI `[-0.007196, +0.008637]` | 主指标收益很小且区间覆盖 0 | 保留 provisional；不打开 FiQA test |
| Day 3 Two-stage Completeness | Spearman `+0.003300`；RMSE `-0.000424` | domain bootstrap 95% CI `[-0.009684, +0.024870]` | 5/12 domain 退化，区间覆盖 0 | 暂缓；不打开 RAGBench test |
| Day 4 Sentence NLI span | span F1 `+0.015149`；response AUPRC `+0.015411`；Recall `+0.010302` | source bootstrap 95% CI `[+0.005455, +0.024323]` | span recall `-0.047613`，历史 lexical response AUPRC 仍更高 | 唯一进入最终 test 的候选 |

推荐只消耗 RAGTruth test 一次访问。Day 2、Day 3 继续保留 validation 研究记录，不因 Week 6
收口而强行冻结，也不使用 test 为弱证据候选“寻找一次翻盘”。

## 关于“封存 Test”的事实边界

FiQA、RAGTruth、RAGBench 官方 test 曾在 Week 5 经典基线阶段使用，聚合结果已经存在，因此这些
公开 test 对项目整体并非从未见过。Week 6 的保护含义是：

- Day 2～4 候选设计、特征、阈值、模型和晋级判断没有读取 Week 5 test prediction；
- Week 6 train/validation 缓存没有复用含 test 的旧缓存；
- 新候选尚未在对应 test 上运行；
- Day 5 只允许对已冻结候选执行一次、不可回头调参的最终评估。

报告中应使用“Week 6 candidate test isolation”，不能夸大为完全未知的盲测。

## 推荐最终 Test 协议

### 数据访问

只对父 revision `c103204b9ce28d6bbad859304bf30de72b8ed8fe` 的 RAGTruth frozen 原始
JSONL 执行一次受控 test-only 派生：

1. 先重新校验两个父文件 SHA-256；
2. train response 在 JSON 解码前丢弃，不进入对象、统计、缓存或输出；
3. 只复制 test response 与其引用 source 到 Git 忽略目录；
4. 冻结父 revision/hash、派生文件 hash、转换代码 hash和聚合 test 计数；
5. 最终 runner 只打开 test-only 派生目录。

该扫描与 Day 4 的 train-only 派生方向相反，会首次为 Week 6 候选解封 test 内容，因此必须单独
批准。不会输出 test 样本 ID、原文、gold span、逐条预测或逐 pair logits。

### 冻结计算身份

最终 test 绑定当前 validation summary SHA-256：

`babefd7f3eef7583dc37e4b0c1bfb2319ba688ce7c706ea6e0f38467e32c4143`

只允许使用其中已冻结的：

- baseline 与 candidate Logistic Regression 系数/截距；
- baseline response/span 阈值 `0.57/0.67`；
- candidate response/span 阈值 `0.585/0.71`；
- lexical/BGE-M3/NLI 特征顺序；
- BGE-M3 与 DeBERTa 固定 revision/hash；
- context chunk 1,200 字符、overlap 120、NLI max length 512、batch 8。

Test 期间禁止重新拟合、校准阈值、选择切片、修改特征、改变 batch 以外的数值行为或根据中间结果
重跑。batch 8 若 OOM 仍只允许降到 4；两者数值协议相同。运行只输出整体、预登记五维切片和
source-cluster bootstrap 聚合。

### 最终判定

正式注册门保持不变：

1. candidate span char F1 高于相同 test 上的 lexical+dense logistic；
2. response AUPRC 不回退；
3. response Recall 不回退；
4. NLI 增量平均时延不超过 250 ms/response。

同时单列 span precision/recall、历史 lexical coverage、三类 task 和五维切片。Span recall 下降不
会被隐藏；即使注册门通过，最终是否接受该 precision/recall 权衡仍由用户审核决定。

## 条件式 Profile 冻结建议

若四项 test 门全部通过：

- 保留现有 `ragtruth-lexical-hallucination` 作为 response-level 默认研究参考；
- 新增 `ragtruth-nli-span-localization`，角色为 offline/advisory/span-focused；
- 禁止 production blocking、在线默认启用和中文质量外推；
- baseline profile registry 从 `1.0.0` 升到 `1.1.0`，现有 profile 数值不变；
- 新 profile 记录模型 revision/hash、派生协议、系数、阈值、test 聚合指标与限制；
- Experiment Registry 把 Day 2/3 标为未冻结的 provisional/deferred 说明，Day 4 标为已完成。

如果任一注册门失败，则不新增 NLI profile、不升级 profile registry，只提交失败报告并停止。

Profile registry 的 `1.1.0` 是评测配置集合版本，不等同于应用版本 `v1.2.0`。

## 应用版本与发布边界

建议 test 通过并经用户审核后，再准备应用 `v1.2.0` release candidate：同步 backend、frontend、
OpenAPI、README、技术文档和 release notes，执行全量后端/前端/隐私/版本一致性检查。

本轮不请求 GitHub 发布授权。即使 A/B/C 获批且 test 通过，也只完成本地代码、profile 和候选文档；
创建提交、Tag、推送和 GitHub Release 必须在最终结果报告后再次得到明确批准。

## 资源与隐私预算

- 不需要下载新数据或模型；
- RAGTruth test 已知聚合规模为 450 sources、2,700 responses；
- 按 train-only 实测吞吐保守估计，Dense + NLI + 聚合约 10～20 分钟；
- GPU 继续使用 RTX 4070 Laptop，NLI 预算 4 GiB，validation 实测约 732.84 MiB；
- test-only 数据、特征缓存和结果位于 `backend/datasets/`，由 Git 忽略；
- tracked 报告只保留聚合指标、hash、协议和限制。

## 本次需要批准的三项

### A. 最小候选选择

批准只让 Day 4 NLI 进入最终 test；Day 2、Day 3 因稳定性证据不足停在 validation，不运行其
官方 test。

### B. 一次 RAGTruth Test 解封

批准按上述边界生成 test-only 派生副本，并使用完全冻结的 validation 系数、阈值、特征和模型
执行一次最终 test；不调参、不写逐条结果。

### C. 条件式本地冻结

批准在且仅在四项 test 门全部通过时，本地新增 advisory NLI span profile、升级 profile registry
到 `1.1.0` 并准备应用 `v1.2.0` release candidate 文档与版本元数据；若失败则只报告并停止。

A/B/C 不包含 Git 提交、Tag、推送或 Release 授权。完成后将再次停下，提交最终 test 与发布候选
报告供用户审核。

## 审批后的范围补充

- Day 5 只执行冻结的 Day 4 NLI Span 候选一次性 RAGTruth test；
- Day 2、Day 3 不在 Day 5 访问 FiQA/RAGBench test；
- Day 2、Day 3 的新增证据与重新评估列入 Week 6 Extra，并继续只使用 train/validation；
- Extra 不得根据本次 RAGTruth test 结果修改 Day 2、Day 3 的候选设计或晋级门槛。
