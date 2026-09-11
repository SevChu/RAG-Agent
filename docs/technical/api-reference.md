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

当前工作区 OpenAPI 包含 26 个路径，其中 7 个新增路径属于v1.3.0 智能体管理能力；应用版本为 1.3.0，最终推送审批已通过。

### 智能体配置（Week 7 Day 2）

- GET/POST /api/agent-profiles：列表、创建；
- GET /api/agent-profiles/options：模型与评测配置选项；
- GET/PATCH /api/agent-profiles/{profile_id}：详情、配置/身份更新与启停；
- POST /api/agent-profiles/{profile_id}/copy：复制；
- GET /api/agent-profiles/{profile_id}/revisions：版本列表；
- GET /api/agent-profiles/{profile_id}/revisions/{revision_id}：指定版本；
- POST /api/agent-profiles/{profile_id}/restore：从旧配置追加新版本。

修改与恢复必须携带 expected_row_version；历史 revision 不可覆盖。
完整请求、响应、分页、错误码及用途约束见[Day 2 接口契约](../deliverables/week-07-day-02.md)。
Day 3 已接入会话创建、问答和 SSE；未绑定智能体的旧会话保持兼容路径，新增契约见第 13 节。

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


## 13. 会话固定智能体版本（Week 7 Day 3）

`POST /api/courses/{course_id}/conversations` 和 `POST /api/quick-conversations`
可传 `{"title":"可选标题","agent_profile_id":"智能体 UUID"}`。省略/null 创建兼容会话。
服务端在创建时选择当前 revision 并固定；响应、列表、详情增加可空字段
`agent_profile_id`、`agent_profile_revision_id`。不接受客户端指定 revision 或原地切换。

资料回答的同步与 stream 请求也可传 `agent_profile_id`，仅用于未传 `conversation_id`
时自动创建绑定会话。已有会话同时提交非空 `agent_profile_id` 返回 400，必须新建会话。
绑定后的 `model` 可省略或等于快照模型；冲突返回 400，旧会话仍允许按白名单选模型。
会话创建和两类生成请求拒绝未知字段（422），避免拼错绑定字段后静默创建兼容会话。

每轮先验证智能体启用、版本归属/哈希、供应商白名单/凭据和允许空间存在性；
失败在 SSE start 前返回普通 HTTP 错误。停用返回 409，依赖无效一般为 400，
缺凭据为 503，资源不存在为 404。历史查询不需要这些依赖继续有效。
检查覆盖请求开始时的状态，不会强制中断已经开始的外部调用。

权限交集：服务端总开关 AND revision 工具权限 AND 本轮允许。资料 `course_only`
和总结始终不联网；快速对话从不查询资料索引。`document_ids` 只缩小当前空间的资料范围。
绑定试卷续写如果与本轮资料/外部来源范围冲突会明确失败，不从旧工件绕过范围限制。

上下文和各任务检索数量/字符预算取服务端与 revision 中较小者；top_k 再受 candidate_k
限制。问答证据相似度下限取较大者。总结/组卷保留原有按任务选取证据和质量检查的语义，
不把问答相似度门改造成总结或组卷的生产评分器。

资料回答 JSON、资料/快速对话 SSE 的 start 与 complete 增加 `agent_runtime`：

```json
{
  "profile_id": "智能体 UUID",
  "revision_id": "固定版本 UUID",
  "revision_number": 1,
  "config_sha256": "64 位 SHA-256",
  "provider": "供应商 ID",
  "requested_model": "固定的模型名称",
  "actual_models": ["本轮生成网关实际返回的模型标识"]
}
```

start 的 actual_models 为空；complete 按实际完成的生成调用去重记录（含改写、计划、修复）。
无模型调用的拒答/试卷工件重放也为空；顶层 model 继续保留原响应含义。
该对象同时保存到助手消息 `retrieval.agent_runtime`，历史查询可恢复。
兼容会话的 agent_runtime 为 null；旧消息缺字段时读取为 null。流式 error 仍沿用原契约，
失败或中断不保存完整消息交换，不伪造 complete。

配置固定不冻结资料、服务器上限或供应商实现；不保证回答逐字重现。
评测引用只保存在配置中，在线链路不读取评测注册表、运行模型或使用最终 test。
详细测试及限制见 [Day 3 报告](../deliverables/week-07-day-03.md)。

## 14. 删除智能体（2026-09-10 补充）

`DELETE /api/agent-profiles/{profile_id}?expected_row_version=1`：逻辑删除，成功 HTTP 200，
响应为 `{"data":null}`（沿用 APIResponse 信封）。参数必填且为正整数；版本过期 409，
非法/缺失参数 422，不存在 404。重复删除成功且不再次递增版本。

AgentProfile 响应新增可空 deleted_at。删除时记录时间、停用并递增 row_version，不追加
revision；所有列表（包括 enabled=false）均先排除已删除身份再分页。详情和历史版本仍可读。
删除不要求当前模型/评测配置有效，原名称仍保留且受唯一约束。

删除后编辑、复制、启用、恢复、新建或继续会话均返回 409；历史查询保持。正在执行的生成
不被强行中止。迁移为 20260910_06，管理接口现有 10 个操作，未提供硬删除或回收站。

## 15. 产品与科研模式

GET /api/agent-profiles/options 新增 edition=product|research。产品模式 evaluation_profiles=[]，
不会打开研究注册表；科研模式返回冻结引用选项。产品新建时非空研究引用返回 400；编辑只能
保留原引用或清空，不能添加/替换。历史、启停、恢复和运行不需要评测资源；复制省去研究引用。
两版业务接口、会话绑定及迁移链相同，无需为每个智能体安装 Benchmark。
