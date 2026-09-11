# 开发与测试

## 1. 仓库结构

```text
Agentic/
├─ .env.example                 # 后端/根配置模板
├─ README.md                    # 项目入口与历史总览
├─ backend/
│  ├─ app/
│  │  ├─ api/                   # FastAPI 路由、错误映射
│  │  ├─ core/                  # Settings、领域异常
│  │  ├─ db/                    # SQLAlchemy 引擎与 Base
│  │  ├─ models/                # SQLite ORM
│  │  ├─ schemas/               # Pydantic DTO
│  │  ├─ repositories/          # 数据访问
│  │  ├─ services/              # 资料空间、文件、会话业务
│  │  ├─ ingestion/             # 解析器与分块
│  │  ├─ knowledge/             # Embedding、Qdrant、证据与审计
│  │  ├─ retrieval/             # Dense 检索抽象与 Reranker
│  │  ├─ indexing/              # 后台索引生命周期
│  │  ├─ orchestration/         # LangGraph 路由与问答图
│  │  ├─ generation/            # 模型客户端、回答、总结、组卷
│  │  ├─ external_search/       # DeepSeek Web Search
│  │  ├─ token_usage/           # Token 事件统计
│  │  └─ evaluation/            # 本地候选评测基础设施
│  ├─ migrations/               # Alembic 迁移
│  ├─ evaluations/              # 版本化本地候选评测数据
│  ├─ scripts/                  # 审计与评测 CLI
│  ├─ tests/                    # pytest
│  ├─ pyproject.toml
│  └─ uv.lock
├─ frontend/
│  ├─ src/
│  │  ├─ api/                   # REST/SSE 客户端
│  │  ├─ components/            # 应用级组件
│  │  ├─ stores/                # Pinia
│  │  ├─ types/                 # API 类型
│  │  ├─ utils/                 # 格式化工具及测试
│  │  └─ views/                 # 六个主要页面（含智能体管理）
│  ├─ package.json
│  └─ package-lock.json
├─ data/                        # 本地运行数据，公开仓库只保留 .gitkeep
└─ docs/
   ├─ technical/                # 1.0.0 当前态技术文档
   ├─ design-decisions/         # 跨周架构决策
   ├─ engineering-logs/         # 实施过程
   └─ deliverables/             # 每日/每周验收说明
```

## 2. 后端开发环境

### 2.1 安装

后端要求 Python 3.11+，使用 `uv.lock` 锁定依赖。新环境可执行：

```powershell
cd D:\Agentic\backend
uv sync --dev
```

PyTorch 配置使用项目声明的 CUDA 12.8 索引。没有可用 CUDA 时，本地模型运行会回退 CPU，但依赖安装仍应遵守 lock 文件。不要在没有评估的情况下升级 Torch、PaddleOCR、PaddlePaddle、Sentence Transformers 或 Qdrant Client；这些版本与模型加载及本地数据格式关系密切。

主要运行依赖：

- FastAPI、Pydantic Settings、SQLAlchemy、Alembic、aiosqlite；
- LangGraph、httpx、orjson、structlog；
- pypdf、pypdfium2、PaddleOCR/PaddlePaddle；
- Sentence Transformers、Torch；
- qdrant-client。

### 2.2 数据库迁移

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

当前迁移链：

```text
20260730_01  courses + documents
→ 20260803_02  document indexing progress
→ 20260803_03  conversations + messages
→ 20260810_04  token_usage_events
→ 20260907_05  agent_profiles + revisions + conversation binding
```

新增迁移：20260907_05（AgentProfile/revision + 会话可空绑定）。2026-09-08 已在用户授权后
完成正式库备份与升级，见[执行记录](../deliverables/week-07-day-01-database-upgrade.md)。
其他旧库部署 Day 1 ORM 前仍需停止后端、备份并迁移。升级、回退的数据边界见
[AgentProfile 迁移说明](../design-decisions/agent-profile-versioning.md)。

新增 ORM 字段必须同时创建 Alembic 迁移和迁移测试。不要通过删除正式 `app.db` 代替迁移。

### 2.3 启动

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

推荐从 `backend` 目录启动，确保相对数据路径和根目录 `.env` 解析一致。

## 3. 前端开发环境

### 3.1 安装与启动

Node 要求 `^22.18.0 || >=24.12.0`：

```powershell
cd D:\Agentic\frontend
npm ci
npm run dev
```

已有依赖目录的普通开发也可以使用 `npm install`。CI 和可重复构建优先 `npm ci`。

主要运行依赖：

- Vue、Vue Router、Pinia；
- Element Plus；
- Axios、fetch-event-source；
- markdown-it、DOMPurify、highlight.js、KaTeX。

Markdown 在渲染前必须继续经过 DOMPurify；不要为了支持新语法绕过清洗。

### 3.2 构建

```powershell
npm run type-check
npm run build
npm run preview
```

`npm run build` 并行执行 Vue TypeScript 检查和 Vite 生产构建。

## 4. 后端分层约定

### Route

- 解析 HTTP 输入和依赖；
- 调用 Service/Indexing/Generation；
- 构造 API Schema；
- 不直接散布 SQL 查询。

### Service

- 执行业务规则；
- 管理提交、回滚和跨存储补偿；
- 对外抛出领域异常，不暴露内部堆栈。

### Repository

- 只处理数据库查询与持久化细节；
- 不包含 HTTP 或前端概念。

### Schema 与 Model

- SQLAlchemy Model 是持久化结构；
- Pydantic Schema 是 API 契约；
- 两者不应被当作同一对象随意复用。

### Gateway

生成、外部搜索、Embedding 和向量存储通过协议/封装与业务逻辑隔离。测试使用 Fake/Mock Gateway，不发真实外部请求。

## 5. 前端约定

- API 返回先通过统一解包器，页面不直接处理 `{data,error}`。
- 可复用远程状态放入 Pinia，瞬时表单和上传队列留在 View。
- 后端 DTO 变化时同步 `src/types/api.ts`。
- SSE 必须支持 AbortSignal，并把 complete 作为成功终态。
- 供应商 API Key 不进入浏览器状态。
- 用户可见术语使用“资料空间/智能体对话”；内部 `/courses` 兼容名可以保留。
- 桌面折叠、移动端抽屉和无障碍标签需要一起回归。

## 6. 自动化测试

### 6.1 后端

```powershell
cd D:\Agentic\backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m mypy app
```

后端测试覆盖：

- 健康检查、配置、迁移和数据库约束；
- 资料空间、资料、批量删除和会话 API；
- 五类解析、OCR 布局和结构化分块；
- Embedding、Qdrant、索引、审计、检索和 Reranker；
- 上下文、查询改写、证据角色与引用；
- 多供应商生成客户端、联网适配器和 Token 统计；
- 普通问答、总结、组卷和 SSE API；
- 本地评测数据、预算、结果与人工审核层。

测试必须隔离本地正式 `.env`、API Key、SQLite、Qdrant 和上传目录。需要外部响应时使用 `httpx.MockTransport` 或 Fake Gateway。

### 6.2 前端

```powershell
cd D:\Agentic\frontend
npm run test:unit -- --run
npm run type-check
npm run lint
npm run build
```

注意：当前 `npm run lint` 包含 `--fix`，会修改文件。CI 若只希望检查，应该在发布前新增无写入的 lint 脚本；在脏工作区运行现有 lint 前先检查差异。

现有 Vitest 重点覆盖 API 错误映射、响应解包和格式化工具。资料上传、SSE 和页面主流程仍主要由后端契约测试及人工浏览器验收覆盖，后续应增加组件级测试。

### 6.3 1.0.0 最近完整回归

本技术文档整理前已记录的完整回归基线：

- 后端：231 个 pytest 测试通过；
- Ruff：通过；
- Mypy strict：98 个源文件无问题；
- 前端：10 个 Vitest 测试通过；
- vue-tsc：通过；
- Vite 生产构建：通过。

发布时应重新执行全部命令，并以当次终端输出更新 1.0.0 发布证据，不能只引用历史数字。

## 7. 手工验收清单

自动测试通过后至少验证：

1. 创建和删除资料空间。
2. 分别上传五种格式并等待完成。
3. 上传重复内容、伪装格式和损坏 PDF，确认错误与失败状态。
4. 失败资料重新处理，完成资料重新索引。
5. 单删、批删和资料空间级联删除后检查无孤儿文件/向量。
6. 在智能体对话中验证普通问答、引用、总结和组卷。
7. 切换 `course_only`，确认不触发 Web Search。
8. 快速对话开关联网并验证外部来源。
9. 切换已配置模型并检查刷新后默认值。
10. 查看 Token 统计并验证清零不影响其他数据。
11. 恢复两类会话历史并删除会话。
12. 桌面宽屏、侧边栏折叠和手机尺寸布局。

真实验收完成后删除临时资料空间，运行一致性审计，并确认没有把用户资料或 Key 写入报告。

## 8. 本地候选评测基础设施

`backend/evaluations/week05/dataset-v1.json` 是 100 条本地候选数据，包含 train/validation/test 主题隔离和多类任务。它是工程资产，不是最终自有金标，也不能代替公开 Benchmark。

CLI：

```powershell
cd D:\Agentic\backend

# 只校验数据契约和哈希，不调用模型
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation validate

# 导出待人工审核模板，不调用模型
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation export-annotations

# 冻结代码、数据、模型和参数清单，不调用生成模型
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation snapshot

# 查看真实运行参数
.\.venv\Scripts\python.exe -m scripts.run_week5_evaluation run --help
```

`run` 会真实调用模型，并可能把问题及检索到的本地资料片段发送给供应商。只有在用户明确批准数据发送范围、模型、预算和运行范围后才能执行。

真实运行支持：

- `--token-budget 1..1000000`；
- `--split train|validation|test`；
- `--case` 和 `--limit`；
- `--rerun-failed`；
- 独立 output、ledger、course 和 model。

每个 Case 原子写入，已完成 Case 默认跳过；Token 预算在调用前保守扣额。人工审核和 LLM-as-Judge 分层保存，Judge 不能覆盖人工金标。

## 9. 公开 Benchmark 接入约束

1.0.0 尚未下载公开数据。第五周后续按以下状态机推进：

```text
candidate → approved → downloaded → verified → frozen
```

每个数据集在下载前提交：

- 官方来源与版本；
- 许可证和再分发限制；
- 预计大小与保存目录；
- 下载命令；
- 哈希/签名校验；
- corpus/query/qrels 或 question/context/answer/label 映射；
- split 用途和污染防护。

候选包括 BEIR SciFact、RGB refined、RAGBench、RAGTruth 和 IBM MTRAG，但当前均不视为已审批。

## 10. 经典基线顺序

获得数据批准后，先复现再改进：

1. BM25；
2. 当前 BGE-M3 Dense；
3. 融合检索；
4. BGE Reranker；
5. Exact Match、Token F1、ROUGE-L、BERTScore；
6. RAGAS/RAG Triad 类指标；
7. 在 RAGBench/RAGTruth 标注上验证评分器自身质量。

检索报告 Recall@K、Precision@K、MRR、MAP、nDCG、延迟和资源；分类评分器报告 Precision/Recall/F1/AUROC/AUPRC；连续评分器报告 Pearson、Spearman、校准误差和重复运行稳定性。

## 11. 变更纪律

- 一个 PR/提交聚焦一个可解释目标。
- 先增加失败测试，再修复高风险逻辑。
- API、数据库、Qdrant Payload 和评测数据契约的变化必须写迁移说明。
- 模型或阈值变化必须记录版本、配置、数据哈希和实验结果。
- 不在 test split 上调参。
- 不提交 `.env`、真实资料、数据库、向量、模型和未经许可的数据。
- 用户工作区可能已有未提交修改；不得用 reset/checkout 覆盖。


## Week 7 前端与浏览器回归补充

前端单元测试新增智能体配置工具和会话绑定组件测试。浏览器闭环使用
frontend/e2e/server.py 的隔离库与模拟网关，frontend/e2e/agent-profiles.cjs 核验测试服务
身份后再执行管理和对话操作。启动方式和覆盖范围见 [Day 4 报告](../deliverables/week-07-day-04.md)。


## Week 7 集成与解析测量

`tests/test_agent_integration.py` 使用 MockTransport 验证四供应商固定版本路由；模拟
Request.is_disconnected 验证两类 SSE 在 delta 前后中断及同版本重试。测试不访问真实供应商。
全量 pytest 应禁用正式 .env，使用独立 basetemp，不复用用户要求保留的 Day 1 目录。

从 backend 运行 `python -m scripts.measure_agent_runtime --samples 100`，在内存 SQLite
测量默认、绑定和创建前解析。每种情况预热 10 次、独立 Session、2/1,000 个合成智能体；
脚本断言 SQL 为 0/1/2 次并输出中位/P95。仅测解析，不代表完整生成请求的性能。
方法、结果和联合验收状态见[Day 5 报告](../deliverables/week-07-day-05.md)。

## 两个源码发行包验证

完整开发环境使用 uv sync --frozen --group research，普通安装使用 --no-dev。
不要为了检查依赖分组而修改正在使用的业务虚拟环境。

从仓库根目录运行 python scripts/build_editions.py --output output/editions。解压产品包后，
使用已有开发 Python 运行 scripts/verify_product_edition.py，传入解压目录和独立绝对路径
--basetemp。它断言应用来自解压包并禁止研究模块/PyArrow 导入。此验证复用已安装依赖，
不等同于执行了全新联网安装。

frontend/e2e/server.py 默认启动 product 隔离服务 18004；设置 AGENTIC_UI_TEST_EDITION=research
启动科研服务 18005。前端分别使用对应 API 与 41734/41735，运行 agent-profiles.cjs 和
research-edition.cjs。输出位于 tmp/week07-editions-product-ui 与 research-ui，不使用业务库。
