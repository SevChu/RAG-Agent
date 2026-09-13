# 第八周 Day 1：训练数据 Registry 与审核基础

- 实施日期：2026-09-11。
- 授权：用户已批准[第八周计划](week-08-plan.md)并明确启动 Day 1；高风险/需用户操作事项须先审查。
- 状态：开发与自动验证完成，用户于 2026-09-11 确认验收通过并授权 Day 2；后续结果见[Day 2 报告](week-08-day-02.md)。
- 应用版本仍为 `1.3.0`；本周目标候选为 `v1.4.0-beta.1`，没有发布。

## 本日目标与完成范围

建立科研模式可用的 TrainingDataset Registry，提供不可变数据版本、审核/撤销、内容校验和未来任务的服务端使用资格门，保证旧 AgentProfile、会话和产品版保持兼容。

已完成：

1. 三张元数据表及六个不可变触发器；增量迁移 `20260910_06 → 20260911_07`。
2. UTF-8 JSONL + manifest 受控上传，支持 scorer/reranker 两种明确 schema，记录来源、许可、PII、空间声明、内容及 split 哈希。
3. 数据结构校验、精确重复/来源分组/字符近重复检测、基础敏感模式检查及可复现报告。
4. draft、pending_review、approved、rejected、revoked 审核流程，审核事件追加保存，并发修改使用 row_version 防止覆盖。
5. 创建/列表/详情/版本/导入校验/审核记录/资格检查，共 10 个 HTTP 操作；无原始样本下载接口。
6. 资格检查再次核验审核状态、智能体启停/删除、当前空间范围、来源空间存在性、原文件及 manifest/report 完整性。
7. 请求体、文件、行数和去重工作量上限，拒绝链接越界/硬链接；上传文件名不进入路径。
8. 产品包排除 `app/training`，保留共用 ORM/迁移；实际解压产品包后阻断科研及训练模块导入验证核心能力。

设计和精确字段见[数据契约](../design-decisions/training-dataset-registry.md)，请求示例见[API 参考](../technical/api-reference.md)。

## 验证结果

| 检查 | 结果 |
|---|---|
| 后端全量回归 | 454 passed，72.21 秒 |
| 最终 Day 1 定向复验 | 52 passed，11.23 秒；JUnit 证据保留于本周临时目录 |
| 后端静态检查 | Ruff 通过；strict Mypy 120 个源文件通过 |
| 隔离迁移 | 升级、回退、再升级通过；Alembic 与 ORM 无差异 |
| 旧数据与触发器 | 七张旧业务表逐行相等，原触发器保留；foreign_key_check 无错误，integrity_check 为 ok |
| 前端回归 | 25 passed；类型、只读 ESLint 与 1756 模块构建通过 |
| 实际产品制品 | 80 passed、1 deselected，29.05 秒；无 app.evaluation/app.training/PyArrow 导入 |
| 双版打包规则 | 全量测试中分别检查产品/科研包边界、共用迁移与逐文件哈希 |
| OpenAPI 与文档审计 | 版本 1.3.0 / 33 paths；训练数据 7 paths / 10 操作；99 个 Markdown 链接无失效 |
| 变更隐私范围 | 不含运行数据、权重、样本文件或依赖锁变更；数据核心未导入训练栈 |

最初 40 项数据功能测试通过，但迁移反射检查发现冻结 SQL 换行使 SQLite 约束识别与 ORM 不一致，已改为显式 Alembic 建表；随后 42 项定向检查通过。后续增加转义敏感信息、Unicode、并发导入、硬链接及请求限额测试，并纳入上述全量回归。类型检查发现的 SQLAlchemy 返回类型与变量类型冲突也已修复。

实际产品验证出现两条 pytest 已导入模块无法重写断言的提示，不影响通过结果。前端构建的插件耗时提示不是构建失败。本日无 UI 增量，因此未新增浏览器交互验收；五步微调页面属于 Day 4。

验证关闭正式 `.env`、使用隔离 SQLite 和合成资料；全量后端运行器阻断外部网络并设置离线模型标志。没有使用真实供应商、训练样本或现有封存 test。测试和产品包位于本周忽略目录 `tmp/week08-day01/`，本轮不清理。

## 环境记录

| 项目 | 只读检查结果 |
|---|---|
| Python | 3.11.15 |
| 系统 | 原生 Windows，内核版本 10.0.26200 |
| RAM | 总量 63.71 GiB；采样可用 47.38 GiB |
| 工作区磁盘 | 采样可用 404.29 GiB |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU；8188 MiB；驱动 596.21 |
| 已安装相关包 | Torch 2.11.0+cu128、Transformers 5.14.1、sentence-transformers 5.6.1 |
| 未安装训练扩展 | PEFT、TRL、bitsandbytes |

仅检查已安装包元数据和 nvidia-smi；未导入模型或执行 CUDA 训练。资源可用量会变化，不能据此承诺真实训练可行性或耗时。第八周 Fake Trainer 沿用 Windows；真实模型、依赖、OS 兼容性和预算在第九周具体核验。

## 主要文件

| 文件 | 用途 |
|---|---|
| `backend/app/models/training_dataset.py` | 数据身份、不可变版本与审核事件 ORM |
| `backend/migrations/versions/20260911_07_training_datasets.py` | 独立增量迁移 |
| `backend/app/training/schemas.py` | manifest、样本、报告及 API DTO |
| `backend/app/training/validation.py` | 编码、schema、许可/PII 标志、去重与哈希 |
| `backend/app/training/storage.py` | UUID 文件存储和路径/链接边界 |
| `backend/app/training/repository.py` | 数据访问和分页 |
| `backend/app/training/service.py` | 事务、审核、撤销与使用资格 |
| `backend/app/training/routes.py` | 10 个 HTTP 操作 |
| `backend/app/training/upload_limit.py` | multipart 解析前请求限额 |
| `backend/tests/test_training_datasets.py` | 数据、接口、并发、存储与模式隔离验证 |
| `backend/tests/test_training_dataset_migration.py` | 七表数据与旧触发器往返迁移 |
| `scripts/build_editions.py`、`scripts/verify_product_edition.py` | 双版分发与实际产品包导入阻断 |

## 尚未执行的操作与审查边界

- **正式数据库未迁移。** 新迁移仅在隔离合成库演练；现有资料、会话和恢复备份未修改。若需在正式后端试用数据 API，先提交具体数据库身份、备份位置、迁移/停机/恢复步骤并取得用户批准，再执行。
- 没有安装/升级依赖、下载模型/数据、启动真实训练、调用付费服务或执行 official test。
- 未改应用版本号、Git 提交、Tag、推送或 Release；周计划中的发布要求仍适用。

## 限制与 Day 2 入口

1. 审核是本地单用户署名记录，不是认证授权或双人标注；规则扫描不等于完整隐私/许可审计，近重复规则也不识别全部语义改写。
2. 训练数据注册表仅接受 train/validation，不管理封存 test；无法自动识别人为伪报数据来源，审核人需核对 provenance。
3. 文件独占写入后数据库提交失败可能留下未引用文件；API 不会展示或选用，后续按引用清单审核清理，不自动删除。
4. Day 1 只有数据使用资格门，没有 TrainingRun/Fake Trainer/Adapter/UI。撤销后资格检查拒绝使用已经验证；排队取消、运行取消及竞争处理留到 Day 2。
5. Day 2 先实现任务冻结配置与持久化状态机，提交及领取时调用 `require_eligible`，补上与审核撤销的事务/版本协调，再接入 Fake Trainer 的取消、失败、重试与恢复。
