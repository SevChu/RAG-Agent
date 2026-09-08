# Changelog

本项目的显著变化记录在此。版本采用 [Semantic Versioning](https://semver.org/)。在 GitHub 发布前，日期、项目名和发布链接仍可根据用户最终决定调整。

## [Unreleased]

## [1.2.2] - 2026-09-08

### Changed

- 前端采用“暖白编辑”风格：暖白纸感面板、陶土橙主色、衬线标题、细边框和小圆角；
- 统一导航、资料空间、资料详情、快速对话、智能体对话、设置及弹窗/下拉框的主题；
- 保留现有页面结构、功能入口与业务交互；状态提示使用协调的绿、赭、红色；
- frontend、backend 与 OpenAPI 应用版本同步为 1.2.2，依赖版本保持不变。

### Fixed

- 修复资料详情表格中隐藏辅助标签可能引起的中等屏宽横向溢出；
- 补齐对话输入区的焦点样式，并调整主题样式加载顺序。

### Release status

- 本版本已通过用户审核并授权发布；发布范围见 [v1.2.2 说明](docs/releases/v1.2.2.md)。
- 不包含仍在独立开发的 Week 7 AgentProfile 配置、迁移或相关文档。

## [1.2.1] - 2026-09-07

### Added

- Week 6 Extra 的 Day 2/3 稳健性复评、预注册确认、一次性 FiQA final-test runner；
- 无样本内容、无本机路径的 `benchmarks/v1.2.1` 聚合证据包。

### Changed

- backend、frontend 与 OpenAPI 候选版本同步为 1.2.1；
- 第六周报告、工程日志和路线图同步最终 `reject` / `deferred` 结论。

### Decision

- Dense Top-100 直接重排在 FiQA official test 上主门失败，最终 `reject`；
- Two-stage Completeness 外层留一领域四门失败，保持 `deferred`；
- 两者均不进入 profile，baseline profile registry 保持 1.1.0。

### Known limitations

- Day 2 train 确认证据为正，但 official test nDCG delta 为负且 CI 跨 0；
- Day 3 证据复用已知领域族，不是全新外部数据库；
- 本补丁只发布离线证据与否决记录，不新增生产评分能力。

## [1.2.0] - 2026-09-04

### Added

- 机器可校验的 Week 6 Experiment Registry、optimization split 防污染和五维匿名错误切片；
- RAGTruth train-only/test-only 安全派生与冻结 NLI final-test runner；
- `ragtruth-nli-span-localization` offline/advisory profile。

### Changed

- baseline profile registry 升至 1.1.0；backend、frontend 与 OpenAPI 版本同步为 1.2.0；
- Dense 直接重排与 Completeness runner 支持注册实验、split-aware 缓存和聚合稳定性报告。

### Known limitations

- NLI span recall 下降且 final-test bootstrap CI 跨 0，不替换 lexical response profile；
- Day 2/3 候选分别保持 provisional/deferred，未访问 official test；
- Week 6 Extra 待独立审核，计划作为 `v1.2.1` 发布，不属于本次候选。

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
