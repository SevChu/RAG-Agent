# 运行与排障

## 1. 标准启停

### 后端

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### 前端

```powershell
cd D:\Agentic\frontend
npm run dev
```

启动指令在 1.0.0 没有因为界面迁移或多供应商接口而改变。模型、URL 或 API Key 修改后只需重启后端；前端在已配置模型之间切换不需要重启。

停止开发服务时，在各自终端按 `Ctrl+C`。不要在索引写入中强制结束多个相关进程；如果中断，重新启动后端会恢复未完成资料。

## 2. 启动检查顺序

1. 根目录 `.env` 存在且至少一个供应商同时配置 Key 和模型列表。
2. `data/models/` 下的 OCR、Embedding、Reranker 路径存在。
3. Alembic 已升级到 head。
4. 端口 8000 和 5173 没有被旧进程占用。
5. 后端健康检查返回 ok。
6. `/api/llm/config` 中目标供应商显示 `configured=true`。
7. 前端设置页能加载模型和 Token 统计。

PowerShell 检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/llm/config
```

健康检查不是深度检查。只有实际上传/检索才能验证本地模型和 Qdrant，只有实际生成才能验证上游 Key、模型 ID 和额度。

## 3. 数据目录

默认从 `backend` 启动时：

```text
D:\Agentic\data\
├─ app.db                         # SQLite
├─ uploads\                       # 原始资料
├─ qdrant\                        # Qdrant Local
└─ models\
   ├─ paddleocr\
   ├─ embedding\bge-m3\
   └─ reranker\bge-reranker-v2-m3\
```

这些目录不属于源码发布物。不要把真实数据和模型推送 GitHub。

## 4. 备份与恢复

### 4.1 一致备份原则

完整业务状态由 SQLite、uploads 和 Qdrant 三部分组成。只备份 `app.db` 会丢失原文件或向量，只备份 Qdrant 也无法恢复资料空间和 Document 元数据。

推荐：

1. 等待所有资料进入 `completed` 或 `failed`。
2. 停止后端，释放 SQLite 和 Qdrant 文件锁。
3. 把 `app.db`、`uploads` 和 `qdrant` 复制到同一个带时间戳的备份目录。
4. 单独记录当前代码提交、Alembic revision、Collection 名和本地模型版本。
5. 对备份生成哈希或使用校验工具。

PowerShell 示例（先停止后端）：

```powershell
$backupRoot = "D:\Agentic-backups\Agentic-2026-08-25"
New-Item -ItemType Directory -Path $backupRoot
Copy-Item D:\Agentic\data\app.db $backupRoot
Copy-Item D:\Agentic\data\uploads $backupRoot -Recurse
Copy-Item D:\Agentic\data\qdrant $backupRoot -Recurse
```

请把示例日期替换为实际备份标识，并确保备份目标不是 Git 仓库内目录。

### 4.2 恢复原则

1. 停止后端。
2. 先另行备份当前 data，避免不可逆覆盖。
3. 确认备份的代码/迁移版本与当前应用兼容。
4. 成组恢复 SQLite、uploads 和 Qdrant。
5. 运行 `alembic upgrade head`。
6. 启动后端并执行一致性审计。
7. 抽查资料引用和重新索引能力。

不要在后端运行时覆盖 Qdrant Local 目录。

## 5. 数据库升级

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
```

升级前备份完整 data。迁移只处理 SQLite 结构，不会迁移 Qdrant Payload 或本地模型；涉及这些结构的版本变化必须提供额外迁移/重索引步骤。

## 6. 日志与诊断入口

- Uvicorn 控制台：HTTP、启动和未捕获异常。
- structlog：索引、Token 记录等后端事件。
- Document API：处理阶段、百分比、细节和失败原因。
- Answer retrieval：查询改写、候选/证据数、设备、路由、联网和质量诊断。
- 设置页：供应商配置状态和 Token 累计。
- `app.ingestion.inspect`：解析/分块只读检查。
- `app.knowledge.audit`：SQLite/文件/Qdrant 一致性。
- `app.knowledge.inspect`：隔离 Collection 上的 Embedding 与搜索检查。

日志和诊断可能包含文件名、问题、模型名或错误原因。公开 Issue 和 GitHub 日志前先脱敏。

## 7. 常见故障

### 7.1 前端提示“无法连接到后端服务”

检查：

1. 后端终端是否仍在运行。
2. `http://127.0.0.1:8000/api/health` 是否可访问。
3. `frontend/.env` 的 `VITE_API_BASE_URL` 是否为正确 `/api` 根地址。
4. 修改前端 env 后是否重启 Vite。
5. 浏览器来源是否列入 `CORS_ORIGINS`。
6. 8000 是否被旧进程占用。

### 7.2 设置页显示“接口待配置”

一个供应商必须同时满足：

- API Key 非空；
- 模型白名单非空；
- 后端已在修改 `.env` 后重启。

DeepSeek 使用 `LLM_API_KEY` + `LLM_AVAILABLE_MODELS`；Qwen/Kimi/GLM 使用各自变量。

### 7.3 模型未绑定到供应商

原因：请求模型不在任何白名单，或前端保留了已经从配置移除的旧选择。

处理：把准确模型 ID 加入对应 `*_MODELS`，确认没有跨供应商重复，重启后端并刷新前端。`LLM_MODEL` 也必须属于某个白名单。

### 7.4 Qwen 401/404/模型不存在

除 Key 和模型 ID 外，还要检查地域。DashScope 不同地域的 Base URL 与 API Key 必须匹配。不要把 `/chat/completions` 重复追加到 Base URL。

### 7.5 上游不接受 JSON 模式

总结、组卷和部分回答校验调用会发送 `response_format=json_object`。如果某供应商/模型不支持该参数，可能返回 HTTP 400。先用普通快速对话验证文本模式，再确认模型官方兼容性；若要支持不兼容模型，应在客户端增加按供应商/模型声明的能力开关和回归测试，而不是全局移除结构化约束。

### 7.6 Web Search 失败但普通回答可用

Web Search 仍依赖 DeepSeek 专用接口。检查：

- `EXTERNAL_SEARCH_ENABLED=true`；
- DeepSeek Key 与白名单；
- `EXTERNAL_SEARCH_MODEL` 是否有效；
- 最终模型是其他供应商时，搜索是否仍有独立 DeepSeek 模型；
- 上游搜索权限和额度。

空间资料充足时系统可保护性降级；没有证据时应显示失败或资料不足。

### 7.7 本地 Embedding/Reranker 模型不存在

典型表现：资料处理失败、检索 503 或错误说明模型目录不存在。

检查 `EMBEDDING_MODEL_PATH` 与 `RERANKER_MODEL_PATH`。应用不会自动下载模型。下载/复制模型前确认来源、许可、版本、大小和哈希；不要未经批准联网获取大模型文件。

### 7.8 CUDA 不可用

`auto` 会回退 CPU，通常不影响正确性，但速度明显下降。retrieval 诊断会返回 `embedding_device`、`reranker_device` 和 `fallback_reason`。

若显式配置 `cuda`，仍需确保 PyTorch、驱动和设备兼容。系统不要求独立安装 CUDA Toolkit，但需要可用的 NVIDIA 驱动与兼容 PyTorch 运行时。

### 7.9 Qdrant 文件锁或 `INDEX_STORAGE_ERROR`

常见原因：

- 两个后端进程访问同一 Local 目录；
- 审计/检查脚本与后端并发访问；
- 旧进程未退出；
- 目录权限或异常中断。

处理：停止重复进程，确保只有一个写入者，再重启后端。删除接口在此错误下会保留文件和 SQLite 记录，不要手工只删其中一层。

### 7.10 资料长时间停在等待/处理中

1. 查看后端终端是否有模型、OCR 或文件错误。
2. 重启后端，让 `recover_incomplete` 恢复任务。
3. 确认 `AUTO_INDEX_DOCUMENTS=true`。
4. 检查原文件仍存在。
5. 如果状态变为 failed，使用页面“重新处理”。

进程内队列不是持久任务系统；机器关机期间不会继续处理。

### 7.11 资料处理失败且提示损坏/无正文

- PDF：检查加密、损坏、空白页和 OCR 模型。
- DOCX/PPTX：确认文件不是旧 `.doc/.ppt` 改后缀，也不是损坏 ZIP。
- TXT/MD：转换为 UTF-8，移除空字节。
- 复杂图片资料：1.0.0 只对 PDF 扫描页做 OCR，不处理 DOCX/PPTX 图片语义。

### 7.12 检索结果相关但不能作为证据

系统会拒绝 `exercise_question` 和 `unknown` 角色，也可能因概念不匹配淘汰相关片段。查看 retrieval 的候选数、合格/拒绝证据数和 content role。不要简单降低所有门槛；应先用回归 Case 判断是角色误判、分块问题、查询改写还是 Reranker 问题。

### 7.13 SSE 中途停止或历史没有本轮

前端停止按钮通过 AbortSignal 断开连接。后端只有在发送完整答案和引用后才保存交换。因此 complete 之前停止时历史中没有半条消息是预期行为。

当前 delta 是后端对完整上游答案的分段发送；停止接收不一定能取消已经完成的上游模型费用。

### 7.14 Token 统计与单次回答 usage 不一致

累计统计包含总结计划、分批生成、修复、外部搜索等所有返回 usage 的调用；单次回答字段通常只代表最终生成结果。供应商缺少缓存拆分时，输入都计入 cache miss。

### 7.15 Token 接口提示数据库表不存在

运行：

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

确认当前 revision 包含 `20260810_04`。

## 8. 安全运行建议

- 默认只监听 `127.0.0.1`。
- 不使用 `--host 0.0.0.0` 暴露到公网，除非前置认证、TLS、防火墙和限流已完成。
- 关闭 `DEBUG` 后再进入共享环境。
- 限制 CORS 到准确来源。
- 使用供应商侧最小权限 Key、额度限制和轮换策略。
- 不在屏幕录制、日志或 Issue 中展示 Key。
- 上传敏感资料前确认供应商数据处理政策，因为检索片段会进入生成请求。
- 对 data 目录实施磁盘权限、备份和必要的加密。

## 9. 生产化差距

1.0.0 适合本地研究和演示。生产化至少需要：

- 用户认证、授权、租户数据隔离和审计；
- 服务端 Qdrant/数据库和对象存储；
- 独立任务队列、幂等作业与并发限额；
- TLS、密钥管理、限流和请求体安全策略；
- 集中日志、指标、Tracing 和告警；
- 备份编排、灾备演练和数据保留策略；
- 上传内容恶意软件检测和敏感信息治理；
- 供应商故障隔离、熔断和成本预算；
- 版本化 API 和滚动迁移方案。

## 10. 发布前运行检查

```text
[ ] 全量后端测试、Ruff、Mypy 通过
[ ] 前端测试、类型检查、Lint、生产构建通过
[ ] Alembic current=head
[ ] .env 与全部密钥未被 Git 跟踪
[ ] data、模型和真实评测输出未被 Git 跟踪
[ ] 空间/资料/对话/Token 主流程人工通过
[ ] 一致性审计无错误
[ ] 公开数据许可与下载状态准确
[x] README、技术文档和版本元数据一致
[ ] 许可证、仓库名和项目名已确认；安全联系信息待补充
```

## 11. 缓存与临时文件维护

| 内容 | 维护方式 |
|---|---|
| `.mypy_cache`、`.ruff_cache`、`.pytest_cache`、自有代码的 `__pycache__` | 相应检查结束后可清理，下次运行会重建；后端检查统一从 `backend` 执行，避免根目录再生成一份缓存 |
| `tmp` 内已经结束的 pytest 专用目录 | 测试完成并保存必要结果后清理；临时数据库及样本由测试重新生成 |
| PDF 预览图、临时响应和重复副本 | 确认正式输出仍存在、没有代码或文档引用后清理；重复文件须核对内容哈希 |
| 模型、数据集、向量缓存、上传目录和数据库 | 按运行或实验数据管理，不能仅凭名称含 `cache` 就删除 |

不要整体清空 `tmp`，其中可能有尚未交付的产物或复现脚本。先检查具体目录、链接及在用进程，
保留正式输出和实验记录；遇到无法读取的目录先跳过，不自动改写权限。
已执行清理的范围与统计见[存储与代码审计](storage-and-code-audit-2026-09-07.md)。
