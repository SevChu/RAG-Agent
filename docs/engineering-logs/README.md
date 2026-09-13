# 工程日志索引

本目录记录 Agentic 从课程学习 Agent 演进为通用智能体实验平台的实施过程。

日志按照项目计划周独立保存，计划日不等同于自然日。每个计划日同时记录实际完成日期，以便将计划进度、代码提交和真实时间对应起来。

## 日志文件

| 计划周 | 主题 | 状态 | 当前进度 | 日志 |
|---|---|---|---|---|
| 第 1 周 | 工程骨架 | 已完成 | 已完成计划日 1～5 | [week-01.md](week-01.md) |
| 第 2 周 | 知识库入库 | 已完成 | 已完成计划日 1～5并通过周验收 | [week-02.md](week-02.md) |
| 第 3 周 | RAG 问答 | 已完成 | 计划日 1～5 均已完成并通过验收 | [week-03.md](week-03.md) |
| 第 4 周 | Agent、总结和出题 | 已完成 | 计划日 1～5、Token 统计及独立会话默认联网增量均已验收 | [week-04.md](week-04.md) |
| 第 5 周 | 通用智能体迁移与公开 Benchmark 基线 | 已完成 | 计划日 1～5 已验收；`v1.1.0` 已发布，许可补丁为 `v1.1.1` | [week-05.md](week-05.md) |
| 第 6 周 | 评分与检索算法优化 | 已完成 | Day 1～5 发布为 `v1.2.0`；Extra 两候选拒绝/延后并发布为 `v1.2.1` | [week-06.md](week-06.md) |
| 第 7 周 | AgentProfile 与多智能体基础 | 已完成并发布 | `v1.3.0` 于 2026-09-11 发布，提交 `15eb125` | [week-07.md](week-07.md) |
| 第 8 周 | 微调平台基础 | 已完成并发布预发布版 v1.4.0-beta.1（2026-09-13） | [五日计划](../deliverables/week-08-plan.md)；目标 `v1.4.0-beta.1` | [week-08.md](week-08.md) |
| 第 9 周 | Reranker 与 Scorer 真实微调 | 未开始 | 两项分别训练与评测，目标稳定版本 `v1.4.0` | [第 6～11 周路线](../deliverables/week-06-to-11-roadmap.md) |
| 第 10 周 | 动态长上下文与资料空间记忆 | 未开始 | `v1.5.0` 第一阶段 | [第 6～11 周路线](../deliverables/week-06-to-11-roadmap.md) |
| 第 11 周 | 自有人工金标集基础 | 未开始 | `v1.5.0` 第二阶段 | [第 6～11 周路线](../deliverables/week-06-to-11-roadmap.md) |
| 后续国际化里程碑 | 中英文产品支持 | 未开始 | 目标版本 `v1.6.0`；当前程序仍仅支持中文 | [第 6～11 周及后续路线](../deliverables/week-06-to-11-roadmap.md) |
| 最终交付周 | Docker、演示、答辩与 Release | 未排期 | 项目需要交付时启动 | 待创建 |

## 跨周设计决策

| 决策 | 状态 | 计划实施 | 文档 |
|---|---|---|---|
| 混合来源回答 | 计划日 1～2 均已实施并通过验收 | 第 4 周计划日 1～2 | [mixed-source-answering.md](../design-decisions/mixed-source-answering.md) |
| 动态总结规划 | 已实施并通过用户验收 | 第 4 周计划日 4 | [dynamic-summary-planning.md](../design-decisions/dynamic-summary-planning.md) |
| 混合组卷与来源配额 | 已实现并通过用户验收 | 第 4 周计划日 4-B | [mixed-exam-generation.md](../design-decisions/mixed-exam-generation.md) |
| 通用智能体平台迁移 | 第一阶段已完成 | 第 5 周计划日 1 | [general-agent-platform.md](../design-decisions/general-agent-platform.md) |
| 资料空间记忆与同会话长上下文 | 已完成旧方案设计，调整为后续独立里程碑 | 后续阶段 | [course-memory-and-long-context.md](../design-decisions/course-memory-and-long-context.md) |
| AgentProfile 配置版本与会话绑定 | Day 1～4 数据、管理、运行与界面已实现 | 第 7 周 | [agent-profile-versioning.md](../design-decisions/agent-profile-versioning.md) |

## 记录规范

每个计划日固定记录：

1. 当日目标和明确不实施的范围；
2. 实际完成内容；
3. 关键设计与产品决策；
4. 主要新增或修改文件；
5. 测试、构建、迁移和安全检查结果；
6. 遇到的问题、原因和处理方式；
7. 遗留项、技术债和下一计划日入口；
8. 对应的 Git 分支、提交哈希和提交信息。

每个计划周结束时补充：

- 周目标完成度和可演示成果；
- 与原计划的差异及原因；
- 质量数据汇总；
- 已知问题和技术债；
- 下一周开始前必须满足的输入条件。

## 维护原则

- README 只保存项目总体状态和简要进度，详细实施过程以本目录为准。
- 日志记录结果、设计理由和验证证据，不复制大段终端输出。
- 每周日志相互独立；新一周开始时创建新文件，不继续追加到上一周。
- 已结束的计划周原则上不重写历史。如需更正，在原记录中增加带日期的“更正说明”。
- 不记录 API Key、访问令牌、私人课程资料正文或其他敏感内容。
- 日志变更随代码提交，使计划日记录能够追溯到确定的代码状态。
- 跨计划周且会影响后续实现的数据契约或产品决策，另建 `docs/design-decisions/` 文档，并从
  README 和日志索引同时链接，保证新任务可以恢复上下文。

### 2026-08-31 更正说明

应用户要求，第五周主日志按前四周统一模板完成格式补录。补录只整理既有事实、验收记录和
Git 归属，不改变已发布 Benchmark 数值或版本历史；原始 M0 方案保留为历史归档。

2026-09-11：Week 7 补充完成[产品/科研分离](../deliverables/week-07-edition-separation.md)，
跨周边界见[设计决策](../design-decisions/product-research-editions.md)。

第七周基础任务已于 2026-09-11 确认验收，并完成[v1.3.0 日志/效果最终审批](../releases/v1.3.0-approval.md)及
[GitHub 正式发布](https://github.com/SevChu/RAG-Agent/releases/tag/v1.3.0)。2026-09-13 已只读复核实际发布状态。

2026-09-11 文档修订：第七周主日志已按第 5/6 周固定栏目重整，逐日事实和验证计数保留；
本周新增产品/科研两份独立 README，修订后再次提交用户审批。

2026-09-11：第八周 Day 1 已完成[训练数据 Registry](../deliverables/week-08-day-01.md)，跨周数据与审核规则见[设计决策](../design-decisions/training-dataset-registry.md)。正式数据库未迁移。

2026-09-11：Day 1 获用户验收；Day 2 完成[任务与 Fake Trainer](../deliverables/week-08-day-02.md)，规则见[任务生命周期](../design-decisions/training-run-lifecycle.md)。正式数据库与 worker 开关未变更。

2026-09-11：用户授权后完成[Day 2 正式数据副本演练](../deliverables/week-08-day-02-copy-rehearsal.md)，旧数据保留、迁移往返及 Fake worker 通过；正式库和开关保持不变。

2026-09-11：Day 2（含副本演练）获用户验收；Day 3 完成[模拟 Adapter Registry](../deliverables/week-08-day-03.md)，规则见[产物一致性设计](../design-decisions/simulated-adapter-registry.md)。正式库保持不变。

2026-09-12：Day 3 获用户验收；Day 4 完成[逐智能体五步界面与浏览器验收](../deliverables/week-08-day-04.md)，正式库与 worker 开关保持不变，Day 5 尚未启动。

2026-09-13：Day 4 获用户验收；Day 5 进入[正式环境准备与审查](../deliverables/week-08-day-05.md)，新副本演练通过，正式迁移和 worker 启用尚未执行。

2026-09-13：用户批准后完成[正式 06→09 升级、worker 启用及唯一合成验收](../deliverables/week-08-day-05-formal-upgrade.md)，服务保持运行；候选与发布材料待后续。


2026-09-13：用户确认第八周功能与 Fake Trainer 可视化验收通过；[周总结](week-08.md)记录功能完成与候选发布收尾的区别。同步更正第七周发布状态，保留此前逐日审批记录作为历史。


2026-09-13：按用户要求完成 [v1.4.0-beta.1 发布审阅材料](../releases/v1.4.0-beta.1-approval.md)，
补齐当前技术文档、升级恢复和第八周发布日志；候选回归与实际双包验证通过，等待审阅后再发布。


2026-09-13：日志复审及最终发布获批后，完成 [v1.4.0-beta.1 GitHub 预发布](https://github.com/SevChu/RAG-Agent/releases/tag/v1.4.0-beta.1)；
Tag 指向 `dac057d9d877ae7d2e969b7059757ea3d8193610`，两个源码包及 SHA256SUMS.txt 已上传并核对远端 SHA-256。
Latest 仍为 v1.3.0；后续状态记录提交不移动发布标签，详见[第八周日志](week-08.md)。
