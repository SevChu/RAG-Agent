# 第八周 Day 2：正式数据副本演练

- 日期：2026-09-11。
- 授权：用户明确要求“开始数据副本演练”；本次执行范围为本地备份、独立副本迁移与模拟运行。
- 结果：演练通过，正式库未迁移、正式 worker 未启用；Day 3 尚未开始。
- 关联：[Day 2 实现报告](week-08-day-02.md)、[本周计划](week-08-plan.md)。

## 副本与隔离

配置解析出的正式库为 `data/app.db`，版本 `20260910_06`，634,880 字节，SQLite delete 日志模式；读取时没有 WAL/SHM/journal 附属文件，配置中的 worker 为关闭。

通过 `sqlite3.Connection.backup` 从 `mode=ro` 连接生成一致性快照，不直接复制正在使用的数据库文件。保留原始快照后，从已关闭的快照建立两份独立副本：

| 本地私有文件 | 用途与最终状态 |
|---|---|
| `tmp/week08-rehearsal/day02-20260911/source-backup.sqlite` | 原始备份；保持第七周版本，哈希未变 |
| `tmp/week08-rehearsal/day02-20260911/migration-roundtrip.sqlite` | 专用于升级/回退/再升级；最终为 Day 2，无模拟任务 |
| `tmp/week08-rehearsal/day02-20260911/rehearsal.sqlite` | 分步升级后进行历史读取及 Fake worker 演练；最终为 Day 2 |

进程内覆盖 DATABASE_URL，禁用 .env 加载、自动索引与联网搜索，供应商凭据清空或替换为离线占位值。训练、上传、向量库和模型目录全部指向演练目录；没有复制正式上传文件、向量索引或模型。运行验证加装 Python 审计钩子，拒绝连接演练目录外的数据库、读取正式 data 目录和 .env。外部网络与 DNS 被阻断，仅允许 Windows asyncio 内部需要的本机回环连接。

API 使用进程内 ASGI 调用，没有启动监听端口或修改正在使用的正式进程。运行时使用真实应用生命周期启动/关闭 Fake worker。

## 迁移与旧数据验证

| 原业务表 | 原记录数 | 结果 |
|---|---:|---|
| agent_profiles | 1 | 原记录保持 |
| agent_profile_revisions | 2 | 原配置、版本与哈希保持 |
| conversations | 9 | 原记录保持 |
| messages | 26 | 原记录保持 |
| courses | 2 | 原记录保持 |
| documents | 3 | 原记录保持 |
| token_usage_events | 5 | 原记录保持 |
| 合计 | 48 | 7 张表全部原行保持 |

迁移副本依次执行：`06 → 07 → 08 → 07 → 06 → 08`；运行副本执行：`06 → 07 → 08`。共完成 7 次 Alembic 操作，每步校验版本、原行指纹、原表/索引/触发器定义、integrity_check 和 foreign_key_check；结果均通过。抵达 `20260911_08` 后的 3 次 Alembic check 均无新增差异。

运行后再次核对全部 48 条原业务记录，未被演练修改。新增的 1 个智能体及其 1 个 revision 专供合成训练使用，不引用正式智能体作为运行对象。

## Worker 与 API 演练

| 场景组 | 实测结果 |
|---|---|
| 历史只读 API | 2 个空间、3 份文档元数据、9 个会话及26条消息、1 个智能体及2个revision可读取；Token 汇总 API 返回成功 |
| 默认关闭 | 应用生命周期启动后任务保持 queued |
| 启用与运行取消 | 开启副本 worker 后成功任务完成；50 步任务在运行中取消，无结果 |
| 失败、重试、关闭与重启 | 仅测试构造器注入失败，错误为脱敏码；重试创建新任务成功；正常关闭将运行任务标为 interrupted，重启保留终态 |
| 独立进程退出恢复 | 子进程领取并提交任务后不执行终态清理即退出；1 秒租约过期后，新 worker 标记 interrupted / WORKER_LOST |
| 审核撤销 | 撤销合成数据审核后，排队任务 cancelled，再次提交被拒绝 |
| 持久化事件 | 全部 7 个任务的事件序号连续、进度不倒退 |

最终 7 个任务：succeeded 2、cancelled 2、failed 1、interrupted 2；没有 queued/running/cancelling 遗留。成功结果均为模拟且不可部署。合成数据仅 2 行，分别属于 train/validation，没有使用历史对话或资料正文作训练样本。

取消测量：Fake 检查点 30 ms，从取消请求到观察到 cancelled 约 **47 ms**，实际完成 2/50 步。这是一次副本环境样本，不是 SLA 或真实 GPU 停止时间。

结束时 worker 协程全部停止，租约 owner_token 为空、expires_at 为 0；索引 pipeline 未创建，隔离上传、向量库和模型目录为空。

## 最终审计与证据

- 正式数据库文件、根目录 .env 与后端 .env（存在性也纳入检查）的 SHA-256/存在性与演练前一致；正式版本仍为 `20260910_06`，未产生附属日志文件。
- 原始备份哈希不变，备份与正式库的原业务记录、结构及版本一致。
- 训练运行时代码指纹与 Day 2 的 499 项全量回归时一致；本次没有改业务代码或新增依赖，因此没有重复全量回归。
- 演练库、原始备份、合成文件和私有证据均被 Git 忽略，未提交或发布。
- 私有证据目录：`tmp/week08-rehearsal/day02-20260911/`，包含 backup-manifest.json、baseline-private.json、source-guard-private.json、migration-results.json、worker-results.json、final-results.json。
- 可复核脚本保留在 `tmp/week08-day02/`：copy_rehearsal.py、exercise_copy.py、orphan_claim.py、verify_copy.py；脚本带目标目录限制和防覆盖检查，不作为正式迁移命令。

初次迁移尝试在创建 Windows asyncio 事件循环时，被演练脚本的全连接禁令拦截，尚未执行迁移。调整为允许内部回环、继续阻断外部连接后通过。Git 忽略审计改用 NUL 分隔输出，以避免 Windows 路径显示转义影响比较。这两项都是演练工具修正，未改动应用实现。

## 范围与后续安排

本次验证了实际历史数据库状态下的迁移、元数据/API兼容及 Fake worker；没有验证正式文档下载、检索、向量索引恢复、真实供应商调用或浏览器操作。数据库副本中的旧文件路径保留，但本次只读元数据，不沿这些路径打开资产。这不是数据库与外部文件共同恢复的完整灾备演练。

迁移回退发生在新增表尚无训练数据的专用副本上，不表示正式启用后降级可无损保留新任务。恢复原始备份也会舍弃快照之后的数据，正式恢复必须结合届时写入情况单独审查。

Day 3 在隔离环境继续增量验证 Adapter；Day 4 完成合成资料与界面全链路；Day 5 汇总证据并准备正式升级审查。正式升级时重新确认库身份、做新备份、检查写入/停机安排，再经用户批准执行迁移和开关变更，不能直接把本次已产生模拟数据的副本替换为正式库。
