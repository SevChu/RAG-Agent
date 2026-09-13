# 微调平台数据契约与审核边界

> v1.4.0-beta.1 候选当前态：数据、任务、模拟产物和五步界面均已实现并验收；正式 09 迁移与 worker
> 已获准完成。下文按日期保留设计演进；早期“尚未实现/未升级”仅表示当日状态。
> 本候选仍只含 FakeTrainer，没有真实权重、真实评测或在线绑定。当前维护入口见
> [训练平台](../technical/training-platform.md)，发布等待[文档审阅](../releases/v1.4.0-beta.1-approval.md)。


- 日期：2026-09-11；第八周 Day 1。
- 依据：[详细计划](../deliverables/week-08-plan.md)、[产品/科研分离](product-research-editions.md)、[AgentProfile 版本契约](agent-profile-versioning.md)。
- 实现范围：训练数据 Registry、审核、使用资格和共用迁移。TrainingRun/TrainingEvent/ModelAdapter 是后续接口设计，Day 1 尚未创建这些表或执行训练。

## 1. 数据模型与版本

| 实体 | Day 1 行为 |
|---|---|
| TrainingDataset | 稳定 UUID、唯一名称、row_version、创建时间；空身份允许存在，不能作为训练版本使用 |
| TrainingDatasetRevision | dataset_id、递增 revision_number、完整 manifest、manifest_sha256、冻结校验报告、创建时间；内容及元数据不可变 |
| TrainingDatasetReview | revision_id、递增 sequence、审核状态、审核人、意见、时间；只能追加 |

新增迁移 `20260911_07`，父版本 `20260910_06`。SQLite 的六个触发器分别拒绝 revision/review 的 UPDATE、DELETE 与 INSERT OR REPLACE；唯一约束保护版本号/事件序号，外键 RESTRICT 保留历史链。ORM create_all 与 Alembic 具备相同约束，迁移不导入当前应用模型。

内容、来源、许可、PII 声明或空间归属变化必须新建 revision，再次审核。审核状态从最新事件读取，不写回冻结快照。新增 revision 与审核操作都检查数据集 expected_row_version，并在事务中领取写入权；并发只有一个请求成功，失败回滚不消耗版本号。

未来 TrainingRun 固定 AgentProfile revision/config hash、DatasetRevision、split hash、训练目标、base model revision、参数、seed 和 Trainer/代码身份；TrainingEvent 追加执行进度；ModelAdapter 关联唯一成功 run 和产物 manifest/hash。任务、产物和配置关联不等于启用到在线运行。

## 2. manifest 与样本格式

manifest 为 JSON 对象，禁止未知字段和重复 JSON key；schema_version 为整数 1。必填：target、source、license_id、license_notes、training_allowed、pii_status、pii_notes；source_course_ids 默认为空。target 仅 scorer/reranker，pii_status 为 pending/clean/redacted，training_allowed 必须为布尔值。

- scorer：id、source_id、group_id、split、query、response、evidence（非空字符串数组）、score（有限数值，0～1）。这是平台原始标签契约，不等同于某个具体模型的训练损失格式。
- reranker：id、source_id、group_id、split、query、document、relevance（严格整数 0/1）。真实 pairwise/listwise 转换由未来 Trainer 明确实现。
- split 只接受 train/validation，两个 split 都必须非空；test、sealed_test、dev 等别名及额外嵌套字段直接拒绝。
- 仅导入用户显式上传的 UTF-8 JSONL，不扫描原资料空间、会话、现有数据集或封存 test。JSONL 空行、损坏编码、未知字段、重复 JSON key 和标签越界返回安全的错误代码/行号。
- source_course_ids 声明来源空间；非空时登记、批准和使用资格校验都验证存在性。外部合成/自有资料可以为空；不据此提供任意文件读取。

Day 1 不提供 test Registry。训练选择器的后端数据源本身不存在 test revision，不能靠直接传 ID 绕过。不识别提交者把真实 test 样本伪称为 train 的语义欺骗；来源审核仍需人工核对，不能宣称自动检测了全部数据污染。

## 3. 校验与审核

初始 draft → pending_review → approved/rejected；approved → revoked；rejected/revoked 可以重新送审。修改文件不能通过重新批准覆盖原 revision，必须创建新版本。审核人是本地审计署名，不是认证账户或双人复核机制。

校验报告区分 valid（结构合格）与 approvable（结构及治理检查均通过）：结构错误不持久化 revision；许可未知/未允许训练、PII 待审、命中敏感模式、重复/污染可登记为隔离 draft，但不能批准。含疑似敏感信息的展示元数据拒绝登记，审核意见同样检查。原始样本只存被 Git 忽略的本地目录，列表与错误不包含样本正文。

去重协议 `normalized-alnum+char5-jaccard-0.85-v1`：

1. 样本 ID 唯一；source_id/group_id 经 NFKC、casefold、仅保留字母数字归一化后，不得跨 split。
2. 输入文本（不含 ID、split 或标签）按同一方式归一化并计算 SHA-256，识别精确内容重复。
3. 跨 split 检查字符 5-gram 集合 Jaccard，相似度 ≥0.85 时阻止批准。不是语义模型，不能发现所有改写或跨语言重复。
4. 原文件 SHA-256 固定原始字节；split SHA-256 使用按原顺序排列的规范化样本 JSON（排序键、UTF-8、紧凑分隔符、每行 LF）。manifest 单独计算规范 JSON 哈希。

PII 基础规则检查邮箱、中国大陆手机号和典型密钥/密码模式，扫描 JSON 解码后的内容以防 Unicode 转义绕过。规则会漏报或误报；clean/redacted 声明和审核意见是必要补充，不宣称已完成全面 DLP 或自动许可判断。

## 4. 使用资格与撤销

`DatasetService.require_eligible` 是 Day 2 的服务端入口，要求具体 dataset/revision/agent ID。它重新读取审核状态，验证智能体启用且未删除、最新配置可读、数据来源空间为允许空间的子集、原空间存在、文件及元信息哈希一致、校验报告与冻结记录一致且可批准。前端 eligible 标志不能作为任务授权依据。

Day 1 已保证撤销后再次校验拒绝使用；尚无训练任务，所以没有“已取消排队/运行任务”的实现结论。Day 2 必须在提交和实际领取任务时调用资格门，并与审核写入建立事务/版本冲突保护；任务冻结配置不得绕过之后的权限撤销。运行中取消和重启恢复按 Day 2 落地。

## 5. 存储、限额与故障行为

- 默认 `TRAINING_DATA_DIR=../data/training`（相对后端工作目录）；上传文件名完全不参与存储路径。服务端仅用 revision UUID 生成 `<uuidhex>.jsonl`，没有任意服务端路径、URL、压缩包或自动下载入口。
- 检查根目录及祖先的符号链接/Windows reparse point，拒绝读取硬链接或非普通文件；所有解析后路径必须仍在指定根内。这是本地应用边界，不防拥有同一 OS 账户写权限的攻击者实施文件系统竞争。
- 整个训练 POST 请求在 multipart 解析前限制为 8 MiB + 64 KiB；文件最多 8 MiB、5000 行、每行 64 KiB，manifest 最多 16000 UTF-8 bytes。超额不截断后继续使用。
- 近重复检测最多累计 1000000 个 shingle、200000 次候选比较，超出返回 DEDUP_WORK_LIMIT 并拒绝批准。问题列表最多 50 条，同时返回总数。
- 文件独占创建、flush/fsync 完成后才提交数据库引用。数据库/文件错误回滚元数据；极端断电或 commit 失败可能留下未引用 UUID 文件，它不会出现在目录 API 或获得使用资格。清理须先核对引用，不提供自动破坏性清理。
- 未提供原始样本下载或公开导出；新增版本不删除旧文件。downgrade 只移除三张新表和相关触发器，保留文件；恢复完整状态需同时保留数据库及对应文件，不能把 downgrade 当作审核撤销。

## 6. 产品模式与环境

训练管理位于 `app/training`，没有 Torch/Transformers/PEFT/TRL/bitsandbytes 或评测注册表导入。完整开发仓库包含该模块，product 模式管理 API 返回 403；产品发行包完全排除模块，启动按 RESEARCH_AVAILABLE 跳过路由及请求限额中间件，相关 URL 返回 404。共用 ORM 和迁移仍随两版分发，旧智能体/会话哈希不变。

导入审计区分数据核心和 HTTP 接入：DatasetService/校验/存储不导入训练栈；HTTP 路由复用现有 app.schemas，其包初始化仍会间接导入既有检索栈的 Torch。这是已有共享 Schema 耦合，本轮未重构；导入库不等于加载模型权重或执行训练。

Fake Trainer 计划采用现有原生 Windows。Day 1 仅通过已安装包元数据和 nvidia-smi 查询环境，没有加载/下载模型，也没有验证 CUDA 训练。真实环境、模型许可、依赖、显存/时间及成本在第九周选型后具体审查。

## 7. 本轮执行边界

用户已批准第八周计划及 Day 1 开发，要求高风险/需操作事项先审查。本轮仅工作区源码、隔离合成测试库、临时包和文档；未修改正式数据库、.env 或版本号，未新增依赖、读取私有训练材料、执行真实训练/官方 test、提交、推送或发布。

## 2026-09-11：Day 2 接入补充

Day 1 已验收，持久化任务、Fake Trainer 和撤销联动已在 Day 2 实现；具体数据模型、租约、事务竞争和历史保留规则以[任务生命周期](training-run-lifecycle.md)为准。此前 Day 1 范围描述作为当日记录保留，正式数据库仍未升级。
