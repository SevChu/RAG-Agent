# 参与开发

Agentic 当前是本地单用户研究项目。提交改动前，请先阅读[技术文档](docs/technical/README.md)和[开发与测试](docs/technical/development-and-testing.md)。

## 开发原则

- 一个改动聚焦一个可验证目标。
- 保持资料空间之间的数据隔离和来源可追溯。
- 不把上传资料中的指令当作系统指令。
- API、数据库、Qdrant Payload 和评测契约的变化必须说明兼容性。
- 模型、阈值和评分算法变化必须记录数据版本、配置与复现实验。
- 不使用最终 test split 调参。
- 不下载未经批准的数据集或模型。
- 不提交密钥、用户资料、数据库、向量库、本地模型和真实评测输出。

## 本地质量检查

后端：

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m mypy app
```

前端：

```powershell
cd D:\Agentic\frontend
npm run test:unit -- --run
npm run type-check
npm run lint
npm run build
```

当前 `npm run lint` 会自动修复文件；在存在未提交改动时先检查 Git 状态。

## 数据库与 API 变更

- ORM 变更必须附 Alembic 迁移和迁移测试。
- 不通过删除 `data/app.db` 代替迁移。
- 1.0.x 应保持 `/api/courses` 等冻结契约向后兼容。
- Pydantic Schema 变化需要同步前端 `src/types/api.ts`。
- SSE 事件变化需要同步 `docs/technical/api-reference.md`。

## 测试要求

- 外部模型和搜索使用 Fake Gateway 或 MockTransport，不发送真实请求。
- 测试必须隔离正式 `.env`、SQLite、Qdrant 和上传目录。
- Bug 修复应增加能复现问题的回归测试。
- 解析、检索或评分改进应同时报告质量与性能影响。
- UI 变化除自动检查外，还应验收桌面、折叠侧边栏和移动端。

## 发布与外部操作

创建远程仓库、推送、发布 Release、下载公开数据、发送真实资料到模型供应商等操作，需要项目负责人明确批准。许可证和第三方资产再分发范围也必须在公开发布前确认。
