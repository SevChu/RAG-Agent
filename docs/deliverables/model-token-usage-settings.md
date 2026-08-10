# 设置页模型 Token 累计统计验收说明

## 1. 交付目标

设置页新增持久化 Token 用量面板，按上游实际返回的模型名分别展示：

- 输入 Token 合计；
- 输入 Token 中的缓存命中量；
- 输入 Token 中的缓存未命中量；
- 输出 Token；
- 输入与输出总计。

统计覆盖普通问答、快速对话、总结、组卷、内部规划/审查/局部修复，以及真实外部搜索模型调用。
一次业务请求如果触发多次上游调用，每次有 usage 的响应都会独立计入，避免只统计最终回答而漏掉
内部消耗。

## 2. 统计口径与边界

1. OpenAI-compatible 响应读取 `prompt_cache_hit_tokens`、
   `prompt_cache_miss_tokens` 和 `completion_tokens`。旧式响应没有缓存明细时，全部输入按缓存未命中
   记录，不虚构命中量。
2. Anthropic-compatible 外部搜索读取 `cache_read_input_tokens` 作为缓存命中，普通输入与
   `cache_creation_input_tokens` 作为缓存未命中。
3. 以响应中的真实 `model` 字段归类，而不是只按请求模型名归类。
4. 只累计上游明确返回 usage 的调用。无法取得 usage 的失败请求不会估算；本功能上线前的历史调用
   不会追溯补记。
5. 本统计独立于 `output/week-04/day-05/token-ledger.json` 的审计预算账本；设置页 Reset 不会更改
   审计账本。

## 3. 数据与接口

- 新表：`token_usage_events`，每个取得 usage 的上游响应保存一条事件；事件式写入避免并发读改写
  导致累计丢失。
- `GET /api/llm/token-usage`：返回配置模型与历史模型的分组累计，以及全部模型合计。
- `DELETE /api/llm/token-usage`：清空统计事件并返回归零后的模型列表。
- Reset 只删除 Token 统计，不删除课程、资料、向量、对话或消息；前端执行前必须二次确认。

## 4. 主要改动

| 文件 | 作用 |
|---|---|
| `backend/app/models/token_usage.py` | 单次模型用量事件模型 |
| `backend/app/token_usage/service.py` | 持久化、按模型聚合与清零 |
| `backend/app/generation/client.py` | 普通模型响应缓存用量解析与记录 |
| `backend/app/external_search/client.py` | 外部搜索模型响应缓存用量解析与记录 |
| `backend/app/api/routes/token_usage.py` | 设置页读取和清零 API |
| `backend/migrations/versions/20260810_04_add_token_usage_events.py` | 新表迁移 |
| `frontend/src/views/SettingsView.vue` | 分模型展示、合计和确认式 Reset |
| `backend/tests/test_token_usage.py` | 累计、空模型、接口与清零回归 |

## 5. 验收步骤

### 5.1 应用迁移并启动

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd D:\Agentic\frontend
npm run dev
```

### 5.2 页面验收

1. 打开 `http://127.0.0.1:5173/settings`。
2. 确认“累计 Token 消耗”按模型显示输入、缓存命中、缓存未命中、输出和合计；从未使用的可选模型
   显示为 0。
3. 在快速对话或课程助手中完成一次真实模型请求，再返回设置页或刷新页面；对应模型的数字应增加，
   且 `输入 = 缓存命中 + 缓存未命中`、`合计 = 输入 + 输出`。
4. 切换模型并完成一次请求；设置页应分别保留两个模型的统计，而不是合并到当前模型。
5. 点击 `Reset（清零）`，先取消确认，数字不得变化；再次点击并确认，所有模型数字应归零。
6. 清零后检查原课程、资料和对话仍然存在；重启前后端后统计仍保持为 0，随后新调用重新开始累计。

## 6. 自动验证

- Token 服务的同模型累加、跨模型分组、零用量模型与清零；
- GET/DELETE API 的字段恒等式和数据库清空；
- DeepSeek 普通生成缓存明细解析；
- Anthropic-compatible 外部搜索缓存读取/创建明细解析；
- Alembic 从 base 升级到 head、模型一致性检查和降级回 base；
- 后端全量 Pytest、Ruff、Mypy strict；
- 前端 Vitest、Lint、Vue/TypeScript 类型检查和生产构建。

本次实施结果：后端 217 项 Pytest 全部通过；Ruff 全量通过；Mypy strict 检查 93 个 `app/scripts`
源文件通过；前端 10 项 Vitest、Oxlint/ESLint、Vue/TypeScript 类型检查和生产构建全部通过；
`git diff --check` 通过。迁移已应用到当前本地开发数据库，版本为 `20260810_04 (head)`。

用户于 2026-08-10 完成验收，并授权补写工程日志和创建本地 Git 提交；不自动推送远端。
