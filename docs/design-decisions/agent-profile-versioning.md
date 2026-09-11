# AgentProfile 配置版本与会话绑定

- 日期：2026-09-07。
- 目标：第七周 / v1.3.0；Day 1 建立持久化和配置契约，管理 API 与运行接入分别为 Day 2/3。
- 关联：[周计划](../deliverables/week-07-plan.md)。

## 1. 身份与版本

AgentProfile 保存 id、唯一名称（1～100 字符）、描述、enabled、row_version、创建/更新时间。
名称和描述是可编辑的展示信息，不属于执行配置；历史界面可以显示当前名称，但必须显示原绑定
revision。row_version 是数据库行的乐观锁，和配置 revision_number 是不同概念。

AgentProfileRevision 保存 UUID、所属 AgentProfile ID、正整数 revision_number、完整 config JSON、
config_sha256、change_summary 和 created_at。同一智能体的 revision_number 唯一。
SQLite UPDATE/DELETE 触发器保护全部 revision 字段，BEFORE INSERT 拒绝重复 ID 或版本号，
使 INSERT OR REPLACE 也不能覆盖快照；覆盖 ORM 更新和直接 SQL。有 revision 的
智能体受外键 RESTRICT 保护，不能硬删除。应用通过停用保留记录。

当前配置定义为该智能体 revision_number 最大的记录，不另存可漂移的 current_revision_id。
这避免双向外键和指针维护。Day 2 服务需在同一事务创建身份和首版配置；空身份不能对外成为可运行
智能体。后续追加 max+1，并结合 row_version 检查及唯一约束处理并发；不能把撞号当成功。
回退为复制旧配置并追加新 revision，即使配置哈希相同也保留新的恢复记录。

row_version 的 SQLAlchemy 乐观锁已在 Day 1 实现；API 端的 expected version 和冲突映射属于 Day 2。
绕过 ORM 的批量身份更新不会自动得到乐观锁保护，管理服务必须使用 ORM 或显式 compare-and-swap。

## 2. 会话固定绑定

Conversation 增加两个可空 UUID：
agent_profile_id 和 agent_profile_revision_id。CHECK 要求同时为空或同时非空；
复合外键同时验证 revision 存在且属于指定智能体，防止仅靠两个独立外键造成错配。
索引支持按智能体查会话。绑定在 INSERT 时确定，SQLite 触发器拒绝后续换版、换智能体、
清空绑定，以及把既有 legacy 会话原地绑定。会话重复 ID 的 INSERT OR REPLACE 也被拒绝，防止替换绑定及级联删除消息。
标题、时间和普通消息写入仍可更新。

旧会话迁移后两个字段都为空，继续兼容路径；没有可靠历史配置快照，因此不进行“猜测回填”。
Day 3 接入新绑定会话，现有 API/SSE DTO 在 Day 1 不变。换智能体或更新配置另建会话，
不将原会话历史静默复制到新身份。资料空间原有 Course/course_id/API 命名继续保留。

停用语义在本周采用：历史可读，禁止新会话和继续生成，重新启用后恢复。Day 1 只持久化 enabled，
服务和执行入口的停用校验分别在 Day 2/3 落地；不能把当前模型字段等同于完整停用功能。

## 3. 配置快照契约

内部 Pydantic 契约位于 backend/app/agents/configuration.py，不是公开 HTTP Schema。
所有层级禁止未知字段，配置对象及嵌套对象冻结，集合使用 tuple。序列化补全默认值，
资料空间集合与评测引用排序；JSON key 排序、UTF-8、紧凑分隔符，计算 SHA-256。
ORM 插入时校验并归一化 JSON 与哈希；read_config 重新校验。直接 SQL 无法自动计算 SHA-256，
运行入口后续必须调用 read_config，不能只信任数据库字符串长度检查。

| 字段 | Day 1 契约 |
|---|---|
| schema_version | 1；不静默接收未知版本 |
| system_prompt | 最多 20,000 字符；只表达角色和任务偏好 |
| model | 显式 provider + model；不含 Key、Base URL 或本地模型路径 |
| allowed_course_ids | 最多 100 个唯一 UUID；空集合表示无资料空间授权 |
| tools | 仅现有 Web Search 布尔权限 |
| context | bounded-history-v1；空间默认 6 条/6000 字符，快速对话 10 条/8000 字符 |
| retrieval | course-rag-v1；问答、总结、组卷的候选数、Top-K、来源/字符预算与相似度门 |
| evaluation_profiles | 最多 20 个唯一 profile；固定 registry 版本、SHA-256 及 offline/advisory 用途 |

静态契约不读取 .env、资料或 registry，不连接任何数据库/模型。供应商可用性、模型白名单、
空间存在性和真实评测 profile 身份校验在 Day 2 服务层实现，执行前在 Day 3 再校验。
禁止未知 api_key 字段不等同于 DLP：用户自由文本可能含敏感内容，配置快照保存在被 Git 忽略的
本地数据库；未经审核不能导出真实系统提示或配置实例到公开仓库。

资料会话仅检索其 course_id；它必须属于 allowed_course_ids，不能将允许列表解释为跨空间召回。
快速对话仍不访问资料空间。总结禁用联网、引用证据门、组卷约束及系统安全策略优先于自定义提示。
请求可进一步收紧范围，不能提升权限。已有绑定会话不接受冲突模型参数；旧路径维持原规则。

course-rag-v1 是现有在线算法身份，不是 fiqa-dense-retrieval 等研究基线的别名。本周不把研究
候选接入生产：Day 2 reject、Day 3 deferred、NLI offline/advisory 限制全部保持。
评测引用只记录选择和复现身份，不自动读 test、不自动调评分器、不拦截回答。

## 4. 可追溯性的限度

revision 固定的是应用执行配置。运行环境凭据、供应商地址、服务器总开关、代码部署、资料内容、
索引和远端模型仍可能变化；配置哈希不是完整运行环境哈希，也不保证答案逐字复现。
Day 3 应记录 revision、配置哈希、实际模型及必要策略身份，遇到失效依赖明确失败而非换模型。
新增执行字段需显式配置 Schema/策略版本演进，不能通过新增默认值悄悄重解释已冻结 JSON。

## 5. 迁移与回退

新增迁移 20260907_05，父版本 20260810_04。建两张表，并批量重建 conversations 添加
可空字段、CHECK、复合外键和索引；随后创建保护触发器。Alembic SQLite 专用连接保持
foreign_keys OFF，避免重建被引用的 conversations 时级联删掉 messages；应用连接仍为 ON。
迁移在任何改表前拒绝 FK-on 连接和既有外键损坏，完成后执行 foreign_key_check。

迁移只支持实际 SQLite 数据库的在线 Alembic 执行，不提供 --sql 离线生成路径。
不支持绕过 Alembic 用 create_all 更新旧数据库。create_all 用于空测试库，安装相同约束和触发器。

升级不创建默认智能体，不回填旧会话，不改变旧消息、引用、资料和 Token 记录。
回退到 20260810_04 会删除 AgentProfile、全部 revision 和会话绑定字段；保留所有会话和消息，
包括升级后创建的会话内容。再次升级不会找回已删除配置。实际回退前必须保留完整数据库备份，
不能把 downgrade 当作业务配置恢复；业务恢复应追加 revision。

Day 1 开发阶段仅在隔离合成数据库及其 SQLite backup 副本演练。
2026-09-08 用户授权后已完成正式数据库备份和升级，见[升级记录](../deliverables/week-07-day-01-database-upgrade.md)。
部署本次修改后的 ORM 前必须停止后端、备份正式数据库并执行迁移；旧结构不具备新增列，
不能直接启动新代码。当前正式库已经完成本版本迁移，无需重复执行。


## 6. Day 2 实施补充（2026-09-08）

管理接口、原子追加和 API expected_row_version 冲突协议已完成，详见
[Day 2 接口契约](../deliverables/week-07-day-02.md)。同一配置再次提交会产生新 revision；
恢复历史配置也追加版本；展示信息和启停只消耗 row_version。
依赖失效不影响历史读取，但创建/复制/恢复/新配置/重新启用均校验当前依赖。
请求权限辅助函数已提供并测试，运行链路的实际接入仍为 Day 3。


## 7. Day 3 实施补充（2026-09-09）

创建时选择当前 revision，并在 INSERT 时写入两项绑定 ID；不提供客户端指定旧 revision。
同一请求只选择一次，后续请求按固定 ID 联查，不查最新版本。依赖验证在每轮开始执行，
停用不抹掉历史、不取消已发出的外部请求；重新启用后会话继续使用原 revision。

服务端与 revision 的上下文/检索预算取小值，问答证据阈值取大值；不覆盖全局 Settings。
自定义提示与内置任务约束组合，保留引用/拒答/总结仅资料/组卷检查。
离线评测注册表失效不转化为在线拦截器；运行只检查当前模型和全部允许空间是否仍存在。

新增诊断保存在既有消息 retrieval JSON，并通过 JSON/SSE/历史响应提供，因此无需迁移。
实际模型列表只记录本轮生成网关已返回的标识；工件重放和无调用拒答为空。
完整契约见 [Day 3 报告](../deliverables/week-07-day-03.md)。

## 2026-09-10 补充：逻辑删除

用户验收后要求增加删除入口。AgentProfile 增加 deleted_at，逻辑删除同时设 enabled=false，
列表默认排除；身份、唯一名称、revision 和会话绑定仍保留。详情和版本只读，写入/复制/恢复
及生成被拒绝；无回收站或硬删除。首次删除需要 expected_row_version，重复删除幂等。
此决策扩展最初仅停用的管理能力，不撤销不可变版本与外键规则。
