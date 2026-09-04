# Agentic 技术文档

本目录描述 Agentic 1.2.0 的**当前实现**。逐周工程日志用于解释系统如何演进，本目录则用于回答“系统现在是什么、如何运行、模块如何协作、接口如何使用、哪里仍有限制”。若历史计划与当前代码、许可或数据库迁移不一致，以当前代码、根目录 `LICENSE`、`THIRD_PARTY_NOTICES.md`、数据库迁移和本目录为准。

## 文档适用对象

- 使用者：配置模型、启动服务、创建资料空间并使用智能体。
- 开发者：理解模块边界、扩展解析器、检索器、生成器或前端页面。
- 研究者：复现实验、接入 Benchmark、比较评分算法或规划微调工作流。
- 维护者：迁移数据库、备份本地数据、定位索引和模型故障。

## 推荐阅读路线

### 第一次运行

1. 阅读根目录 [README](../../README.md) 的快速开始。
2. 按[配置参考](configuration.md)创建根目录 `.env`。
3. 按[运行与排障](operations.md)检查本地模型、迁移和健康状态。
4. 需要直接调用后端时阅读 [API 参考](api-reference.md)。

### 开发和维护

1. [系统架构](architecture.md)
2. [资料与 RAG 管线](data-and-rag-pipeline.md)
3. [智能体与生成链路](agent-and-generation.md)
4. [开发与测试](development-and-testing.md)
5. [运行与排障](operations.md)

### 发布与后续研究

1. [v1.2.0 Release Notes](../releases/v1.2.0.md)
2. [v1.2.0 数据脱敏与发布安全审查](../releases/v1.2.0-security-review.md)
3. [v1.1.1 License Patch Release Notes](../releases/v1.1.1.md)
4. [v1.1.0 Release Notes](../releases/v1.1.0.md)
5. [1.0.0 历史基线说明](version-1.0.0.md)
6. [公开 Benchmark 与冻结基线](evaluation-and-baselines.md)
7. [第五周实施计划](../deliverables/week-05-plan.md)
8. [计划日 5 统一基线与研究入口](../deliverables/week-05-day-05.md)
9. [第 6～11 周研发路线与 GitHub 版本节点](../deliverables/week-06-to-11-roadmap.md)
10. [第六周计划日 1：实验注册与错误切片](../deliverables/week-06-day-01.md)
11. [第六周计划日 2：Dense Top-100 直接重排](../deliverables/week-06-day-02.md)
12. [第六周计划日 3：Completeness 两阶段评分](../deliverables/week-06-day-03.md)
13. [第六周计划日 4：NLI 幻觉定位审批前置](../deliverables/week-06-day-04-approval.md)
14. [第六周计划日 4：下载与数据派生核验](../deliverables/week-06-day-04-readiness.md)
15. [第六周计划日 4：句级 NLI 幻觉定位](../deliverables/week-06-day-04.md)
16. [第六周计划日 5：候选冻结与最终 Test 审批前置](../deliverables/week-06-day-05-approval.md)
17. [第六周计划日 5：最终 Test 与条件冻结](../deliverables/week-06-day-05.md)
18. [通用智能体平台迁移设计决策](../design-decisions/general-agent-platform.md)
19. [第 1～6 周工程日志](../engineering-logs/README.md)

## 文档地图

| 文件 | 主要问题 |
|---|---|
| [architecture.md](architecture.md) | 系统由哪些组件组成，数据和请求如何流动？ |
| [configuration.md](configuration.md) | 每个环境变量是什么意思，如何切换模型？ |
| [api-reference.md](api-reference.md) | 后端提供哪些 REST/SSE 接口和错误码？ |
| [data-and-rag-pipeline.md](data-and-rag-pipeline.md) | 文件如何变成可检索、可引用的证据？ |
| [agent-and-generation.md](agent-and-generation.md) | 问答、总结、组卷和联网如何路由与校验？ |
| [development-and-testing.md](development-and-testing.md) | 如何开发、迁移、测试和运行本地评测？ |
| [evaluation-and-baselines.md](evaluation-and-baselines.md) | 公开 Benchmark、冻结 profile 和实验治理规则是什么？ |
| [operations.md](operations.md) | 如何启动、备份、恢复和排查常见故障？ |
| [version-1.0.0.md](version-1.0.0.md) | 1.0.0 冻结了什么，还有哪些发布前事项？ |

## 当前实现摘要

| 维度 | 1.0.0 状态 |
|---|---|
| 产品形态 | 本地单用户、资料驱动的通用智能体实验平台 |
| 界面语言 | 当前仅中文；英文界面、提示词、错误信息与双语质量验证规划于后续 `v1.6.0` |
| 资料空间 | 已实现；内部继续使用 `Course` / `course_id` / `/courses` 兼容标识 |
| 文件格式 | PDF、PPTX、DOCX、Markdown、TXT |
| 入库 | 自动解析、OCR 回退、结构化分块、Embedding、Qdrant 写入 |
| 检索 | BGE-M3 Dense 候选召回 + BGE Reranker + 证据门控 |
| 生成任务 | 普通问答、动态总结、混合组卷、快速对话 |
| 外部信息 | 条件触发的 DeepSeek 服务端 Web Search |
| 模型接口 | DeepSeek、Qwen、Kimi、GLM 的 OpenAI-compatible 预留/运行接口 |
| 会话 | 快速对话和资料空间对话分别持久化 |
| 可观测性 | 文档处理进度、引用元数据、检索诊断、Token 累计 |
| 评测 | FiQA、RAGTruth、RAGBench 已获批并完成冻结基线；机器 profile 1.0.0 可校验加载 |
| 微调 | 规划中；1.0.0 没有训练任务或微调界面 |

## 事实来源优先级

文档维护时按以下顺序判定事实：

1. `backend/app`、`frontend/src` 当前代码；
2. `backend/migrations/versions` 数据库迁移；
3. `.env.example`、`backend/pyproject.toml`、`frontend/package.json`；
4. 本目录的当前态文档；
5. `docs/design-decisions` 中已采纳的设计；
6. `docs/engineering-logs` 和 `docs/deliverables` 中的历史记录与计划。

## 术语兼容说明

产品界面已迁移为通用智能体语义，但为避免一次性破坏数据库和接口，1.0.0 保留了一层内部兼容命名：

| 用户可见术语 | 1.0.0 内部标识 | 说明 |
|---|---|---|
| 资料空间 | `Course`、`course_id`、`/api/courses` | 数据与 API 尚未重命名 |
| 空间资料 | `Document` | 上传文件及其索引状态 |
| 智能体对话 | course conversation | 绑定一个资料空间的对话 |
| 快速对话 | quick conversation | 不访问资料空间向量库 |
| 内容生成/组卷 | exam task | 历史能力名称继续保留 |

这种兼容是明确的 1.0.0 设计边界，不代表产品仍局限于课程学习。后续只有在提供数据库迁移、API 兼容层和前端回归后，才应重命名内部领域对象。
