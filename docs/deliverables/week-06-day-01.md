# 第六周计划日 1：实验注册与错误切片

## 状态

- 完成日期：2026-08-31
- 目标版本：`v1.2.0`
- 开发基线：`60755dd3ca440b774322a5b0dc713234816ffaeb`
- 结果：实验注册、防 test 污染和统一错误切片契约已实现；未运行候选算法

## 当日边界

本日只建立后续算法实验的治理基础，不运行 Dense 重排、Completeness 两阶段模型或 NLI 推理。
不下载模型、不调用外部 API、不访问 test split、不提交或发布 GitHub 版本。受 Git 管理的文件
只保存配置和聚合契约，不保存问题、回答、上下文、预测或其他逐样本内容。

## 实现内容

### 1. 候选实验注册

`backend/app/evaluation/experiment-registry.json` 登记了三项候选：

| Experiment ID | 计划日 | 状态 | 主指标 | 关键守门指标 |
|---|---:|---|---|---|
| `w6-d2-dense-direct-rerank` | 2 | ready | nDCG@10 | Recall@100 不回退；单列时延 |
| `w6-d3-two-stage-completeness` | 3 | ready | Completeness Spearman | Completeness RMSE；其他 TRACe 维度 |
| `w6-d4-sentence-nli-spans` | 4 | draft | span char F1 | 回答级 AUPRC/Recall；时延 |

每项登记都包含假设、唯一主变量、数据/模型/代码 revision、随机种子、优化 split、主指标、
守门指标和切片维度。Day 2、Day 3 所需数据与模型均已冻结；Day 4 的 NLI 模型保持
`pending_approval`，在来源、许可、大小、revision、哈希和显存适配获批前不能转为 ready。

### 2. Split 防污染

- 优化 split 的类型只允许 `train` 和 `validation`；
- registry 的 `test_access` 固定为 `forbidden`；
- 运行时 `require_optimization_split("test")` 会显式拒绝并说明需要后续用户批准；
- FiQA 的 `dev` 映射为 validation；
- RAGTruth validation 只从 train 按 source 分组派生，官方 test 保持封存；
- 已发布的 1.1.x test 指标只作历史参考，不作为本轮参数选择输入。

### 3. 标准错误切片

所有候选统一使用五个维度：

1. domain；
2. positive / negative class；
3. length：short `<=256`、medium `257..1024`、long `>1024` chars；
4. evidence count：none、single、multiple；
5. error type，可为一条观测登记多个规范化错误标签。

`SliceObservation` 故意不提供样本 ID 或文本字段，只接受 split、切片元数据和有限数值指标。
`aggregate_slices` 输出 count、mean、minimum 和 maximum，供后续三类 runner 共用。

## 新增或修改文件

- `backend/app/evaluation/experiments.py`
- `backend/app/evaluation/experiment-registry.json`
- `backend/app/evaluation/__init__.py`
- `backend/tests/test_experiments.py`
- `docs/technical/evaluation-and-baselines.md`
- `docs/engineering-logs/week-06.md`

## 验证

- 新增 6 项针对性测试通过；
- Ruff 与 mypy strict 针对新增模块通过；
- 全量后端 271 项测试通过；
- 全量 Ruff 通过，mypy 对 100 个源文件检查通过；
- 测试没有读取本地资料空间、对话、test split 或外部网络。

## 下一入口

计划日 2 使用 ready 的 `w6-d2-dense-direct-rerank` 登记，在 FiQA train/dev 上实现并比较
Dense、RRF、RRF+Reranker 和 Dense Top-100 直接 Reranker。正式 test 继续保持封存。
