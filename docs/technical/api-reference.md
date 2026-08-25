# API 参考

## 1. 基础约定

- 默认后端：`http://127.0.0.1:8000`
- API 前缀：`/api`
- JSON 编码：UTF-8
- 资源 ID：UUID
- 时间：后端返回 ISO 8601 日期时间
- 认证：1.0.0 未实现，只适用于可信本机或受控网络
- 交互式文档：`GET /docs`
- OpenAPI JSON：`GET /openapi.json`

除 SSE 外，成功和失败都使用统一响应包。

成功：

```json
{
  "data": {},
  "error": null
}
```

失败：

```json
{
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "..."
  }
}
```

## 2. 接口总览

当前 OpenAPI 包含 19 个路径。

### 系统与模型

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/llm/config` | 返回模型、供应商、上下文和联网配置，不含 Key |
| GET | `/api/llm/token-usage` | 按模型读取累计 Token |
| DELETE | `/api/llm/token-usage` | 清空全部 Token 事件并返回零值汇总 |

### 资料空间

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/courses` | 创建资料空间 |
| GET | `/api/courses` | 列出资料空间 |
| GET | `/api/courses/{course_id}` | 获取资料空间 |
| DELETE | `/api/courses/{course_id}` | 删除资料空间、资料、向量和空间对话 |

### 资料

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/courses/{course_id}/documents` | multipart 上传资料 |
| GET | `/api/courses/{course_id}/documents` | 列出空间资料 |
| POST | `/api/courses/{course_id}/documents/bulk-delete` | 原子批量删除 1～500 份资料 |
| GET | `/api/documents/{document_id}` | 获取资料详情 |
| GET | `/api/documents/{document_id}/status` | 获取资料处理状态 |
| POST | `/api/documents/{document_id}/reindex` | 重新处理/重新索引 |
| DELETE | `/api/documents/{document_id}` | 删除单份资料及向量 |

### 会话

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/conversations` | 列出全部资料空间对话摘要 |
| GET | `/api/quick-conversations` | 列出快速对话 |
| POST | `/api/quick-conversations` | 创建快速对话 |
| GET | `/api/quick-conversations/{conversation_id}` | 获取快速对话及消息 |
| DELETE | `/api/quick-conversations/{conversation_id}` | 删除快速对话 |
| GET | `/api/courses/{course_id}/conversations` | 列出一个空间的对话 |
| POST | `/api/courses/{course_id}/conversations` | 创建空间对话 |
| GET | `/api/courses/{course_id}/conversations/{conversation_id}` | 获取空间对话及消息 |
| DELETE | `/api/courses/{course_id}/conversations/{conversation_id}` | 删除空间对话 |

### 检索与生成

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/courses/{course_id}/retrieval/search` | 资料空间范围 Dense 检索 |
| POST | `/api/courses/{course_id}/answers` | 同步执行问答、总结或组卷 |
| POST | `/api/courses/{course_id}/answers/stream` | SSE 执行问答、总结或组卷 |
| POST | `/api/quick-conversations/{conversation_id}/messages/stream` | SSE 快速对话 |

## 3. 系统与模型

### 3.1 健康检查

```http
GET /api/health
```

该接口不使用统一响应包：

```json
{
  "status": "ok",
  "environment": "development"
}
```

它只证明 FastAPI 进程可响应，不会主动加载本地模型、检查上游 API Key 或验证 Qdrant 数据完整性。

### 3.2 模型配置

```http
GET /api/llm/config
```

关键字段：

| 字段 | 含义 |
|---|---|
| `provider` | 第一组兼容供应商 ID |
| `base_url` | 第一组 Base URL |
| `model` | 后端默认模型 |
| `available_models` | 四组白名单合并去重后的模型 |
| `configured` | 默认模型所属供应商是否已配置 |
| `answer_styles` | `concise`、`balanced`、`detailed` |
| `rag_context_max_messages` | 空间对话历史消息上限 |
| `quick_chat_context_max_messages` | 快速对话历史消息上限 |
| `external_search_enabled` | 服务端联网总开关 |
| `providers[]` | 供应商 ID、名称、Base URL、模型、配置状态和环境变量名 |

供应商对象故意不包含 API Key。

### 3.3 Token 统计

```http
GET /api/llm/token-usage
DELETE /api/llm/token-usage
```

返回 `models[]` 和 `total`，每项包含：

- `model`
- `input_cache_hit_tokens`
- `input_cache_miss_tokens`
- `input_tokens`
- `output_tokens`
- `total_tokens`

只有上游返回可解析 usage 的调用才进入统计。记录在收到上游响应后独立提交，即使后续结构校验失败，该次已经产生费用的 usage 仍会保留。DELETE 只清零 Token 事件，不删除资料、向量或对话。

## 4. 资料空间

### 4.1 创建

```http
POST /api/courses
Content-Type: application/json
```

```json
{
  "name": "项目规范",
  "description": "架构文档、需求和测试资料"
}
```

约束：

- `name`：1～100 字符，数据库中全局唯一；
- `description`：可空文本；
- 同名返回 HTTP 409。

### 4.2 读取

`CourseRead`：

```json
{
  "id": "uuid",
  "name": "项目规范",
  "description": "...",
  "created_at": "2026-08-25T10:00:00",
  "updated_at": "2026-08-25T10:00:00"
}
```

### 4.3 删除

删除空间前，后端先暂存本地目录并清理该空间的全部 Qdrant Point；只有向量清理成功才删除 SQLite 记录。成功返回：

```json
{
  "data": {
    "id": "uuid",
    "deleted": true
  },
  "error": null
}
```

## 5. 资料

### 5.1 上传

```http
POST /api/courses/{course_id}/documents
Content-Type: multipart/form-data
```

表单字段只有 `file`。允许扩展名：`.pdf`、`.pptx`、`.docx`、`.md`、`.txt`。

PowerShell 示例：

```powershell
curl.exe -X POST `
  -F "file=@D:\materials\guide.pdf" `
  http://127.0.0.1:8000/api/courses/{course_id}/documents
```

接口返回 201 和初始 Document 状态。默认情况下，返回后立即在进程内调度后台索引。

`DocumentRead`：

| 字段 | 含义 |
|---|---|
| `id`、`course_id` | 资料和空间 UUID |
| `original_name` | 原文件名 |
| `file_type`、`file_size` | 类型与字节数 |
| `sha256` | 内容哈希 |
| `status` | `pending`、`processing`、`completed`、`failed` |
| `error_message` | 失败时的用户可理解原因 |
| `progress_percent` | 0～100 |
| `processing_stage` | `waiting`、`preparing`、`parsing`、`chunking`、`embedding`、`storing`、`completed`、`failed` |
| `progress_detail` | 当前步骤说明 |
| `created_at`、`updated_at` | 时间 |

同一资料空间中相同 SHA-256 返回 409；伪装格式、损坏容器、空文件、非法文本或超限文件返回相应错误。

### 5.2 重新索引

```http
POST /api/documents/{document_id}/reindex
```

成功后资料回到等待状态并调度处理。重索引会替换旧 Point，不会叠加重复向量。正在 `pending/processing` 的资料不能重复提交。

### 5.3 批量删除

```json
{
  "document_ids": ["uuid-1", "uuid-2"]
}
```

约束：1～500 个不重复 ID，且全部属于 URL 中的 `course_id`。任一 ID 无效时整批失败。

## 6. 会话与消息

创建两类会话使用同一请求结构：

```json
{
  "title": "可选标题，最多 120 字符"
}
```

空间对话必须绑定存在的 `course_id`；快速对话的 `course_id` 为 null。响应摘要包含 ID、标题、创建/更新时间和最后消息时间；空间对话还包含 `course_id` 与 `course_name`。

详情响应的 `messages[]` 按 `sequence_number` 排序，每条包含：

- `role`：`user` 或 `assistant`；
- `status`：`completed`、`pending`、`failed`、`interrupted`；
- `content`；
- `answer_status`、`answer_style` 和 `model`；
- `citations[]`；
- `retrieval` 诊断 JSON；
- `usage`、`elapsed_ms` 和 `created_at`。

1.0.0 的正常问答路径会保存已完成交换。流式连接在完成前断开时不会保存半条回答。

## 7. 检索

```http
POST /api/courses/{course_id}/retrieval/search
```

```json
{
  "query": "系统如何处理扫描 PDF？",
  "top_k": 5,
  "document_ids": null
}
```

约束：

- `query`：1～1000 字符且不能只含空白；
- `top_k`：1～20，默认 5；
- `document_ids`：可选，最多 50 个且不能重复；
- 显式指定的资料必须全部处于 `completed`。

当前公开检索接口返回 Dense 检索结果，`retrieval_mode` 为 `dense`。每个 Hit 包含 rank、score、Point ID、Document ID、Chunk 序号、正文、文件名、类型、章节、页码、幻灯片和行号。

智能体内部问答会在更宽的 Dense 候选上继续执行 BGE Reranker 和证据门控，因此与该基础检索接口的排名不完全相同。

## 8. 同步资料空间生成

```http
POST /api/courses/{course_id}/answers
```

请求：

```json
{
  "question": "总结第二章并列出易错点",
  "answer_style": "balanced",
  "answer_scope": "course_and_external",
  "document_ids": null,
  "conversation_id": null,
  "model": null
}
```

字段：

| 字段 | 约束 | 说明 |
|---|---|---|
| `question` | 1～2000 字符 | 普通问题、总结或组卷自然语言指令 |
| `answer_style` | concise/balanced/detailed | 回答详细度 |
| `answer_scope` | course_and_external/course_only | 普通问答和组卷的来源范围 |
| `document_ids` | 最多 50 个唯一 UUID | 限制空间内资料范围 |
| `conversation_id` | 可空 UUID | 空时后端创建空间对话 |
| `model` | 可空、1～120 字符 | 空时使用后端默认模型 |

响应 `CourseAnswerRead`：

- 会话、用户消息和助手消息 ID；
- 原问题、答案、`answered/insufficient_evidence` 状态；
- 回答风格、范围、模型和耗时；
- 资料与外部 `citations[]`；
- `retrieval`：候选数、证据数、设备、改写、上下文、路由、总结计划或组卷计划；
- `usage` 和 `external_search`；
- `task_type`：`question`、`summary` 或 `exam`。

### 引用结构

资料引用 `source_type=course`，携带 document/chunk、分数、证据角色、文件、章节和位置。外部引用 `source_type=external`，携带标题、发布者、URL 和访问时间。正文引用编号分别通过生成契约验证，未出现在可用来源集合中的编号会被拒绝或清洗。

## 9. SSE 资料空间生成

```http
POST /api/courses/{course_id}/answers/stream
Accept: text/event-stream
```

请求体与同步接口相同。

| 事件 | 数据 | 顺序与语义 |
|---|---|---|
| `start` | `conversation_id`、`model`、`context_max_messages` | 首个事件 |
| `delta` | `{text}` | 答案小段；当前由完整答案切分，不是上游原生 token 流 |
| `citations` | `{citations: [...]}` | 资料空间流在持久化前发送 |
| `complete` | 完整 `CourseAnswerRead` | 持久化成功后的终态 |
| `error` | `{code, message}` | 业务错误或受保护的内部错误 |

客户端应只在 `complete` 后把本轮视为持久化成功。用户停止接收或网络断开后，后端检测到断开便结束事件生成；若尚未进入持久化步骤，本轮不会出现在历史记录中。

## 10. SSE 快速对话

```http
POST /api/quick-conversations/{conversation_id}/messages/stream
```

```json
{
  "message": "检索并说明某个近期版本变化",
  "model": null,
  "web_search": true
}
```

- `message`：1～4000 字符；
- `web_search` 默认 true；
- 不访问资料空间或 Qdrant；
- start 事件额外返回 `web_search_enabled`；
- 没有独立 citations 事件，外部引用在 complete 事件中返回；
- complete 包含消息 ID、模型、usage、耗时、上下文数、引用和外部搜索诊断。

## 11. 错误码

| HTTP | code | 典型原因 |
|---:|---|---|
| 400 | `INVALID_INPUT` | 内容为空、格式内容非法或业务输入不合法 |
| 404 | `NOT_FOUND` | 资料空间、资料或会话不存在 |
| 409 | `CONFLICT` | 同名空间、同空间重复内容、重复索引或状态冲突 |
| 413 | `FILE_TOO_LARGE` | 超过 `MAX_UPLOAD_MB` |
| 415 | `UNSUPPORTED_FILE_TYPE` | 不支持或内容与扩展名不匹配 |
| 422 | `VALIDATION_ERROR` | Pydantic/FastAPI 请求校验失败 |
| 502 | `LLM_SERVICE_ERROR` | 上游网络、超时、Key、限额或响应异常 |
| 502 | `LLM_OUTPUT_ERROR` | 生成结果不满足 JSON、引用或任务硬契约 |
| 503 | `INDEX_STORAGE_ERROR` | 本地模型或 Qdrant 无法安全读写/清理 |
| 503 | `LLM_NOT_CONFIGURED` | 模型不在白名单或所属供应商缺少 Key |

SSE 接口在 HTTP 连接已经建立后，会通过 `event: error` 返回同类 code，而不是改变 HTTP 状态。

## 12. 兼容与演进规则

- 1.0.0 的 `/courses`、`course_id` 和 DTO 字段属于已冻结兼容契约。
- 后续内部重命名为 ResourceSpace 时，应保留旧路径或提供清晰的版本化迁移。
- 新增响应字段应保持向后兼容；删除或改变字段语义需要 API 大版本。
- 前端 TypeScript 类型必须与 Pydantic Schema 同步更新。
- OpenAPI 是接口清单的机器可读来源，但 SSE 事件需要继续在本文维护。
