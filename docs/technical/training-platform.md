# 模拟微调平台：v1.4.0-beta.1

当前为已获发布批准的 beta 版本。训练数据、任务、模拟 Adapter 与界面已通过第八周验收；本章描述当前代码，
不把模拟任务成功解释为模型质量提升。第九周将分别推进 Reranker 与 Scorer 的真实训练和评测。

## 能力与入口

完整科研源码且 `AGENTIC_EDITION=research` 时，通过侧栏“微调实验室”进入。产品源码包排除
`app/training` 和 `app/evaluation`；共用 ORM、迁移及前端源码仍随包提供。完整仓库 product 模式
返回 403，实际产品包没有训练路由。模式不是认证或多租户权限系统。

| 页面 | 用途 |
|---|---|
| `/training/datasets` | JSONL 校验、数据版本登记、审核及资格查看 |
| `/training/new` | 智能体 → 数据版本 → 模拟目标 → 参数 → 复核提交 |
| `/training/runs` | 分页查看任务及状态 |
| `/training/runs/:runId` | 来源、进度、增量事件、取消和重试 |
| `/training/adapters` | 模拟产物列表、归档筛选 |
| `/training/adapters/:adapterId` | 完整性、来源链、兼容性与归档 |

选择智能体固定其版本和来源配置，不会训练该智能体所调用的生成模型。LoRA/QLoRA 选项目前只做
参数校验和记录；FakeTrainer 运行检查点并计算确定性 checksum，没有 optimizer、梯度或模型权重。
`simulation_steps` 与真实 epoch/batch 没有对应关系。当前 API 不允许真实模型或真实 Trainer。

## 数据与训练闭环

```mermaid
flowchart LR
    A[合成或已获授权的 JSONL] --> B[校验与不可变数据版本]
    B --> C[追加审核记录]
    C --> D[冻结来源的任务]
    D --> E[Fake worker 与租约]
    E --> F[模拟 manifest 与 Adapter 登记]
    F --> G[来源查看与归档]
```

1. 准备 manifest 与 JSONL。manifest 声明来源、训练许可、PII 和资料空间归属；训练注册表不读取
   既有资料空间、会话或公开 Benchmark 来自动造样本。
2. 校验后登记 revision。train/validation 均须非空，source/group 不得跨 split；test 及其别名被拒绝。
   通过格式校验不等于标签可靠、具有许可或已经获得真实训练授权。
3. 将 draft 送审为 pending_review，明确批准为 approved 后方可建任务。审核是本机审计署名，
   没有实现双人认证系统。源文件、manifest、split 哈希和审核序号用于后续复核。
4. 五步向导复核智能体 revision；提交时服务端在事务内再次检查版本、范围、审核与文件。数据选择器
   的 eligible 只是当时结果。同幂等键同请求重放原任务；改参数需要新键。
5. worker 默认关闭，任务留在 queued。迁移和显式启用完成后，worker 领取任务并复核来源；
   开始/完成时检查代码身份，不能用新代码静默完成旧冻结任务。
6. 成功时登记唯一模拟 Adapter；查看 `integrity` 与 manifest。归档是逻辑标记，保留历史和文件。

数据格式、完整限额与示例见[数据契约](../design-decisions/training-dataset-registry.md)和
[API 参考](api-reference.md)。Scorer 的 `score` 是单一 0～1 标签；实际训练前必须明确它对应
哪项评分维度，不能把一个标签同时解释为全部 TRACe 指标。

## 模块与持久化

| 层 | 实现与职责 |
|---|---|
| 数据 | `training/routes.py`、service/repository/validation/storage：审核、去重、资格及受控文件写入 |
| 任务 | run_routes/run_schemas/run_store：事务、幂等、冻结来源、状态机、事件 |
| 执行 | worker/trainer：单 worker 租约、心跳、检查点与模拟结果 |
| 产物 | adapter_routes/adapter_service/adapter_storage：唯一登记、manifest 校验、来源链及目录核对 |
| UI | `frontend/src/views/training`、API/DTO、edition store：科研入口与异步响应隔离 |

迁移 `20260911_07` 新增 training_datasets、training_dataset_revisions、training_dataset_reviews；
`20260911_08` 新增 training_runs、training_events、training_worker_leases；`20260911_09` 新增
model_adapters。不可变触发器、来源撤销触发器及唯一约束配合应用事务维持一致性。

任务快照包含智能体配置正文，数据库本身必须按私有资料保护；公开响应只返回来源摘要和哈希。
代码身份覆盖 `app/training/*.py` 及三个训练 ORM 文件，不等于整个仓库 commit 或完整依赖环境。
源码发行 manifest 另行记录包内逐文件哈希。

## 状态与恢复

正常主线为 queued → running → succeeded。排队取消直接 cancelled；执行中先 cancelling，
在检查点结束后 cancelled。其他终态为 failed/interrupted；终态不反写为运行中。重试创建新的
任务身份并保留 retry_of 与来源，原任务事件不覆盖，也没有真实 checkpoint 续训。

单机 SQLite 持久租约和 owner token 阻止过期 worker 提交结果；进程正常关闭和失联恢复按
[状态机设计](../design-decisions/training-run-lifecycle.md)处理。来源撤销、智能体停用/删除与取消
标记在事务中关联。取消延迟是模拟检查点行为，不能推导 GPU 训练强制退出或显存释放能力。

成功任务与 Adapter 记录同数据库事务提交，文件先写临时文件、fsync、rename。文件系统和 SQLite
没有跨介质原子事务；失败可能留下未引用文件。`storage-audit` 是有界核对，不自动删除或修复。
已登记文件缺失/篡改明确失效，不自动覆盖。补登记只适用于符合条件的历史成功任务，不重新训练。
详见[产物一致性](../design-decisions/simulated-adapter-registry.md)。

## 配置、备份与排障

`TRAINING_DATA_DIR` 默认 `../data/training`，包含 revision JSONL 与 `adapters/*.json`。
`TRAINING_WORKER_ENABLED` 默认 false；`TRAINING_POLL_INTERVAL_SECONDS=0.25`、
`TRAINING_LEASE_SECONDS=10`、`TRAINING_FAKE_STEP_SECONDS=0.2`。修改配置后重启后端；
开关和 UI 都不会自动迁移。当前 head 为 `20260911_09`，完整前端 API 地址须含 `/api`。

备份在停止写入后成组保存 SQLite、uploads、Qdrant、训练目录和私有配置，记录版本与哈希；
恢复时使用匹配的代码/配置并保持 worker 关闭，核验来源、文件、租约和业务记录后再显式启用。
不能只恢复数据库或把降级当作清理。详细操作见[升级与恢复](../releases/v1.4.0-beta.1-upgrade.md)。

| 现象 | 检查与处理 |
|---|---|
| 403 / 404 | 确认模式及发行包能力；不要用打开前端 URL 绕过后端能力边界 |
| queued 不执行 | 确认目标库为 09、worker 开关、服务进程及事件；options 开关不是活性证明 |
| 409 | 重新读取数据 row_version 或智能体 revision；复核后重新提交，避免盲目重复创建 |
| 来源预检失败 | 检查审核/权限/文件与代码身份；修复后创建重试，不改写旧快照 |
| Adapter 无效 | 保存证据并核对文件与数据库备份，不用补登记覆盖已登记损坏文件 |
| 显示成功但无权重 | 当前预期行为：只有 simulated manifest，不能绑定生成运行 |

## 验收与后续

第八周验证覆盖来源审核、版本竞争、状态机、幂等、取消/撤销、失联恢复、文件一致性、模式隔离及
五步界面；正式合成集仅两条样本，用来验收流程。真实训练时间、显存与成本未知，不能把模拟估算
作为资源承诺。Windows 原生符号链接的一项测试受权限限制跳过，junction 拒绝另有演练证据。

第九周将补齐 Reranker 与 Scorer 各自的目标/标签、数据划分、训练参数和效果对照指南；先冻结 base
及现有方案对照，再用 train/validation 选择候选，通过质量门并获批后按协议一次 test。只有真实
评测合格的产物才设计运行绑定与回滚。生成大模型权重训练不在当前及后续已规划版本范围内。
