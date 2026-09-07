# 第六周 Extra：Day 2 / Day 3 补充证据、确认性验证与最终决策

状态：实施完成；Day 2 最终 `reject`，Day 3 最终 `deferred`，均不进入 profile
目标版本：`v1.2.1`（不属于 `v1.2.0`）

## 范围与结论

- 实际日期：2026-09-04 至 2026-09-07
- 范围：既有稳健性复评、FiQA 未使用 train queries 确认、RAGBench 外层留一领域确认，以及
  一次经审批的 FiQA official test
- FiQA official test 访问：1；RAGBench official test 访问：0
- Day 2 最终决策：`reject`
- Day 3 最终决策：`deferred`
- Extra summary SHA-256：
  `a52865bf7a69cc8bf2132a7aa8188ab6a947e33f5ba313985a611a969cb8700c`
- Extra final decision SHA-256：
  `d3ae9dc0369b91d7278a08ec966a8a9829de66c1324092223ed04041b7b76fb4`

Extra 没有改变 Day 2/3 的候选设计、主指标或晋级门，也没有使用 Day 5 RAGTruth test 结果调整
二者。补充证据先确认 Day 2 具备最小 test 资格，再按用户批准执行一次冻结 test；负向结果直接
触发拒绝，没有调参或重跑。Day 3 的新增证据不是全新独立标注集，因此按预登记门停止。

## Day 2：Dense Top-100 直接重排

复评绑定：

- Day 2 summary SHA-256：
  `c49c06e6e9acc7e791d7b01b69789fb1b38fe860d39f8ec3e90831b770e38df0`
- slice summary SHA-256：
  `00003d6949b8fc66f96628004e66f35fc8dcc8cefed72d5295f4b1d0d793805b`
- FiQA dev qrels SHA-256：
  `03b27e547cd29dc721c3b93ce8ddd70df6b2d0ce954d8ef3659d386e8cd72c11`

新增证据：

| 检查 | 结果 | 解读 |
|---|---:|---|
| 非平局 sign test | 62 胜 / 27 负；`p=0.000266` | 发生排序变化时，候选更常获胜 |
| paired sign-flip | `p=0.787202` | 效应幅度不足以拒绝零均值 |
| leave-one-query-out | 500/500 均值为正；范围 `[0.000414, 0.003158]` | 不是由单一 query 驱动 |
| single-evidence nDCG delta | `-0.004536`；CI `[-0.022694, 0.010441]` | 单证据切片有负向风险 |
| multiple-evidence nDCG delta | `+0.004943`；CI `[-0.002701, 0.011975]` | 主要收益仍来自多证据，但 CI 跨 0 |
| MRR@10 delta | `+0.000574`；CI `[-0.009192, 0.009289]` | 不稳定 |
| MAP@100 delta | `+0.000554`；CI `[-0.007289, 0.007123]` | 不稳定 |

sign test 与 sign-flip 并不矛盾：前者只看 89 个非平局查询的胜负方向，不看幅度；后者保留全部
500 个差值的大小。候选会在少数 query 上更常改善，但负向变化的幅度足以让总体均值证据很弱。
在仅看该轮既有 dev 复评时，注册主指标的 paired bootstrap CI 仍跨 0，因此当时结论保持
`provisional`；后续独立 train-query 确认结果见下文。

## Day 3：两阶段 Completeness

复评绑定 Day 3 summary SHA-256：
`91e0aeeafcb4f3cbc52a3e39c85cd990564b807162cf6dfec8c8be4d96512b88`。

新增证据：

| 检查 | 结果 | 解读 |
|---|---:|---|
| 12-domain macro delta | `+0.007462` | 平均略正 |
| 样本量加权 delta | `+0.013726` | 大域权重下增益更高 |
| domain sign test | 7 胜 / 5 负；`p=0.774414` | 胜负方向不稳定 |
| exact 2¹² sign-flip | `p=0.437012` | 无法确认跨域零均值之外的稳定收益 |
| leave-one-domain-out | 12/12 均值为正；范围 `[0.002278, 0.012596]` | 不由单一域独占驱动 |
| 去掉两个最大正向域 | macro delta `-0.002990` | 收益依赖少数强正向域 |
| 去掉两个最大负向域 | macro delta `+0.016454` | 域异质性较大 |
| 三 seed Spearman range | `0.000056` | 算法随机性低，但不能解决跨域异质性 |

seed 一致只说明训练随机性可控，不能替代跨 domain 稳定性。原 domain bootstrap CI 仍为
`[-0.009684, 0.024870]`，exact 检验也不支持稳定优势，因此结论保持 `deferred`，不打开
RAGBench test。

## 确认性验证与最终决策

确认协议在查看结果前冻结，见 `week-06-extra-confirmation-protocol.md`。train/validation
确认阶段未读取官方 test、未下载新数据、未调用外部 judge，也未写出文本、样本 ID 或逐样本
指标。其后用户于 2026-09-07 单独批准一次 Day 2 FiQA official test；Day 3 test 始终未开放。

### Day 2：未使用 FiQA train queries

- 样本：此前未运行的 5,500 个 train queries、14,166 条 qrels；仍属于 finance domain；
- 基线 nDCG@10：`0.433536`；候选：`0.437847`；delta：`+0.004311`；
- paired bootstrap 95% CI：`[+0.002719, +0.005825]`；positive fraction：`1.0`；
- query 级结果：638 胜 / 4,557 平 / 305 负；
- Recall@100 delta：`+0.030302`；平均延迟 delta：`+196.11 ms`；
- 四个预注册门全部通过。

因此 Day 2 获得 `minimum_test_eligible`，只触发一次性 official test 的审批资格，并不自动
取得 profile 资格。

Day 2 summary SHA-256：
`b3de736e10ba4bf9a6da015fa0f2c9cf3e32d4fa7f3d7e87b8577681d59aa344`；slice summary
SHA-256：`03a0f3795e4adf4ba950d2de546ad862abe8125d98ddbe80fe33942cf7403e92`。

### Day 2：一次性 FiQA official test

用户批准后，冻结 runner 在读取 test 前复核 parent decision、审批文档、dataset manifest、
archive、corpus、queries 与 test qrels 哈希。运行中模型拟合 0 次、阈值校准 0 次、外部 API 0 次、
新模型下载 0 次；结果不佳后没有重跑。

| 指标 | Hybrid Top-100 → Reranker | Dense Top-100 → Reranker | Delta |
|---|---:|---:|---:|
| nDCG@10 | 0.429862 | 0.429352 | -0.000510 |
| Recall@100 | 0.699345 | 0.718779 | +0.019434 |
| MRR@10 | 0.516222 | 0.513520 | -0.002702 |
| MAP@100 | 0.368163 | 0.368598 | +0.000435 |
| 平均时延 | 698.670 ms/query | 674.726 ms/query | -23.945 ms/query |

paired query nDCG@10 的 10,000 次 bootstrap 95% CI 为
`[-0.005411, 0.004049]`，69 胜 / 542 平 / 37 负。均值 `> 0` 与 CI 下界 `> 0` 两项主门
失败；Recall 与时延 guardrail 通过。依照预登记停止规则，最终决策为 `reject`，不进入
offline/advisory 或 production profile。

final-test summary SHA-256：
`06ef176923ad83041b0e195d8b53f24a6585c81da6a5abc45d0845500623029b`。

### Day 3：外层留一领域

- 每次只用其他 11 个领域的 train 行拟合，在留出领域 validation 行评估；
- 12-domain macro Spearman delta：`-0.003987`；95% CI：`[-0.030626, 0.021197]`；
- exact sign-flip：`p=0.790527`；6 胜 / 6 负；
- macro RMSE delta：`+0.002524`；四个预注册门全部失败。

Day 3 最终保持 `deferred`：不运行 RAGBench test、不进入 profile，也不主动补充数据库。
outer-domain summary SHA-256：
`9d6422d515b8b52e5375c115795f805776829a7147ff46b729c23ce96c6d4434`。

## 隐私与后续边界

Extra 输出只包含 count、均值、CI、p-value、哈希与决策，不包含 query/sample ID、文本、文档、
gold 或逐条指标。完整 `reassessment.json` 位于 `backend/datasets/` Git 忽略目录。

pre-test `decision.json` 与 final-test 完整 summary 位于 `backend/datasets/` Git 忽略目录。
公开 `benchmarks/v1.2.1/` 只含重新导出的无路径聚合结果。Day 2 不得重跑 test，Day 3 没有待
运行 test；任何未来外部数据库、人工 gold、judge 模型或新实验假设均需重新提出协议并取得审批。

## 质量门

- Extra focused 16 passed；纳入后端全量后共 310 passed；
- Ruff 全量通过；应用 100 个源文件与 5 个新增脚本 strict mypy 通过；
- `uv lock --check --offline` 通过；前端 Vitest 10 passed，Vue TypeScript、Oxlint、ESLint
  与 1,748 模块 production build 通过；OpenAPI 1.2.1、19 paths；
- 完整 Extra JSON 与 TREC run 被 `/backend/datasets/` 忽略；公开聚合通过禁止字段与本机
  路径扫描；
- 30 个候选文件的密钥、危险扩展名、大文件和新增绝对路径扫描通过；13 个 Markdown 的
  169 个本地链接无断链；
- 用户于 2026-09-07 完成候选审核并正式授权 commit、Tag、push 与 GitHub Release。
