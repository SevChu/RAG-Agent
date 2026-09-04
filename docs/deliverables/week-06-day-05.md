# 第六周计划日 5：NLI 最终 Test 与 v1.2.0 本地候选冻结

## 结论

- 实际日期：2026-09-04
- 用户审批：A/B/C 均已批准
- 最终决策：`accept_advisory_profile`
- 应用状态：本地 `v1.2.0` release candidate，尚未提交、Tag、推送或发布
- Profile Registry：`1.1.0`

Day 4 的冻结 NLI Span 候选在唯一一次 RAGTruth test 上通过四项预登记数值门，因此新增
`ragtruth-nli-span-localization`。该 profile 只用于 offline/advisory/span-focused 研究分析，
不替换 `ragtruth-lexical-hallucination`，也不得用于生产回答拦截。

## Test 隔离与冻结身份

本次遵守 Week 6 candidate test isolation。RAGTruth test 在 Week 5 经典基线中已有历史聚合结果，
所以它不是项目从未见过的盲测；但 Week 6 候选在冻结前没有读取或复用 test prediction。

- 父 revision：`c103204b9ce28d6bbad859304bf30de72b8ed8fe`
- test-only transform：`ragtruth-stream-filter-test-v1`
- test-only manifest SHA-256：
  `e6bbcc20cd74cf39386d6caf4315125da05ea2bfa3317127b05adfaa2cd7b2f2`
- 冻结 validation summary SHA-256：
  `babefd7f3eef7583dc37e4b0c1bfb2319ba688ce7c706ea6e0f38467e32c4143`
- 最终 test summary SHA-256：
  `5af902172dc86df3c8346a7be0879b8a79cc7be017656030955e0d1a5760babd`
- 数据规模：450 sources、2,700 responses、943 hallucinated responses、1,533 spans
- 运行约束：0 次模型拟合、0 次阈值校准、0 个逐样本 prediction artifact、0 次外部 API

派生器先重新校验两个父文件哈希；train response 在 JSON 解码前被跳过。最终 runner 只打开
test-only 目录，且必须显式接收派生 manifest 哈希。已经存在完整 summary 时 runner 拒绝重复运行。

## 最终聚合结果

| 指标 | lexical+dense baseline | + sentence NLI candidate | Delta | 门 |
|---|---:|---:|---:|---|
| Span char F1 | 0.176380 | 0.184802 | +0.008421 | 通过 |
| Response AUPRC | 0.445373 | 0.460838 | +0.015465 | 通过 |
| Response Recall | 0.826087 | 0.841994 | +0.015907 | 通过 |
| NLI 增量平均时延 | — | 153.242 ms/response | — | ≤250 ms，通过 |

四项注册门全部通过。NLI 使用 FP16 batch 8，共处理 20,333 个句子与 52,811 个 pair；峰值 GPU
allocated 768,436,736 bytes，未触发 OOM 或 batch 4 回退。总运行时间 460.30 秒。

## 必须保留的反向证据

- Span precision：`0.118138 → 0.133124`；
- Span recall：`0.347892 → 0.302058`，下降 `0.045835`；
- source-cluster bootstrap 95% CI：`[-0.000657, +0.017168]`，覆盖 0；
- 正向 bootstrap 比例为 96.59%，但不能据此宣称稳定显著提升；
- 历史 lexical coverage response AUPRC 为 `0.504173`，仍高于 NLI candidate 的 `0.460838`。

因此 `accept_advisory_profile` 只表示候选满足预先约定的四项注册门，不表示其统计稳定性、召回、
response-level 能力或生产适用性全面优于现有 lexical profile。

## 条件式冻结结果

- 保留三个既有 profile 数值和角色；只把 registry/profile version 同步到 `1.1.0`；
- 新增 `ragtruth-nli-span-localization`，冻结 NLI/BGE revision、模型哈希、12 维特征顺序、
  Logistic Regression 系数/截距、阈值与 test 聚合指标；
- Day 4 experiment 标为 `completed`，防止重新运行 optimization；
- Day 2 保持 provisional、Day 3 保持 deferred，均不读取官方 test；
- Day 2/3 的新增 train/validation 证据与重新评估进入 Week 6 Extra，不属于 Day 5。

## 隐私与发布边界

受 Git 管理的结果只包含聚合指标、哈希、协议和限制。test-only JSONL、Dense/NLI 缓存与完整
summary 位于 `backend/datasets/` 的 Git 忽略区域；没有将样本 ID、原文、gold spans、逐 pair
logits 或逐样本 score 写入 tracked 文件。

本地代码和文档已准备为 `v1.2.0` release candidate。本计划日不包含 Git commit、Tag、push 或
GitHub Release；这些动作仍需用户在审核本报告与质量门结果后另行批准。

## RC 质量门

- 后端完整回归：294 passed；
- Ruff：`app`、`scripts`、`tests` 全部通过；
- mypy strict：应用 100 个源文件通过；新增 Day 5 两个脚本单独 strict 通过；
- `uv lock --check --offline`：通过；
- 前端 Vitest：2 files、10 tests 通过；
- Vue TypeScript、Oxlint、ESLint：通过；
- Vite production build：1,748 modules transformed；
- OpenAPI：版本 1.2.0、19 paths；
- test-only 数据与结果缓存 Git 忽略检查、聚合 JSON/NPZ 隐私审计、JSON schema、关键 SHA-256
  与 Git diff 检查：通过。
