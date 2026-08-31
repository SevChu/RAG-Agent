# Agentic 1.0.0 技术文档入口

Agentic 1.0.0 的当前态技术文档位于 [`docs/technical/`](docs/technical/README.md)。该文档体系以当前代码、数据库迁移和配置为事实来源，区别于根 README 中保留的早期目标与逐周实施历史。

## 快速导航

- [技术文档索引](docs/technical/README.md)
- [系统架构](docs/technical/architecture.md)
- [配置参考](docs/technical/configuration.md)
- [API 参考](docs/technical/api-reference.md)
- [资料与 RAG 管线](docs/technical/data-and-rag-pipeline.md)
- [智能体与生成链路](docs/technical/agent-and-generation.md)
- [开发与测试](docs/technical/development-and-testing.md)
- [运行与排障](docs/technical/operations.md)
- [1.0.0 基线说明](docs/technical/version-1.0.0.md)
- [版本变更记录](CHANGELOG.md)

## 发布状态

- 本地功能和文档基线：`1.1.1`（功能基线 `1.1.0`，许可边界补丁 `1.1.1`）
- GitHub 发布目标：`SevChu/RAG-Agent` 的 `main` 分支与 `v1.1.1` Tag
- 项目名 `Agentic`、仓库名 `RAG-Agent`、专有许可范围、第三方排除项和公开可见性：已确认
- 公开 Benchmark：FiQA、RAGTruth、RAGBench 已审批并完成聚合结果发布；原始数据保持本地隔离

本次 v1.1.1 许可补丁发布已获用户明确批准。第三方依赖、模型和 Benchmark 不属于 Agentic
专有版权主张；完整边界见 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。
