# 配置参考

## 1. 配置加载

后端使用 Pydantic Settings，按进程当前目录检查 `.env` 和 `../.env`，并忽略未声明的额外变量。推荐始终从 `backend` 目录启动后端，并把真实配置保存在项目根目录 `D:\Agentic\.env`：

```powershell
cd D:\Agentic
Copy-Item .env.example .env

cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

操作系统环境变量的优先级高于 dotenv 文件。测试会显式覆盖敏感设置，避免意外读取本地 API Key。

前端只读取 `frontend/.env` 中以 `VITE_` 开头的变量。API Key 永远不应放入前端环境变量，也不会通过 `/api/llm/config` 返回浏览器。

## 2. 应用基础配置

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `APP_NAME` | `Agentic` | FastAPI/OpenAPI 标题与项目品牌 |
| `APP_ENV` | `development` | 健康检查返回的环境名 |
| `DEBUG` | `true` | FastAPI Debug 模式 |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 逗号分隔的允许来源 |

公开部署前必须关闭 Debug，并把 CORS 缩小到实际前端域名。

## 3. 生成模型配置

### 3.1 通用生成参数

| 环境变量 | 默认值 | 约束与作用 |
|---|---:|---|
| `LLM_PROVIDER` | `deepseek` | 第一组兼容供应商 ID；1.0.0 应保留 `deepseek` |
| `LLM_MODEL` | `deepseek-v4-flash` | 后端默认模型，必须出现在某个供应商模型白名单中 |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `90` | 单次 Chat Completions 超时，必须大于 0 |
| `LLM_MAX_OUTPUT_TOKENS` | `1600` | 上游 `max_tokens` |
| `LLM_TEMPERATURE` | `0.2` | 生成温度，范围 0～2 |

生成客户端会向 `{BASE_URL}/chat/completions` 发送非流式请求，使用 Bearer API Key。HTTP 429、5xx、网络异常和超时最多重试一次。结构化生成会追加 JSON 输出要求并发送 `response_format={"type":"json_object"}`；DeepSeek 还会发送 `thinking={"type":"disabled"}`，其他供应商不会携带该私有参数。

### 3.2 供应商变量

| 供应商 | Base URL 变量与默认值 | Key 变量 | 模型白名单变量 |
|---|---|---|---|
| DeepSeek | `LLM_BASE_URL=https://api.deepseek.com` | `LLM_API_KEY` | `LLM_AVAILABLE_MODELS` |
| Qwen | `QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1` | `QWEN_API_KEY` | `QWEN_MODELS` |
| Kimi | `KIMI_BASE_URL=https://api.moonshot.cn/v1` | `KIMI_API_KEY` | `KIMI_MODELS` |
| GLM | `GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4` | `GLM_API_KEY` | `GLM_MODELS` |

每组接口只有在 **API Key 非空且模型列表非空** 时才显示为已配置。模型列表以英文逗号分隔并自动去除空白和重复项：

```dotenv
QWEN_API_KEY=your-key
QWEN_MODELS=qwen-model-a,qwen-model-b
```

模型字符串必须与供应商实际支持的模型 ID 完全一致。不要把 `/chat/completions` 追加到 Base URL。

路由规则是“按模型名在各供应商白名单中的归属决定 Base URL 和 API Key”，供应商检查顺序为 DeepSeek、Qwen、Kimi、GLM。不要在两组白名单中重复配置相同模型 ID，否则会命中靠前的供应商。

Qwen 的 API Key 和 Base URL 有地域对应关系；如果使用非北京区域，必须同时替换为该区域官方端点。供应商官方说明：

- [Qwen Model Studio Base URL](https://help.aliyun.com/en/model-studio/base-url)
- [Kimi API 概览](https://platform.kimi.com/docs/overview)
- [GLM OpenAI SDK 兼容说明](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)

### 3.3 模型切换语义

- 修改 `.env`、Base URL、Key 或模型白名单：必须重启后端。
- 在前端切换已经配置的模型：不需要重启后端。
- 前端当前选择只保存在浏览器会话状态中，刷新页面后恢复 `LLM_MODEL`。
- 后端拒绝不在任何白名单中的模型。
- `/api/llm/config` 返回供应商名称、Base URL、模型、配置状态和所需环境变量名，但不返回 Key。

## 4. RAG 参数

| 环境变量 | 默认值 | 作用 |
|---|---:|---|
| `RAG_ANSWER_TOP_K` | `6` | 普通问答重排后返回证据数 |
| `RAG_ANSWER_CANDIDATE_K` | `20` | 普通问答 Dense 候选数 |
| `RAG_SUMMARY_TOP_K` | `12` | 总结最终证据数 |
| `RAG_SUMMARY_CANDIDATE_K` | `40` | 总结候选数 |
| `RAG_SUMMARY_MAX_SOURCES` | `10` | 总结最多来源数 |
| `RAG_SUMMARY_CONTEXT_MAX_CHARS` | `8000` | 总结证据上下文字符预算 |
| `RAG_EXAM_TOP_K` | `12` | 组卷最终证据数 |
| `RAG_EXAM_CANDIDATE_K` | `40` | 组卷候选数 |
| `RAG_EXAM_MAX_SOURCES` | `10` | 组卷最多来源数 |
| `RAG_EXAM_CONTEXT_MAX_CHARS` | `8000` | 组卷证据上下文字符预算 |
| `RAG_MIN_SIMILARITY_SCORE` | `0.3` | 可进入回答的最低证据分数 |
| `RAG_CONTEXT_MAX_MESSAGES` | `6` | 资料空间对话最多历史消息数 |
| `RAG_CONTEXT_MAX_CHARS` | `6000` | 资料空间对话历史字符预算 |
| `QUICK_CHAT_CONTEXT_MAX_MESSAGES` | `10` | 快速对话最多历史消息数 |
| `QUICK_CHAT_CONTEXT_MAX_CHARS` | `8000` | 快速对话历史字符预算 |

候选数应不小于最终 Top-K。修改检索、阈值或上下文参数后，应在 validation split 上重新评估，不应直接使用最终 test split 调参。

## 5. Web Search

| 环境变量 | 默认值 | 作用 |
|---|---:|---|
| `EXTERNAL_SEARCH_ENABLED` | `true` | 服务端总开关 |
| `EXTERNAL_SEARCH_MODEL` | 空 | 专用于 DeepSeek Web Search 的模型；空时使用 DeepSeek 白名单第一项 |
| `EXTERNAL_SEARCH_TIMEOUT_SECONDS` | `60` | 搜索调用超时 |
| `EXTERNAL_SEARCH_MAX_USES` | `1` | 单次搜索允许的工具调用上限 |
| `EXTERNAL_SEARCH_MAX_RESULTS` | `6` | 清洗后最多保留来源数 |
| `EXTERNAL_SEARCH_TRIGGER_SCORE` | `0.55` | 资料覆盖不足时触发外部搜索的阈值 |

当前 Web Search 适配器是 DeepSeek 专用能力，并不是所有 OpenAI-compatible 供应商的通用接口。若最终回答模型是 Qwen、Kimi 或 GLM，搜索阶段仍会改用 `EXTERNAL_SEARCH_MODEL` 或 DeepSeek 白名单第一项。因此启用联网功能时仍需有效的 DeepSeek 配置。

“仅空间资料”会强制关闭外部搜索。快速对话还提供每轮 `web_search` 开关。

## 6. 存储与本地模型

| 环境变量 | 默认值（从 `backend` 启动时） | 作用 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///../data/app.db` | SQLite 数据库 |
| `QDRANT_PATH` | `../data/qdrant` | Qdrant Local 数据目录 |
| `QDRANT_COLLECTION_NAME` | `knowledge_chunks_v1` | 向量 Collection 名 |
| `UPLOAD_DIR` | `../data/uploads` | 原始上传文件根目录 |
| `PADDLE_OCR_BASE_DIR` | `../data/models/paddleocr` | PaddleOCR 本地模型根目录 |
| `EMBEDDING_MODEL_PATH` | `../data/models/embedding/bge-m3` | BGE-M3 模型目录 |
| `EMBEDDING_DEVICE` | `auto` | `auto`、`cuda` 或 `cpu` |
| `EMBEDDING_BATCH_SIZE` | `8` | Embedding 批量大小 |
| `RERANKER_MODEL_PATH` | `../data/models/reranker/bge-reranker-v2-m3` | Reranker 模型目录 |
| `RERANKER_DEVICE` | `auto` | `auto`、`cuda` 或 `cpu` |
| `RERANKER_BATCH_SIZE` | `4` | Reranker 批量大小 |
| `RERANKER_MAX_LENGTH` | `512` | Cross Encoder 最大序列长度 |
| `AUTO_INDEX_DOCUMENTS` | `true` | 上传后自动调度索引，并在启动时恢复未完成任务 |
| `MAX_UPLOAD_MB` | `100` | 单文件大小上限 |

Embedding 与 Reranker 在 `auto` 模式优先尝试 CUDA，CUDA 不可用或运行失败时回退 CPU，并在检索诊断中返回设备和回退原因。模型缺失时应用不会自动联网下载，而是返回明确错误。

Qdrant Collection 固定为 1024 维 Cosine 向量。如果修改 Embedding 模型或维度，不能继续复用旧 Collection；必须设计显式迁移或使用新 Collection 名并重新索引。

## 7. 前端配置

`frontend/.env`：

| 变量 | 默认示例 | 作用 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api` | REST 和 SSE API 根地址 |

修改前端环境变量后需要重启 Vite。生产构建时该值会被写入静态资源，不能依靠运行时修改 `.env` 改变已构建产物。

## 8. 推荐的最小本地配置

```dotenv
APP_NAME=Agentic
APP_ENV=development
DEBUG=true
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173

LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your-key
LLM_MODEL=your-model
LLM_AVAILABLE_MODELS=your-model

DATABASE_URL=sqlite+aiosqlite:///../data/app.db
QDRANT_PATH=../data/qdrant
UPLOAD_DIR=../data/uploads
PADDLE_OCR_BASE_DIR=../data/models/paddleocr
EMBEDDING_MODEL_PATH=../data/models/embedding/bge-m3
RERANKER_MODEL_PATH=../data/models/reranker/bge-reranker-v2-m3
```

## 9. 密钥与公开仓库

发布前确认以下文件或目录被忽略：

- 根目录 `.env` 和前端本地 `.env`；
- `data/app.db`、`data/uploads/`、`data/qdrant/`、`data/models/`；
- 本地评测运行输出和包含真实资料片段的报告；
- 日志、缓存、虚拟环境和 Node 依赖。

`.env.example` 只能包含空 Key、占位模型和公开 Base URL。
