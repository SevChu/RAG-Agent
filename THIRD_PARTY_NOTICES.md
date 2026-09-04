# Agentic 第三方材料、依赖与 Benchmark 声明

更新日期：2026-09-04

本文件用于明确 Agentic 专有许可的边界，不授予任何上游材料的新权利，也不替代上游许可
原文。根目录 [`LICENSE`](LICENSE) 只适用于 Severus Chu 拥有版权的 Agentic 原创材料。

当前 Git 仓库不提交 `node_modules`、Python `.venv`、第三方模型权重、原始 Benchmark、逐样本
预测或构建产物。下列依赖由包管理器在用户本地安装；如果未来发布 Docker 镜像、桌面安装包、
离线依赖包或其他包含第三方二进制的制品，必须重新生成完整 SBOM/许可清单并随制品提供必要
的许可文本、通知和源码获取方式。

## 1. Benchmark 与数据集

| 数据集 | 上游许可/限制 | Agentic 中允许的范围 | 禁止进入公开制品的内容 |
|---|---|---|---|
| BEIR FiQA-2018 | FiQA 官方训练集和测试集仅限非商业使用 | 本地非商业研究评测；公开包只保留聚合数值、协议和引用 | corpus、query、qrels、原始 run、逐样本结果及任何可恢复原文的材料 |
| RAGTruth | 发布仓库为 MIT；MS MARCO、Yelp、CNN/DailyMail、新闻等底层内容保留原权利 | 本地研究评测；公开包只保留聚合数值、协议和引用 | source/response 文本、prompt、标签 span、逐样本预测及底层语料 |
| RAGBench | 数据卡标注 CC BY 4.0；各组成数据集的通知和限制继续适用 | 本地评分器研究；公开包只保留聚合数值、revision、协议和引用 | Parquet、问题/上下文/回答、逐样本预测及未复核的组成数据 |
| BEIR SciFact | CC BY-NC 2.0；当前仅为未批准候选 | 注册表元数据与候选说明 | 数据文件及其派生样本级材料 |
| RGB refined | 来源与 refined 文件权属仍待专项复核；当前仅为未批准候选 | 注册表元数据与候选说明 | 任何下载数据或派生材料 |

`benchmarks/` 目录不属于 Agentic 专有软件许可的授权范围。目录中的数值结果仅作为研究参考，
不重新许可底层数据，不扩张非商业使用范围，也不得被解释为 Severus Chu 对第三方语料主张
所有权。引用结果时应同时引用 Agentic 版本和对应数据集/论文。

主要上游记录：

- FiQA 官方页面：<https://sites.google.com/view/fiqa/home>
- BEIR 数据集页：<https://github.com/beir-cellar/beir/wiki/Datasets-available>
- RAGTruth：<https://github.com/ParticleMedia/RAGTruth>
- RAGBench：<https://huggingface.co/datasets/galileo-ai/ragbench>
- 机器可读注册表：[`backend/app/evaluation/registry.json`](backend/app/evaluation/registry.json)

## 2. 模型与模型资产

模型权重、tokenizer 和 OCR 模型不属于 Agentic 原创材料，且不随 Git 仓库发布：

| 模型/资产 | 当前上游许可记录 | 仓库策略 |
|---|---|---|
| BAAI/bge-m3 | MIT | 仅记录模型名称/revision；权重保存在 Git 忽略目录 |
| BAAI/bge-reranker-v2-m3 | Apache-2.0 | 仅记录模型名称/revision；权重保存在 Git 忽略目录 |
| cross-encoder/nli-deberta-v3-base | 模型仓库声明 Apache-2.0；base model `microsoft/deberta-v3-base` 模型卡声明 MIT；训练数据标注为 SNLI、MultiNLI | 固定 revision `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`，仅用于本地研究评测；权重不进入 Git 或 Release；未来重新分发前需重新复核许可与通知 |
| PaddleOCR / PaddlePaddle 模型与运行时 | 项目代码标注 Apache-2.0；具体外部模型仍以其模型页为准 | 不提交权重；发布制品前重新核对具体模型及训练数据说明 |

模型输出是否包含第三方受保护内容取决于输入、供应商条款和具体使用方式；Agentic 的
`LICENSE` 不对模型输出作所有权保证或再许可。

## 3. Python 直接依赖

以下为 v1.1.0 锁定环境中的直接运行时依赖许可摘要。版本和完整依赖图以
[`backend/uv.lock`](backend/uv.lock) 为准。

| 依赖 | 许可摘要 |
|---|---|
| aiosqlite | MIT（当前本地 wheel 元数据未填写 License 字段，以官方项目为准） |
| Alembic, FastAPI, LangGraph, Pydantic Settings, SQLAlchemy | MIT |
| HTTPX, psutil, pypdf, scikit-learn, PyTorch | BSD-3-Clause |
| PaddleOCR, PaddlePaddle, Qdrant Client, Sentence Transformers, PyArrow | Apache-2.0 |
| structlog | MIT OR Apache-2.0 |
| pypdfium2 | BSD-3-Clause、Apache-2.0 及其所带 PDFium/二进制依赖许可 |
| orjson | MPL-2.0 AND（Apache-2.0 OR MIT）；不同源文件适用不同许可 |

开发依赖 mypy、pytest、pytest-cov、Ruff 等仍分别遵循其上游许可；开发依赖身份以
`backend/uv.lock` 为准。

需要特别关注的传递依赖：

- `crc32c` 由 `PaddleOCR -> PaddleX -> AIStudio SDK -> bce-python-sdk` 引入，包主体为
  LGPL-2.1，并包含 BSD/custom-licensed 部分；
- `tqdm`、`certifi` 等包含 MPL 或复合许可声明；
- 上述包目前没有作为源码或 wheel 提交到本仓库，但若未来随二进制制品分发，必须保留通知并
  满足适用的 LGPL/MPL 源码、修改和可替换/重新链接要求。

## 4. JavaScript 直接依赖

以下为 v1.1.0 锁定环境中的摘要，准确版本和完整传递图以
[`frontend/package-lock.json`](frontend/package-lock.json) 为准：

| 依赖组 | 许可摘要 |
|---|---|
| Vue、Vue Router、Pinia、Element Plus、Axios、KaTeX、Markdown-It、Microsoft Fetch Event Source 及多数开发工具 | MIT |
| highlight.js | BSD-3-Clause |
| TypeScript、Playwright | Apache-2.0 |
| DOMPurify | MPL-2.0 OR Apache-2.0；Agentic 在允许选择时采用 Apache-2.0 路径 |
| Lightning CSS（由 Vite 间接引入） | MPL-2.0 |

`node_modules` 和 `frontend/dist` 当前不进入 Git。若发布浏览器 bundle，必须核对 bundle 是否
包含 MPL/Apache 代码，并随制品提供相应通知、许可文本和可获取源码的位置。

## 5. 分发合规门禁

任何公开发布制品在上传前至少必须完成：

1. 生成与实际制品一致的 Python/npm SBOM 和完整第三方许可清单；
2. 拒绝未经批准的 GPL/AGPL、来源不明、仅研究、非商业或禁止再分发组件进入商业制品；
3. 对 MPL/LGPL 组件保存对应源码版本、修改记录、许可文本及必要的重新链接/替换说明；
4. 对 Apache、BSD、MIT、CC BY 等组件保留版权、许可和署名通知；
5. 独立复核数据集、模型权重、字体、图标、图片、示例资料和生成内容；
6. 确认公开 Benchmark 仍只有聚合数据，且没有原文、样本标识或可逆信息。

本文件是工程合规记录，不构成法律意见。涉及商业发布、收费服务、模型/数据再分发或跨法域
使用前，应由具备资质的法律专业人员复核实际发布制品和全部上游条款。
