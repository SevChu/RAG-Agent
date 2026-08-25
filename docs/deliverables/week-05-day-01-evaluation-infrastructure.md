# 第 5 周计划日 1 验收说明：冻结 M0 与评测基础设施

## 当前交付状态

计划日 1 的离线工程实现已经完成：M0 运行身份、100 条数据结构评测集、候选参考答案、
train/validation/test 章节隔离、可恢复执行器、持久化 token 账本、确定性指标、人工复核层和
LLM-as-Judge 辅助层均已落地并通过全量回归。

真实 DeepSeek M0 试点尚未发出请求。运行审批在发送前拦截了调用，因为该操作会把当前问题以及
检索到的本地教材片段发送到 `https://api.deepseek.com`。用户已经批准读取真实数据和 1M token
预算，但还需要明确批准这一具体外部数据发送边界。当前没有生成 token 账本，实际调用数和
token 消耗均为 0；确认后可直接从同一 CLI 开始，不需要重建数据集或重置产物。

## 冻结的 M0

| 项目 | 冻结值 |
|---|---|
| 基线名称 | M0 |
| Git 提交 | `d1dfc339916b6c71d761c9d896b45b3f83e96886` |
| 模型 | `deepseek-v4-flash` |
| 同会话历史 | 最近 6 条、最多 6000 字符 |
| 课程记忆 | 关闭 |
| 随机种子 | `20260810` |
| 数据集 | `week05-data-structures-100` / `2026-08-10.1` |
| 数据集 SHA-256 | `b978824048ee4847895bc15224ef5d1a876bce731580216dce02e05473b4c415` |
| 问答运行代码指纹 | `ddeac2056ed36e7473404803736a1d7b10c71997f99532f3aa4901da49f050fc` |
| 第一日硬预算 | 1,000,000 tokens，调用前保守扣额 |

基线清单还记录了分块、检索、重排、外部搜索参数，以及“数据结构”课程三份已完成资料的文件名、
大小、状态和 SHA-256。清单不包含 API Key。

本地清单：`D:\Agentic\output\week-05\day-01\m0\baseline-manifest.json`。

## 100 条评测集

### 数据隔离

| Split | 数量 | 隔离主题 | 用途 |
|---|---:|---|---|
| train | 60 | 线性结构、树、查找 | 失败分析和规则开发 |
| validation | 20 | 排序 | 第五日参数选择 |
| test | 20 | 图 | 最终独立结论 |

数据契约会拒绝同一 `partition_key` 跨 split 出现，避免相邻章节或同一问题变体同时进入调参集和
最终测试集。

### 类型分布

| 类型 | 数量 |
|---|---:|
| 普通课程问答 | 25 |
| 资料不足与拒答 | 10 |
| 课程＋外部混合来源 | 15 |
| 动态总结 | 10 |
| 混合组卷 | 10 |
| 多轮上下文 | 20 |
| 课程隔离与污染测试 | 10 |

数据文件位于 `backend/evaluations/week05/dataset-v1.json`。每条包含问题或多轮问题、来源范围、
预期任务、预期状态、候选参考答案、候选得分点、候选资料定位、外部搜索要求、禁止来源和组卷
结构约束。候选答案只参与人工审核和辅助词项统计，不会进入发送给被测模型的提示。

## 人工标注与 Judge 分离

生成了两个本地产物：

- `D:\Agentic\output\week-05\day-01\annotations\annotation-review.md`：适合逐题阅读的 100 条
  问题和候选答案；
- `D:\Agentic\output\week-05\day-01\annotations\human-annotations.json`：机器可读的人工标注
  文件，默认全部为 `pending`。

人工答案只有填写 `reference_answer`、`reviewer` 并将状态改为 `verified` 后才算正式标注。
LLM-as-Judge 使用另一份带 `judge_model` 和 `judge_prompt_version` 的结果文件，合并后仍保留为
`llm_judge` 辅助字段，不能覆盖 `human_review`。

## 可恢复执行与报告

- 每个用例建立独立临时对话，并调用正式 `/answers` 入口；多轮用例在同一临时对话连续执行；
- 每个已完成用例单独原子写入 `cases/W5-NNN.json`，进程中断后默认跳过；
- 失败用例只有显式传入 `--rerun-failed` 才会重跑；已完成用例即使传入该参数也不会再次调用；
- 账本在每次 DeepSeek 或外部搜索前先扣除保守上限，超出 1M 时在调用前停止；
- 报告包含任务、状态、来源目标 Recall/MRR、引用、拒答、外部搜索、隔离泄漏、延迟和 token；
- 完整回答和引用正文只保存在被 `.gitignore` 排除的本地 `output/`，版本库只保存数据契约、
  候选标注和代码。

## CLI 验收

在 `D:\Agentic\backend` 执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation validate
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation snapshot
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation export-annotations
```

数据校验应显示：100 条、60/20/20、七类数量分别为 25/10/15/10/10/20/10，且 49 个章节分区
没有跨 split。

取得外部发送授权后，14 条代表性试点命令为：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation run `
  --case W5-004 --case W5-015 --case W5-016 --case W5-021 `
  --case W5-026 --case W5-034 --case W5-037 --case W5-051 `
  --case W5-059 --case W5-061 --case W5-067 --case W5-071 `
  --case W5-079 --case W5-091
```

试点完成后，根据 `token-ledger.json` 的实际报告用量与保守计入量判断 1M 是否足够继续剩余
86 条。若不够，CLI 会在下一次调用前停止，不自动提高预算。

## 自动验证

- 数据集 `validate` 通过：100 条、60/20/20、七类分布和章节隔离全部符合约定；
- 新增评测、预算和复核层针对性测试 10 项通过；
- 后端全量 Pytest `228 passed`；
- Ruff 全量通过；
- Mypy strict 检查 98 个 `app` 与 `scripts` 源文件通过；
- 未修改 `rag_context_max_messages=6` 或 `rag_context_max_chars=6000`；
- 无数据库迁移、前端改动、新依赖、模型下载或 Git 提交。

## 待验收与下一步

1. 用户先审核 100 条候选问题和答案，可分批回填正式人工答案；
2. 用户明确是否允许把当前问题及检索到的本地教材片段发送到
   `https://api.deepseek.com`，仅用于本次已批准的 M0 评测；
3. 获批后运行 14 条试点，记录成本预测，再决定是否在同一 1M 账本内继续；
4. M0 报告完成且用户验收前，不实施计划日 2 的 100k 长上下文，也不创建 Git 提交。
