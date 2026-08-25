# Changelog

本项目的显著变化记录在此。版本采用 [Semantic Versioning](https://semver.org/)。在 GitHub 发布前，日期、项目名和发布链接仍可根据用户最终决定调整。

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
