# 第六周 Extra 确认性证据预注册

状态：已冻结，尚未查看确认性结果  
目标版本：`v1.2.1`  
冻结日期：2026-09-06

## 不可变边界

- 不读取 FiQA 或 RAGBench 官方 test；test 仍是单独审批点。
- 不下载新数据、不新增人工 gold、不调用外部 judge。
- 不根据确认结果更换候选、指标、alpha、seed、切片或通过门。
- 输出只保留聚合指标、计数与哈希，不保留文本、样本 ID 或逐样本指标。

## Day 2：FiQA 未使用 train query 确认

- 候选冻结为 Day 2 的 `dense-top-100 -> BGE reranker`；基线冻结为
  `BM25+dense RRF-top-100 -> BGE reranker`。
- 数据仅使用此前未运行的 FiQA `train` qrels（5,500 queries）；与原 dev validation
  查询样本独立，但仍属于相同 finance domain。
- 主指标：paired query `nDCG@10` delta。
- 最小 test 资格门：均值 `> 0` 且预注册 10,000 次 paired bootstrap 95% CI 下界 `> 0`；
  同时 `Recall@100` 不低于 dense，候选相对基线平均延迟回归不超过 750 ms。
- 若任何门失败，结论保持 provisional，不运行官方 test，也不进入 advise profile。

## Day 3：RAGBench 外层留一领域确认

- 12 次外层验证；每次仅以其他 11 个领域的 train 行拟合，在留出领域的 validation 行评估。
- 基线与候选 Ridge alpha 均冻结为 `100`；候选内部 5-fold seed 冻结为 `42/43/44`，
  不再使用留出 validation 选择超参数。
- 主指标：12 个领域的 macro completeness Spearman delta。
- 最小 test 资格门全部必须通过：macro delta `> 0`、领域 bootstrap 95% CI 下界 `> 0`、
  exact paired sign-flip `p < 0.05`、macro RMSE delta `<= 0`。
- 该设计保证拟合时不见留出领域，但候选架构曾依据原实验观察过这 12 个领域，因此它是
  较强的跨域稳健性证据，不等同于全新外部数据集。

## 停止规则

任一结果不满足上述门或证据解释仍不确定时，停止在 Extra 证据报告：先向用户说明，未经审批
不得新增数据库、下载数据、制作人工 gold、运行官方 test 或发布 `v1.2.1`。

## Day 2 官方 test 审批与最终门

审批结果：用户于 2026-09-07 批准一次性运行 Day 2 FiQA 官方 test，并同意以下最终门。

- 只运行已冻结的 Day 2 基线与 dense-direct rerank 候选；不调参、不拟合、不重训、不因结果
  不佳重跑。
- 主门：paired query nDCG@10 delta `> 0`，且预注册 10,000 次 paired bootstrap 95% CI
  下界 `> 0`。
- Guardrails：候选 Recall@100 不低于 dense；候选相对基线平均延迟回归不超过 750 ms。
- 只有全部门通过才可标记 `accept_advisory_profile`；任一失败或 CI 跨 0 均标记 `reject`，
  不进入 advise profile。
- test 原始 run 只保留在 Git 忽略的本地 benchmark 目录；公开产物只允许聚合指标与哈希。
