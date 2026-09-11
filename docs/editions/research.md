# Agentic 研发/科研版

Agentic 是基于 FastAPI、Vue 3、LangGraph 与本地检索组件的 RAG Agent 实验平台。
研发/科研版在产品业务核心上提供离线评测模块、数据集管理、冻结 baseline profile、
实验注册与聚合证据，面向应用开发、检索/评分方法复现及受控实验。

当前应用版本为 **1.3.0**，对应已获最终审核的 v1.3.0 源码发行。产品与科研版共用仓库、迁移链和业务
接口；发行能力通过 `distribution.py` 固化，运行模式通过 `AGENTIC_EDITION` 选择。

## 架构与研究范围

| 层 | 主要组成 | 作用 |
|---|---|---|
| 交互与接口 | Vue 3、FastAPI、HTTP/SSE | 资料空间、生成任务、智能体管理与会话 |
| 数据与版本 | SQLite、SQLAlchemy、Alembic、AgentProfile/revision | 持久化、增量迁移、配置不可变与会话固定绑定 |
| 检索与编排 | BGE-M3、BGE Reranker、Qdrant、LangGraph | Dense 召回、重排、证据门控及任务路由 |
| 生成网关 | DeepSeek / Qwen / Kimi / GLM 的配置与路由 | 按模型白名单选择供应商，记录实际模型 |
| 研究工具 | dataset registry、baseline profiles、experiment registry | 数据身份、冻结协议、split 约束及离线复现 |

`backend/app/evaluation/`、`backend/scripts/`、`backend/tests/`、`benchmarks/` 和研究文档随科研源码
分发；原始数据集、逐样本预测、模型权重、业务库和本机配置均不进入发行包。

当前不包含训练/微调执行平台、自动多智能体协作、客户 EvaluationSuite 或跨部署自动重评测。
架构细节见[技术总览](../../docs/technical/README.md)与[运行链路](../../docs/technical/agent-and-generation.md)。

## 快速上手：建立可复现的研发环境

以下命令针对 Windows PowerShell，在解压后的科研包根目录或完整 Git checkout 中执行。
已有开发目录应保留本机配置、模型和数据，不要用产品源码包覆盖。

### 1. 环境与依赖组

使用 Python 3.11+、uv、Node.js 24.12+ 的兼容版本。后端按 `uv.lock` 安装，前端按
`package-lock.json` 安装。开发与测试同时启用默认 dev 组和 research 组：

```powershell
cd backend
uv sync --frozen --group research
cd ../frontend
npm ci
cd ..
```

仅运行科研工具、不需要开发检查工具时，可使用
`powershell -File scripts/install.ps1 -Edition research`，其后端命令为
`uv sync --frozen --no-dev --group research`。该脚本不准备数据集或模型权重。

research 组包含 PyArrow 和研究所用的 scikit-learn 显式约束；scikit-learn 同时是检索组件的
共享传递依赖，因此不能用它是否已安装来判断当前模式。

### 2. 运行配置与资源路径

首次建立环境时创建 `.env`；已有文件直接编辑，不覆盖凭据和资源路径：

```powershell
Copy-Item .env.example .env
notepad .env
```

无论完整仓库还是科研包，都应确认本机配置显式启用 research。下面是单供应商最小配置示例：

```dotenv
AGENTIC_EDITION=research
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=填写有效凭据
LLM_MODEL=填写可用模型ID
LLM_AVAILABLE_MODELS=填写可用模型ID
```

多供应商按 `.env.example` 中对应 `*_BASE_URL`、`*_API_KEY`、`*_MODELS` 设置，模型 ID 必须与
实际供应商一致。完整 RAG 需配置 `EMBEDDING_MODEL_PATH`、`RERANKER_MODEL_PATH`；扫描 PDF
需 `PADDLE_OCR_BASE_DIR`。NLI 实验使用的权重由对应协议单独管理，不是启动服务的前置依赖。

`.env` 属于本地私有文件，不进入 Git 或源码包。完整 checkout 的共享默认值为 product，
开发者通过本机配置保留完整 research 功能；产品包的 `RESEARCH_AVAILABLE=False` 不能靠环境
变量解除。当前模式是功能选择，不是多租户授权或科研源码保密机制。

### 3. Schema 迁移与服务启动

对已有业务库操作前，备份 SQLite、上传目录和 Qdrant。两版共用 Alembic 迁移链，当前 head 为
`20260910_06`；不要并发运行两个实例写同一 SQLite/Qdrant 目录。

```powershell
cd backend
uv run --no-sync alembic upgrade head
uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端，从项目根目录启动前端：

```powershell
cd frontend
npm run dev
```

业务界面为 [localhost:5173](http://127.0.0.1:5173)，交互式 API 文档为
[OpenAPI /docs](http://127.0.0.1:8000/docs)。启动使用 `--no-sync`，复用已选择的依赖组。
科研模式下智能体编辑器显示研究关联；不选择关联也能使用普通业务流程。

### 4. 校验研究元数据与本地数据

先验证注册表，再对已经准备的数据执行完整性检查。在 backend 目录运行：

```powershell
uv run --no-sync python scripts/manage_benchmarks.py catalog
uv run --no-sync python scripts/manage_benchmarks.py verify beir-fiqa-2018
```

`catalog` 读取注册表元数据，不下载数据，也不执行评测。`verify` 检查已冻结的本地数据，数据
未准备时会失败；`beir-fiqa-2018` 是登记的 dataset_id，其他任务使用 catalog 返回的完整标识。

需要新增下载时，先按注册表来源、许可与项目审批流程确定范围，再显式执行 download 子命令。
科研包包含工具和公开聚合结果，不包含所有 Benchmark 的原始数据；只准备当前实验需要的资产。

## 实验复现协议

1. 明确任务、dataset_id、数据/模型 revision、代码版本、随机种子、指标与资源预算。
2. 区分 `registry.json` 的数据登记、`baseline-profiles.json` 的冻结研究配置，以及
   `experiment-registry.json` 的候选协议与状态。
3. 参数选择和候选比较使用 train/validation；进入 final test 前冻结候选并满足原协议的审批条件。
4. 使用对应任务 runner 执行实验，保留结构化结果、配置身份和哈希；不通过切换 UI 模式自动运行。
5. 对外只导出允许的聚合证据，不发布原文、样本 ID、gold span 或逐样本预测。

具体 runner、数据准备和历史方法见[离线评测说明](../../docs/technical/evaluation-and-baselines.md)。
已有 FiQA、RAGTruth、RAGBench 结果只适用于原实验条件；更换模型、知识库、检索参数或部署环境
后，不能继承这些结果作为新部署的性能证明。

## AgentProfile 与研究关联语义

AgentProfile 的 revision 固定运行配置，绑定会话继续使用原 revision。配置修改、恢复均追加新
版本；逻辑删除阻止后续生成并保留审计历史。资料内容、环境凭据及供应商输出不随 revision 冻结。

`evaluation_profiles` 仅记录 offline/advisory 研究关联，服务端校验其注册表版本、哈希和用途。
该字段不是在线评分器、已通过评测标记或产品门禁。切换 product 后旧关联保留历史兼容，普通
运行不加载评测注册表。客户评测套件、环境快照和自动适用性判定仍为后续设计。

## 开发验证与交付

使用隔离配置和独立临时目录运行回归，避免让测试依赖本机业务凭据；命令与夹具说明见
[开发和测试](../../docs/technical/development-and-testing.md)。

在 backend 目录进行静态检查：

```powershell
uv run --no-sync ruff check app tests scripts ../scripts
uv run --no-sync mypy app scripts/measure_agent_runtime.py ../scripts/build_editions.py
```

在 frontend 目录运行 `npm run test:unit -- --run` 和 `npm run build`。
从仓库根目录生成同版本双源码发行包：

```powershell
python scripts/build_editions.py --edition both --label v1.3.0
```

每包生成自己的 README、默认模式和逐文件 SHA-256 manifest；已有同名 ZIP 会拒绝覆盖。
构建前确认日志、版本、依赖锁与审批范围一致。源码和第三方材料的许可边界见
[LICENSE](../../LICENSE)、[第三方声明](../../THIRD_PARTY_NOTICES.md)与[贡献规范](../../CONTRIBUTING.md)。
