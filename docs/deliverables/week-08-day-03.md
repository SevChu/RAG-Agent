# 第八周 Day 3：模拟 Adapter Registry 与产物追踪

- 日期：2026-09-11。
- 用户已确认 Day 2（含数据副本演练）完成，并授权进入 Day 3。
- 状态：2026-09-12 已获用户验收，随后授权 Day 4；以下保留 Day 3 当日实现与验证记录。
- 当前应用版本仍为 1.3.0，本周候选目标为 v1.4.0-beta.1；未提交或发布。

## 完成内容

1. 新增 model_adapters 与冻结迁移 `20260911_08 → 20260911_09`；每个成功任务最多一个 Adapter，四个数据库触发器保护身份、归档、不可删除/替换与成功资格。
2. 模拟 manifest 固定任务、智能体 revision/config hash、数据 revision/manifest/content/split hash、审核序号、base model/revision、目标、参数/seed、代码/Trainer/Python 身份、完成时间及模拟结果；记录独立 manifest SHA-256。
3. 完成任务时在同一写事务内提交成功终态、事件和 Adapter。文件先独占暂存、fsync、校验、同目录原子 rename，再插入数据库引用；失败回滚后不把残留文件当作成功证明。
4. 提供历史成功任务幂等补登记：无登记但文件匹配时复用；已登记而文件缺失/篡改时明确拒绝自动覆盖。失败、取消和中断任务不能登记。
5. 7 个科研 API 支持列表、详情、来源链、归档、兼容检查、存储核对和按任务补登记；完整性状态为 valid/missing/invalid。
6. 创建任务可记录兼容前驱 Adapter；只用于来源追踪，不续训或加载权重。前驱关系不可变，来源链可分页查看，归档保留文件及历史。
7. 模拟产物始终 simulated / deployable=false / not_evaluated；AgentConfiguration 拒绝在根、model、retrieval 中注入 adapter_id。本日不新增真实激活入口。
8. 产品源码包继续排除全部 app/training 实现，保留共享模型和迁移；未改历史智能体配置或在线模型路由。

详细规则见[模拟 Adapter 设计](../design-decisions/simulated-adapter-registry.md)，接口见[API 参考](../technical/api-reference.md)。

## 验证结果

| 检查 | 结果 |
|---|---|
| 首轮定向兼容回归 | 67 passed、1 skipped，46.69 秒；覆盖三日迁移、任务与双版 |
| 最终后端全量 | **517 passed、1 skipped，139.82 秒**；共 518 项，较 Day 2 增加 19 项 |
| 静态检查 | 全量 Ruff 通过；strict Mypy 131 源文件通过 |
| 实际产品源码包 | 80 passed、1 deselected，54.95 秒；未导入 app.training/app.evaluation/PyArrow |
| 迁移 | 升级、回退、再升级，原业务数据/触发器、完整性、外键及 ORM 对照通过 |
| 文件与事务故障 | 文件缺失/改写/超限/硬链接、rename 失败、文件后数据库失败、重复登记、历史补登记通过 |
| 来源与边界 | 前驱不兼容、归档、原智能体删除/数据撤销后历史追溯、伪造 checksum、运行配置注入、产品接口保护通过 |
| Windows 路径 | 原生符号链接测试因权限跳过；另用实际 Windows junction 验证拒绝写入，目标为空 |
| 前端 | 本日无 UI/客户端改动，未重复 Day 2 的前端测试和浏览器验收；Day 4 实现界面后再验证 |

首轮全量发现两个新增测试重复创建同名智能体，触发已有名称唯一性约束（515 passed、2 failed、1 skipped）。修正夹具为独立名称/复用既有数据后重跑全量，取得上表最终结果，业务代码无需为该问题调整。产品验证两条 pytest 模块重写提示不影响结果。

## 实际历史数据副本增量验证

保留 Day 2 备份及演练库，从其运行副本另建 `tmp/week08-rehearsal/day03-20260911/rehearsal.sqlite`，并只复制原演练所用的合成 training 文件。没有复制或访问正式上传、索引、模型。

- 新副本从 08 升级至 09，Alembic check 无差异，迁移前所有表记录保持。
- Day 2 两个成功任务完成幂等补登记，继续保存原代码/数据/配置哈希，没有重新训练或重写任务。
- 新建一项合成任务成功后自动登记；最终共 **3 个有效、不可部署的模拟 Adapter**。
- 全部原有记录保持，包括原正式数据的 48 条记录和 Day 2 演练记录；Day 2 来源副本文件哈希未变。
- 运行结束无排队/运行/取消中任务，租约释放，worker 停止。

这验证了真实历史状态与 Day 2 旧任务契约的兼容性，不代表真实训练、真实文档检索、浏览器界面或完整灾备已经验收。

## 主要文件

| 文件 | 职责 |
|---|---|
| backend/app/models/model_adapter.py | 共享元数据表及四个 SQL 保护触发器 |
| backend/migrations/versions/20260911_09_model_adapters.py | 独立冻结的 SQLite 增量迁移 |
| backend/app/training/adapter_schemas.py | manifest、返回结构和兼容契约 |
| backend/app/training/adapter_storage.py | 有界文件读写、暂存/rename 与目录核对 |
| backend/app/training/adapter_service.py | 来源、登记、补登记、前驱、归档和完整性 |
| backend/app/training/adapter_routes.py | 7 个科研操作 |
| backend/app/training/run_store.py | 成功事务内登记及前驱资格复核 |
| backend/app/training/trainer.py | 保持 Day 2 算法的可复核模拟 checksum |
| backend/tests/test_model_adapters.py | 生命周期、失败恢复、文件和运行隔离测试 |
| backend/tests/test_model_adapter_migration.py | 增量迁移往返及历史数据保留 |

## 证据与限制

测试证据在 `tmp/week08-day03/`，包含 targeted.xml、full.xml（首轮）、full-final.xml（最终）、OpenAPI 与最终审计；实际产品制品在 archives/。副本演练结果在 `tmp/week08-rehearsal/day03-20260911/results.json`。这些本地目录均在 Git 忽略范围内，未发布。

- SQLite 写事务协调本应用写入者；文件系统与数据库不是一个原子事务，残留文件必须核对，不自动删除。
- 已登记文件缺失或损坏不会被静默重建；需要后续具体恢复方案。暂存文件核对有界，超过 5000 个目录项明确标示扫描截断。
- manifest 完整性不等于原始数据仍获批，也不代表模型质量或可部署性。归档/补登记不改变历史审核事实。
- 文件 fsync 与 rename 不证明断电恢复或同账户恶意目录替换防护。没有操作真实模型权重。
- 第九周需另行实现真实产物格式、评测晋级、明确绑定与实际回滚验证；本周 schema 明确只接受模拟产物。

## 最终审计

OpenAPI 共 47 个路径，新增 Adapter 的 7 个路径/操作均已核对；131 个本地 Markdown 链接有效。当前训练代码指纹与最终全量测试、副本演练一致；单独导入 Registry 核心未加载模型库。正式库/.env 的哈希/存在性与前次演练一致。

## 正式边界与下一日

正式数据库和 .env 保持未修改，正式库仍在 `20260910_06`，正式 worker 未启用。未新增依赖、下载模型或数据、调用真实供应商、运行真实训练、创建提交/Tag、推送或 Release。

Day 4 从数据管理、五步模拟训练向导、任务详情及 Adapter 页面开始，使用隔离环境做浏览器全流程验收。正式升级仍在 Day 5 汇总后准备具体备份、写入窗口和恢复材料，等待用户批准。
