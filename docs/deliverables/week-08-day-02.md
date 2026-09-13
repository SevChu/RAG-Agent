# 第八周 Day 2：持久化模拟训练任务与 Fake Trainer

- 实施日期：2026-09-11。
- 用户已确认 Day 1 验收完成并授权实施 Day 2；高风险/正式操作继续先审查。
- 状态：2026-09-11 用户确认 Day 2（含副本演练）完成并授权 Day 3；本日已验收。
- 应用仍为 1.3.0，本周目标候选为 v1.4.0-beta.1，没有提交或发布。

## 本日完成内容

1. 新增 TrainingRun、TrainingEvent 和单例 TrainingWorkerLease，迁移 `20260911_07 → 20260911_08`，配套 13 个触发器。
2. 任务固定智能体 revision/config hash、数据 revision/manifest/content/split hash、审核序号、目标与模拟模型、LoRA/QLoRA 参数、seed、模拟步数、代码身份和 Python 版本。
3. 持久化 queued/running/cancelling/succeeded/failed/cancelled/interrupted 状态及进度事件。SQLite 同时保护来源身份、合法状态转换、进度单调和终态不可覆盖。
4. 同键同参幂等重放，同键异参冲突；失败/取消/中断重试创建新 run 并关联 retry_of，保留原版本和失败记录。
5. 单 worker 租约原子领取、周期心跳、进度续约、所有权 token 校验；租约过期恢复中断任务，迟到回调不能提交结果。
6. 数据审核撤销、智能体停用/删除、来源空间权限收窄或空间删除，在原操作事务中取消关联排队任务、请求取消运行任务；重新启用不会复活原任务。
7. Trainer 接口及确定性 Fake Trainer 跑通成功、失败、取消、关闭与恢复；故障注入只存在测试构造器中，不开放给 HTTP。
8. 新增 8 个 API：能力选项、模拟估算、创建、列表、详情、事件分页、取消与重试。请求体限制 64 KiB，日志/详情不暴露异常原文、系统提示、样本和 worker token。
9. 应用生命周期接入后台 worker，`TRAINING_WORKER_ENABLED=false` 默认关闭；仅科研模式且显式启用才执行。产品包继续排除训练实现，保留共用迁移和 SQL 取消规则。

成功结果只是 `artifact_kind=simulated`、`deployable=false`、`evaluation_status=not_evaluated` 与 checksum，不生成权重或注册 Adapter。资源估算只描述模拟步骤耗时和可用 RAM；真实训练显存、时间、成本仍为待评估。

详细规则见[任务生命周期设计](../design-decisions/training-run-lifecycle.md)，请求示例见[API 参考](../technical/api-reference.md)。

## 验证结果

| 检查 | 结果 |
|---|---|
| 首轮定向测试 | 38 passed，27.41 秒 |
| 扩展定向与兼容验证 | 52 passed，36.13 秒；包含任务、两日迁移及双版测试 |
| 后端全量回归 | 499 passed，144.64 秒；较 Day 1 增加 45 项测试 |
| 静态检查 | Ruff 全量 app/tests/migrations 及打包脚本通过；strict Mypy 126 源文件通过 |
| 实际产品源码包 | 80 passed、1 deselected，63.05 秒；阻断 app.training/app.evaluation/PyArrow 导入 |
| 前端 | 25 passed；类型、只读 ESLint、1756 模块构建通过 |
| 迁移 | 新迁移升级/回退/再升级、Alembic 与 ORM 对照通过；Day 1 Registry 和原业务数据/触发器保留 |
| 并发与恢复 | 双 worker 单胜者、幂等并发、提交/撤销竞争、完成/取消竞争、有效心跳、过期恢复、迟到回调隔离通过 |

全量后端与实际产品制品验证在本机并行运行，以上壁钟耗时不作为推理或真实训练性能指标。产品验证的两条 pytest 模块重写提示不影响结果。

### 最终审计

- 113 个 Markdown 本地链接有效；OpenAPI 共 40 个路径，其中训练任务为 7 个路径、8 个 HTTP 操作。
- 当前训练模块代码指纹与全量测试成功任务保存的快照一致；单独导入训练核心没有加载模型库。
- JUnit 再核对为 499 项通过，无失败或错误。审计结果与 OpenAPI 快照保存在 tmp/week08-day02/final-audit.json 和 openapi.json。

### 取消测量

使用合成数据，Fake 检查点间隔 30 ms，任务上限 50 步，运行后发出取消：

| 运行轮次 | 取消请求至终态 | 实际完成步数 |
|---|---|---|
| 扩展定向验证 | 约 62 ms | 1 / 50 |
| 全量回归 | 约 94 ms | 2 / 50 |

两次都以 cancelled 结束，没有产物结果。测量包含本地 API/数据库开销，仅为两次 Fake 样本，不是 SLA，也不证明真实 GPU 训练会以相同速度释放资源。默认检查点为 200 ms，本日测试使用更短间隔。

### 隔离与证据

- 测试显式关闭正式 .env、使用独立 SQLite/合成 JSONL，禁止外部网络并设置模型离线标志。
- `tmp/week08-day02/targeted.xml`、`full.xml` 保存 JUnit 结果；取消测量保存在对应测试子目录。
- 测试制品位于 `tmp/week08-day02/archives/`，用于本地验证，未发布。Day 1/2 临时证据均保留。
- 未调用真实供应商、下载模型/数据、安装依赖或运行 official test。本日没有 UI 增量，不新增浏览器交互验收。

## 关键文件

| 文件 | 职责 |
|---|---|
| `backend/app/models/training_run.py` | 三张任务表、身份/终态保护、事务内事件及依赖取消 |
| `backend/migrations/versions/20260911_08_training_runs.py` | 与应用模型解耦的冻结迁移 |
| `backend/app/training/run_schemas.py` | 任务、LoRA/QLoRA 参数、来源快照和返回 DTO |
| `backend/app/training/run_store.py` | 事务、幂等、重试、资格复核、租约领取、回调及恢复 |
| `backend/app/training/trainer.py` | Trainer 协议、Fake Trainer 和模拟资源估算 |
| `backend/app/training/worker.py` | 后台循环、心跳、取消、失败与关闭处理 |
| `backend/app/training/run_routes.py` | 8 个任务 HTTP 操作 |
| `backend/tests/test_training_runs.py` | 主流程、权限撤销、并发、恢复、脱敏与生命周期测试 |
| `backend/tests/test_training_run_migration.py` | Day 2 迁移往返及旧 Registry 保留 |

## 取舍、问题与限制

- 为避免新增队列依赖，本周使用 SQLite 单 worker 租约，不引入 Redis/Celery。完整资格复核位于写事务内，其他写操作可能等待；不将其宣称为大规模调度方案。
- 现有 psutil 没有类型 stub，使用局部 import-untyped 标记并保留运行时验证，没有为通过静态检查安装新包。
- 沿用 Day 1 的 SQLite 约束反射经验，迁移冻结 SQL 时只拆 Python 字面量、不重排 SQL 内部空白；新旧约束对照通过。
- 代码身份仅覆盖训练模块及训练模型定义，不冻结完整依赖环境；管理员设置、文件系统和时钟也不是不可变训练环境。
- 失去租约的 worker 无权写入，但此机制不等于真实 GPU 子进程强杀；真实训练停止与资源释放需后续独立验证。
- 本周不自动删除任务和事件；单任务日志有界，长期累积空间治理后续按明确清理规则处理。

## 正式操作边界与下一日入口

**正式数据库和 .env 未修改，正式 worker 未启用。** 当前新链终点只在隔离库演练；若需正式试用，先审查实际数据库身份、备份、Day 1/2 升级、停机/恢复步骤和 worker 开关，再执行。

没有依赖/模型安装、真实训练、付费请求、提交、Tag、推送或 Release。Day 3 将继续实现 Adapter Registry、产物文件/数据库一致性、来源查询与模拟产物不可部署的后端校验；Day 2 的模拟结果不能算作该部分已经完成。

## 2026-09-11 增补：正式数据副本演练

用户授权后完成[正式数据副本演练](week-08-day-02-copy-rehearsal.md)：7 次迁移操作、7 组运行场景通过，48 条原业务记录保持；正式库/.env 与原始备份哈希未变，副本 worker 已停止。此次新增验证使用实际历史数据库副本和独立合成训练样本，区别于上文先前的全合成自动测试。

2026-09-11 后续：用户验收 Day 2 后，Day 3 已完成[模拟 Adapter Registry](week-08-day-03.md)，等待当日验收。
