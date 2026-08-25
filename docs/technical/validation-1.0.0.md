# 1.0.0 文档与回归验证记录

验证日期：2026-08-25

## 验证范围

- 新增技术文档的本地链接与文件存在性；
- FastAPI OpenAPI 路径清单；
- 解析、知识库审计和评测 CLI 的 `--help`；
- 后端 pytest、Ruff 和 Mypy；
- 前端 Vitest、TypeScript 和 Vite 生产构建；
- 前端非写入 Oxlint/ESLint、锁文件一致性、运行时元数据与隐私边界；
- Git 状态与临时文件清理。

本轮没有调用真实生成模型、没有触发 Web Search、没有下载公开数据或模型、没有创建 Git 提交/Tag，也没有推送 GitHub。

## 结果

| 检查 | 结果 |
|---|---|
| 后端 pytest | 元数据统一后复验：`231 passed in 12.29s` |
| Ruff | `All checks passed!` |
| Mypy strict（`app`） | `Success: no issues found in 93 source files` |
| 前端 Vitest | 2 个测试文件、10 项测试通过 |
| 前端 vue-tsc | 通过 |
| Vite production build | 通过，1748 modules transformed |
| Oxlint / ESLint | 直接运行不带 `--fix` 且不写缓存的检查，均通过 |
| uv lock | `uv lock --check` 通过 |
| 运行时元数据 | OpenAPI 标题 `Agentic`，版本 `1.0.0` |
| FastAPI OpenAPI | 19 个路径，与 API 文档清单一致 |
| Markdown 本地链接 | 首轮 12 个新增 Markdown 文件无断链；本记录随后新增且不引入本地依赖链接 |
| CLI 入口 | ingestion inspect、knowledge inspect、knowledge audit、week5 evaluation help 均可加载 |
| 隐私发布审计 | 仅 `data/.gitkeep` 被跟踪；资料、对话数据库、测试集、模型和 `.env` 均未进入索引；疑似密钥扫描为 0 |

## pytest 临时目录说明

首轮后端测试使用系统 Temp，收集 231 项后出现 110 个统一的 `WinError 5` setup error，原因是当前 Windows 用户无法访问：

```text
C:\Users\26415\AppData\Local\Temp\pytest-of-26415
```

这些错误全部发生在 `tmp_path` fixture 创建阶段，不是业务断言失败。随后使用工作区内全新专用 `--basetemp` 且关闭 pytest cache provider 重跑，231 项全部通过。专用临时目录在测试后已删除。

## 未执行项

- 没有直接运行含 `--fix` 的 `npm run lint`；改为分别运行不写入的 Oxlint 和 ESLint，两项均通过。后续建议增加正式的 `lint:check` 脚本。
- 真实浏览器视觉回归：本轮任务为技术文档整理，未重新执行页面视觉验收。
- 真实供应商 API：没有验证 Key、额度、地域、模型 ID 或各模型 JSON 模式兼容性。
- 公开 Benchmark：仍未获用户批准下载。

## 发布前仍需重跑

项目名、仓库名、许可证和版本元数据现已确认并对齐。创建最终提交前仍应重新执行完整发布门禁；GitHub Release 应引用发布提交上的验证结果，而不是仅引用本地脏工作区结果。
