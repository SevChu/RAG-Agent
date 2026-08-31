# Changelog

本项目的显著变化记录在此。版本采用 [Semantic Versioning](https://semver.org/)。在 GitHub 发布前，日期、项目名和发布链接仍可根据用户最终决定调整。

## [Unreleased]

## [1.1.1] - 2026-08-31

### Changed

- 重写专有 `LICENSE` 的适用范围，只覆盖 Severus Chu 拥有版权的 Agentic 原创材料；
- 新增 `THIRD_PARTY_NOTICES.md`，将第三方依赖、模型、Benchmark 与底层数据明确排除在
  Agentic 专有版权主张之外，并记录 FiQA 非商业限制及 MPL/LGPL 分发门禁；
- 明确 `benchmarks/` 聚合结果仅供研究参考，不重新许可底层数据或解除上游限制。

## [1.1.0] - 2026-08-30

### Added

- 通用智能体与资料空间界面语义迁移；
- BEIR FiQA-2018 检索基线；
- RAGTruth 回答级幻觉与 span 定位基线；
- RAGBench adherence、relevance、utilization、completeness 综合评分基线；
- 统一公开 Benchmark 注册表、Adapter、安全冻结流程和机器可读 baseline profile 1.0.0；
- 第 6～11 周评分算法、AgentProfile、微调、记忆与金标集路线。

## [1.0.0] - 2026-08-25

### Added

- 资料空间创建、列表、详情、单删、批删和级联删除。
- PDF、PPTX、DOCX、Markdown、TXT 上传、校验和自动后台索引。
- PDF 原生文本与逐页 PaddleOCR 回退。
- 章节感知结构化分块和完整来源谱系。
- 本地 BGE-M3 Dense Embedding、Qdrant Local 和 BGE Reranker。
- 证据角色门控、有限多轮上下文和查询改写。
- 带引用的资料问答、动态总结和混合组卷。
- 条件 DeepSeek Web Search 与混合来源引用。
- 独立快速对话、两类持久化会话和 SSE 交互。
- DeepSeek、Qwen、Kimi、GLM OpenAI-compatible 模型接口。
- 按模型累计的输入缓存命中/未命中、输出和总 Token 统计。
- 本地 100 条候选评测数据、可恢复执行、预算账本、人工审核和确定性指标。
- Agentic 通用智能体定位与资料空间界面语义。
- 1.0.0 当前态技术文档体系。

### Known limitations

- 仅支持本地单用户运行，无认证和多租户。
- Qdrant 使用 Local Mode，不支持多 worker 共享写入。
- Web Search 仍是 DeepSeek 专用适配器。
- 公共 Benchmark 尚未获批下载，经典评分算法报告尚未执行。
- AgentProfile、长上下文记忆和逐智能体微调界面尚未实现。
- GitHub Release 页面尚未创建；当前 1.0.0 发布以 `main` 分支和 `v1.0.0` Tag 为准。
