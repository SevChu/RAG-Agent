# 第 1 周工程日志：工程骨架

## 周信息

| 项目 | 内容 |
|---|---|
| 计划周 | 第 1 周 |
| 周主题 | 工程骨架 |
| 当前状态 | 进行中 |
| 已完成计划日 | 计划日 1、计划日 2 |
| 实际开始日期 | 2026-07-30 |
| 当前分支 | `main` |

同一自然日可以完成多个计划日。本日志中的“计划日”表示里程碑顺序，不表示自然日期。

## 周目标

第 1 周计划建立可以持续扩展的全栈工程基础：

- 初始化 Vue 3 前端和 FastAPI 后端；
- 建立配置、日志、异常、测试和代码质量规范；
- 建立 SQLite 元数据模型与 Alembic 迁移；
- 完成课程空间基础流程；
- 完成安全文件上传的基础流程；
- 使前后端可以独立启动并具备可验证的最小闭环。

## 周验收标准

- 前后端均可以在本地独立启动；
- 后端健康检查可访问；
- 数据库可以从空库迁移到最新版本；
- 课程名称唯一、文件哈希范围和级联删除等规则受到数据库或业务层约束；
- 课程及文件基础 API 可以通过自动测试；
- 前端能够完成课程和资料管理的基础操作。

当前只完成到计划日 2，课程 HTTP API、文件上传和对应前端页面仍属于本周后续计划内容。

---

## 计划日 1：环境与工程初始化

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际完成日期 | 2026-07-30 |
| 状态 | 已完成 |
| 对应提交 | `256bc22` |

### 当日目标

- 检查现有开发环境；
- 初始化 Git 仓库；
- 安装并固定 Python 3.11；
- 初始化 FastAPI 后端；
- 初始化 Vue 3 前端；
- 建立根目录配置、忽略规则和基础目录；
- 确认前后端可以启动、测试和构建。

明确不实施：

- SQLite 业务模型；
- 课程管理和文件上传；
- 文档解析、Embedding 和 Qdrant；
- DeepSeek 模型调用；
- RAG、Agent、总结和出题。

### 完成内容

#### 开发环境

- 初始化 `main` 分支 Git 仓库；
- 安装 uv 0.12.0；
- 通过 uv 安装并固定 Python 3.11.15；
- 使用现有 Node.js 24.17.0 和 npm 11.13.0；
- 使用 Codex 环境提供的 Git 2.53.0 完成仓库操作。

#### 后端骨架

- 初始化 uv Python 应用；
- 安装 FastAPI、Pydantic Settings、orjson 和 structlog；
- 安装 pytest、pytest-asyncio、pytest-cov、Ruff、Mypy 和 httpx；
- 建立 `app/main.py` 应用入口；
- 建立环境变量配置入口；
- 增加 `/api/health` 健康检查；
- 增加最小后端测试。

#### 前端骨架

- 初始化 Vue 3、TypeScript 和 Vite；
- 启用 Vue Router、Pinia、Vitest、ESLint 和 Prettier；
- 安装 Element Plus、Axios、Markdown、代码高亮、公式渲染、内容净化和 SSE 相关依赖；
- 安装 Playwright 包，但未下载浏览器或编写端到端测试；
- 删除 Vue 默认演示页面；
- 建立项目启动页、基础主题和 Axios 请求入口；
- 增加最小前端冒烟测试。

#### 仓库规范

- 创建根目录 `.editorconfig`；
- 创建 `.gitattributes`，统一文本文件行尾；
- 创建 `.gitignore`；
- 创建不包含真实密钥的 `.env.example`；
- 保留 `data/` 目录，但忽略运行时数据；
- 将 DeepSeek 服务商、默认模型和可切换模型白名单写入配置结构。

### 关键设计与决策

1. 后端使用 uv 管理 Python 和锁定依赖，Python 固定为 3.11。
2. 前端使用计划中确定的 Vue 3 技术栈，不更换为其他前端框架。
3. DeepSeek 模型名称从环境变量读取，业务代码不写死模型。
4. `LLM_MODEL` 表示默认模型，`LLM_AVAILABLE_MODELS` 表示允许切换的白名单。
5. 真实 API Key 只允许出现在未提交的 `.env` 中。
6. 第一版启动页只表达模块规划，不伪造尚未实现的课程或资料数据。
7. 当前 PowerShell 策略会拦截 `npm.ps1`，项目命令使用 `npm.cmd`，不修改系统执行策略。

### 主要文件

| 文件 | 用途 |
|---|---|
| `.env.example` | 后端环境变量模板 |
| `.gitignore` | 密钥、依赖、构建产物和运行数据忽略规则 |
| `backend/pyproject.toml` | Python 依赖与质量工具配置 |
| `backend/app/core/config.py` | 环境配置入口 |
| `backend/app/main.py` | FastAPI 应用和健康检查 |
| `frontend/package.json` | 前端依赖和运行脚本 |
| `frontend/src/App.vue` | 前端应用外壳 |
| `frontend/src/views/HomeView.vue` | 第一阶段启动页 |
| `frontend/src/api/http.ts` | Axios 基础客户端 |

### 验证结果

| 检查 | 结果 |
|---|---|
| 后端 pytest | 1 项通过 |
| Ruff | 通过 |
| Mypy | 通过 |
| 前端 Vitest | 1 项通过 |
| ESLint/Oxlint | 通过 |
| TypeScript 类型检查 | 通过 |
| Vite 生产构建 | 通过 |
| npm 完整依赖审计 | 0 个已知漏洞 |
| 后端健康接口 | 返回 `status=ok` |
| 前端本地访问 | HTTP 200 |

### 问题及处理

#### Vue 脚手架依赖版本冲突

Vue 脚手架生成的 `oxlint` 与 `eslint-plugin-oxlint` 小版本不一致，npm 拒绝安装。将两者固定到兼容版本后正常安装，没有使用 `--force` 或 `--legacy-peer-deps` 绕过依赖解析。

#### Vue 测试工具传递依赖漏洞

`@vue/test-utils` 当时引入存在已知高危公告的旧格式化依赖。生产依赖不受影响，但为保持完整审计为零，移除该依赖，改用 Vue 的 `createApp` 完成基础挂载测试。

#### PowerShell npm 脚本限制

系统策略禁止执行 `npm.ps1`。使用官方同目录下的 `npm.cmd`，没有更改用户机器的全局安全策略。

#### 首次提交格式修正

首次提交前发现部分文件末尾存在多余空行，同时 Git 提示行尾转换。清理格式并增加根目录 `.gitattributes` 后修订首次提交，使工作区保持干净。

### 遗留项与下一计划日入口

按计划延期：

- SQLite 模型和迁移；
- Repository/Service；
- 课程及文件 API；
- 课程和资料管理页面。

非阻塞技术债：

- Element Plus 当前为全量引入，生产包超过 Vite 默认体积提示阈值；待页面结构稳定后改为按需加载。
- FastAPI 测试组件存在上游弃用提示，不影响当前功能，后续随依赖生态调整。
- 系统未单独安装 Git for Windows；当前开发环境中的 Git 已满足项目操作。

### Git 记录

```text
256bc22 chore: initialize frontend and backend foundation
```

---

## 计划日 2：配置与数据库

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际完成日期 | 2026-07-30 |
| 状态 | 已完成 |
| 对应提交 | `3d45a24` |

### 当日目标

- 安装异步 SQLite 数据依赖；
- 建立 SQLAlchemy Base、Engine 和 Session；
- 实现 `Course`、`Document` 模型；
- 落实课程名、文件哈希范围、状态和级联删除规则；
- 建立 Repository、Service 和 Pydantic Schema 基础；
- 配置 Alembic 并创建首次迁移；
- 增加数据约束和迁移测试。

明确不实施：

- 课程 HTTP API；
- 文件上传、磁盘写入和删除；
- Qdrant 向量写入或清理；
- 前端课程和资料管理页面。

### 完成内容

#### 数据库基础

- 安装 SQLAlchemy、aiosqlite 和 Alembic；
- 建立异步 Engine 和 Session Factory；
- 为 SQLite 连接启用 `PRAGMA foreign_keys=ON`；
- 将 SQLite 专用连接设置限制在 SQLite Engine，不影响未来可能接入的其他数据库；
- 建立统一的数据库约束命名规则。

#### 数据模型

- 实现 `Course`：
  - UUID 主键；
  - 最长 100 字符的唯一课程名；
  - 可选简介；
  - 创建和更新时间。
- 实现 `Document`：
  - UUID 主键和课程外键；
  - 原始文件名和内部存储名；
  - 文件类型、大小和 SHA-256；
  - 状态和错误信息；
  - 创建和更新时间。

#### 业务规则

- `Course.name` 建立数据库级唯一约束；
- `(Document.course_id, Document.sha256)` 建立复合唯一约束；
- 相同文件允许存在于不同课程；
- 文档状态限制为：
  - `pending`
  - `processing`
  - `completed`
  - `failed`
- 删除课程时，文档数据库记录使用 `ON DELETE CASCADE` 删除；
- Service 层对课程名去除首尾空格；
- SHA-256 统一转换为小写并校验为 64 位十六进制字符串。

#### 分层结构

- Course/Document Repository 负责数据库访问；
- Course/Document Service 负责编排业务规则和事务；
- 定义 `ConflictError` 和 `NotFoundError` 领域异常；
- 建立课程和文档的 Pydantic 输入输出结构；
- HTTP 状态码映射和统一错误响应留到 API 实现时完成。

#### 迁移

- 建立异步 Alembic 环境；
- 创建首次迁移 `20260730_01`；
- 验证从空库升级到 `head`；
- 验证迁移结构与 SQLAlchemy Metadata 一致；
- 验证可以降级回 `base`；
- 将迁移应用到本地开发数据库 `data/app.db`。

### 关键设计与决策

1. Qdrant 与 SQLite 不具备跨库事务，因此当前只实现数据库记录级联；磁盘文件和向量清理将在对应服务接入后采用可重试、幂等流程。
2. Repository 执行查询和 `flush`，Service 负责 `commit`、`rollback` 和业务异常转换。
3. UUID 由应用生成，避免依赖数据库自增编号，也便于后续文件和向量使用同一实体标识。
4. 文档内部存储名建立唯一约束，防止磁盘路径对应到多条记录。
5. 配置中的数据路径从 `./data` 调整为 `../data`，与“进入 backend 目录启动”的方式保持一致，并统一落到仓库根目录的 `data/`。
6. 数据模型放在 `backend/app/models/`；根目录模型权重忽略规则被收窄为 `/models/`，避免误忽略源代码。

### 主要文件

| 文件 | 用途 |
|---|---|
| `backend/app/db/base.py` | SQLAlchemy Base 和约束命名 |
| `backend/app/db/session.py` | 异步 Engine、Session 和 SQLite 外键设置 |
| `backend/app/models/course.py` | Course 实体 |
| `backend/app/models/document.py` | Document 实体和状态枚举 |
| `backend/app/repositories/` | 数据访问层 |
| `backend/app/services/` | 业务和事务层 |
| `backend/app/schemas/` | Pydantic 输入输出结构 |
| `backend/alembic.ini` | Alembic 配置 |
| `backend/migrations/env.py` | 异步迁移运行环境 |
| `backend/migrations/versions/20260730_01_create_courses_and_documents.py` | 首次迁移 |
| `backend/tests/test_models_and_services.py` | 数据规则测试 |
| `backend/tests/test_migrations.py` | 迁移升级、一致性和降级测试 |

### 验证结果

| 检查 | 结果 |
|---|---|
| 后端 pytest | 5 项通过 |
| 课程名规范化与重复检测 | 通过 |
| 同课程文件哈希去重 | 通过 |
| 不同课程允许相同哈希 | 通过 |
| 课程删除级联删除文档记录 | 通过 |
| Alembic 空库升级 | 通过 |
| Alembic Metadata 一致性 | 无待生成迁移 |
| Alembic 降级 | 通过 |
| Ruff | 通过 |
| Mypy | 通过 |
| 本地数据库版本 | `20260730_01 (head)` |

### 问题及处理

#### 数据目录相对路径不一致

原配置使用 `./data`。按照文档中的启动方式进入 `backend` 后，这会把数据库创建在 `backend/data`，与计划中的根目录 `data/` 不一致。配置改为 `../data`，并同步修正文档和环境变量模板。

#### 忽略规则误匹配源代码

根目录 `.gitignore` 中的 `models/` 会匹配任意层级的同名目录，导致 `backend/app/models/` 被忽略。将规则收窄为 `/models/`，只忽略仓库根目录未来可能存放的模型权重。

#### 迁移验证环境写权限

首次在根目录数据区创建临时迁移数据库时受到执行环境写权限限制。迁移自动测试改用 pytest 提供的临时目录，实际开发数据库则通过受控权限完成迁移。迁移本身和项目路径设计均验证正常。

### 遗留项与下一计划日入口

按计划延期：

- 课程 CRUD HTTP API；
- 统一 API 响应和领域异常映射；
- 安全文件上传、大小和类型校验；
- SHA-256 流式计算；
- 文件系统级课程删除；
- 前端课程和资料管理。

非阻塞技术债：

- FastAPI `TestClient` 仍有一条上游弃用提示；
- `updated_at` 当前依赖 ORM 更新行为，后续批量 SQL 更新时需要显式维护；
- 文件系统和未来 Qdrant 的级联清理尚未接入，不能仅依赖数据库外键完成完整课程删除。

下一计划日需要从以下入口继续：

1. 建立 API Router 和统一响应/错误处理；
2. 实现课程创建、列表、详情和删除接口；
3. 实现文件流式上传和 100 MB 限制；
4. 将数据库事务与文件写入失败清理组合起来；
5. 添加 API 级集成测试。

### Git 记录

```text
3d45a24 feat: add database foundation and initial migration
```

---

## 本周累计成果（截至计划日 2）

- 前后端工程均可独立启动；
- 后端具备配置、异常、数据模型、数据访问和迁移基础；
- 前端具备可扩展的应用外壳和基础请求客户端；
- 本地数据库已经迁移到最新版本；
- 课程名称、文件哈希范围、状态和数据库级联规则已经自动测试；
- 两个计划日均有独立 Git 基线提交。

## 与原计划的差异

1. 原计划拟使用 `@vue/test-utils`，因其当时的传递依赖安全公告而移除，改用 Vue 原生挂载测试。
2. 数据目录配置由 `./data` 修正为 `../data`，以符合当前标准启动目录和根目录存储规划。
3. Git for Windows 尚未独立安装，当前 Codex 环境提供的 Git 已能完成全部仓库工作，因此未将系统级安装作为阻塞项。

以上差异均未减少当前计划日的功能或验收范围。

## 已知问题和技术债

| 项目 | 影响 | 处理计划 |
|---|---|---|
| Element Plus 全量引入 | 前端首包较大 | 页面结构稳定后改为按需加载 |
| FastAPI 测试组件弃用提示 | 当前测试可运行 | 跟踪上游兼容方案 |
| 完整课程删除尚未接入文件和向量 | 当前只有数据库记录级联 | 文件上传和 Qdrant 接入时实现幂等清理 |
| DeepSeek 模型 ID 尚未连通验证 | 第一周不调用模型 | RAG 问答阶段验证并处理不可用模型 |
| 独立 Git for Windows 未安装 | Codex 外的终端可能没有 Git | 用户需要独立终端开发时再安装 |

## 下一阶段衔接

第 1 周计划日 3 将进入课程和文件 API 实现。开始前需要保持：

- `data/app.db` 位于最新迁移版本；
- `.env` 继续只保存在本地；
- 课程测试资料可以随后补充，API 开发阶段也可先使用自动生成的测试文件；
- 不执行上传文件中的任何代码或指令。
