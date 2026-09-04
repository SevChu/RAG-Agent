# 第六周计划日 4：句级 NLI 幻觉定位

## 状态

- 完成日期：2026-09-04
- 实验 ID：`w6-d4-sentence-nli-spans`
- 目标版本：`v1.2.0`
- 数据：RAGTruth frozen train-only 派生集
- 决策 split：由官方 train 按 `source_id + task_type` 派生的 validation
- 官方 test：未打开、未哈希、未解析
- 结论：通过预登记 validation 晋级门，进入 Day 5 候选；尚不冻结为默认

## 实验边界

本次严格比较相同 Logistic Regression 下的单一特征变化：

```text
baseline: 8 个 lexical 特征 + BGE-M3 dense support
candidate: 相同 9 维 baseline + 3 个冻结 NLI 特征
```

三个新增特征为每个回答句子相对全部 source context chunk 的
`max_contradiction`、`max_entailment`、`max_neutral`。两组使用相同 class weight、solver、
fit/calibration/validation 切分、阈值搜索和指标函数。历史 lexical coverage 只作第二参考，
不承担本次单变量因果对照。

NLI 固定为 `cross-encoder/nli-deberta-v3-base` revision
`6c749ce3425cd33b46d187e45b92bbf96ee12ec7`，权重 SHA-256 为
`d8148c6d49e0a7925134294c56326c71fe0ab1dc390e37355e00c7efbb488afa`。模型以本地
safetensors、FP16、CUDA batch 8、max length 512、`truncation="only_first"` 运行；没有调用
网络、外部 API 或远端模型代码。

## 数据隔离与划分

runner 只接受 manifest SHA-256 为
`e70a891458a68861554da76dc9087b67356abf19b5e22b4ab5842545ff058cbc` 的 train-only 目录。
启动时重新校验 manifest、两个数据文件 hash、引用、唯一性、标签边界和全部 row 的 train split。

| 用途 | Sources | Responses |
|---|---:|---:|
| Fit | 1,507 | 9,042 |
| Calibration | 504 | 3,024 |
| Validation | 504 | 3,024 |

共 2,515 个 source、15,090 条 response、123,184 个回答句子。相同 source 不跨 split，各 task
分别按 seed 42 固定为约 60%/20%/20%。fit 只训练 Logistic Regression，calibration 只选择
response/span 阈值，validation 只执行最终比较。

本轮 `official_test_accesses=0`、`prediction_artifacts_written=0`。缓存与 summary 不含样本 ID、
source/response 文本、gold span 或逐样本 score。

## Validation 结果

| 指标 | Lexical+dense logistic | + Frozen NLI | Delta |
|---|---:|---:|---:|
| Span char F1 | 0.228140 | **0.243289** | **+0.015149** |
| Span precision | 0.159386 | **0.185440** | +0.026054 |
| Span recall | **0.401210** | 0.353597 | -0.047613 |
| Response AUPRC | 0.557403 | **0.572814** | **+0.015411** |
| Response AUROC | 0.677103 | **0.690500** | +0.013397 |
| Response Recall | 0.832965 | **0.843267** | **+0.010302** |
| Response F1 | 0.678861 | **0.686228** | +0.007367 |

Calibration 选出的阈值：baseline response/span 为 `0.57/0.67`，candidate 为 `0.585/0.71`。

预登记四项数值门全部通过：span char F1 提高、response AUPRC 与 Recall 不回退、NLI 增量平均
时延不超过 250 ms/response。

### 必须保留的权衡

候选不是全面占优。它把 span false positives 从 283,229 降到 207,897，同时 true positives
从 53,702 降到 47,329；因此 precision 和 micro F1 上升，但 span recall 明显下降。逐回答
span F1 比较为 216 条改善、161 条退化、2,647 条持平；在 hallucinated response 上逐回答 F1
平均 delta 为 `-0.008897`。这说明总体收益主要来自减少过宽标注，而不是找回更多幻觉字符。

历史 lexical coverage 的 validation response AUPRC 为 `0.604584`、Recall 为 `0.846210`，仍略高于
本次 NLI 候选；但其 span F1 只有 `0.202180`。该历史方法的角色只是参考，不改变本次“相同
logistic 下只增加 NLI 特征”的注册对照结论。

## Source-cluster 稳定性

以 504 个 validation source 为 cluster、seed 42 执行 10,000 次 bootstrap：

- micro span char F1 delta 95% CI：`[+0.005455, +0.024323]`；
- bootstrap delta > 0：`99.83%`；
- 区间下界高于 0，稳定性门通过。

该结果支持在当前派生 validation 上存在稳定的 micro F1 收益，但不能外推到官方 test、中文、
真实用户流量或生产阻断精度。

## 资源与缓存

- NLI pair：310,938；
- NLI 推理：2,485.93 秒；
- 增量平均时延：164.74 ms/response；
- 正式运行 CUDA peak allocated：768,436,736 bytes，约 732.84 MiB；
- 预算：4 GiB；未触发 OOM 或 batch 4 回退；
- NLI cache SHA-256：
  `9adfd6d48968ac8407c99be886ed5de4797d2a84ae847a81cc5b5c863c4bbbcf`；
- Dense cache SHA-256：
  `ca0d1174c7cc44e274c0f06b8ba2aac914872d3917b5e573c5ca0d18a9d2aa50`；
- Slice summary SHA-256：
  `68fdc66284a697d2046f9f04a29f6654be2a8334d52fa390a773b972aa4df10b`；
- Runner SHA-256：
  `e1bfabe47307fd2905be06cab8bf8c01c04ff3da3c12e83efddf6c6ccb4c75a6`。

缓存命中复跑耗时 44.42 秒，没有重新加载 NLI 权重或执行 pair 推理；指标、阈值、bootstrap
与 slice hash 均和首次运行一致。

## 实现与验证

主要文件：

- `backend/scripts/prepare_ragtruth_train_only.py`
- `backend/scripts/run_ragtruth_nli_experiment.py`
- `backend/tests/test_prepare_ragtruth_train_only.py`
- `backend/tests/test_ragtruth_nli_experiment.py`
- `backend/app/evaluation/experiment-registry.json`

runner 强制校验 ready 注册表、train-only manifest、模型 revision/hash、三类标签顺序、CUDA、
batch 4/8 和 4 GiB 显存预算。边界测试覆盖排除行解析前丢弃、父哈希变化、拒绝覆盖、source
划分确定性/互斥性和 NLI pair 按类最大值聚合。

最终质量门：

- Day 4 runner/注册表定向测试 10 项通过；
- 后端全量 287 项测试通过；
- Ruff 对 `app`、`scripts`、`tests` 全量通过；
- 派生工具、NLI runner 与实验注册模块 strict mypy 通过；
- mypy 对 100 个应用源文件全量通过；
- JSON/NPZ 样本载荷字段审计通过，更新文档本地链接零缺失；
- 唯一警告为 pytest 无法写工作区 `.pytest_cache`，不影响测试结果。

## 决策与下一入口

当前机器决策为 `promote`：把 `lexical+dense logistic + frozen sentence-level NLI features`
带入 Day 5 汇总，和 Day 2、Day 3 候选共同评审。

这不是自动冻结或发布批准。考虑 span recall 下降和历史 lexical response 指标仍更高，Day 5 应
明确讨论 profile 的主目标和回退策略。只有用户另行批准后，才允许一次性打开官方 test 并决定
是否冻结 Scorer profile 或创建 `v1.2.0`。
