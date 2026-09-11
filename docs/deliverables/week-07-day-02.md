# 第七周计划日 2：智能体管理 API 与配置校验

## 状态与范围

- 日期：2026-09-08；用户已授权实施 Day 2。
- 基线：518748d（v1.2.2 界面补丁）及本地已完成的 Day 1 改动。
- 目标版本：v1.3.0；当前应用版本仍为 1.2.2，不在每日开发阶段发布。
- 管理 API 与客户端开发及自动验证完成；2026-09-09 用户确认 Day 2 审批完成；没有新增迁移或修改正式业务数据。
- Day 1 测试目录、演练副本及备份全部保留，按用户要求到本周完成后再清理。

## 接口与契约

接口前缀 /api/agent-profiles，沿用 APIResponse 的 data/error 包装：

| 方法 | 相对路径 | 功能 |
|---|---|---|
| GET | /options | 当前供应商/模型配置状态、冻结评测引用及允许用途、服务端联网总开关 |
| POST | 空路径 | 创建身份和首版配置，返回 201 |
| GET | 空路径 | 列表；可按 enabled 筛选，limit 默认 50、最大 100，offset 默认 0 |
| GET | /{profile_id} | 详情和当前 revision |
| PATCH | /{profile_id} | 修改名称/描述、启用/停用或追加执行配置 |
| POST | /{profile_id}/copy | 复制当前或指定 revision，创建独立身份，返回 201 |
| GET | /{profile_id}/revisions | 版本倒序列表，支持 limit/offset |
| GET | /{profile_id}/revisions/{revision_id} | 校验归属后读取指定版本 |
| POST | /{profile_id}/restore | 从历史配置追加新 revision，返回 200 |

不提供硬删除、原地修改 revision 或原地更换会话绑定接口。
列表按身份创建时间倒序、ID 排序；版本按 revision_number 倒序。空身份不作为可用智能体返回。

### 创建请求

name 必填，去除首尾空白后非空，最长 100 字符；名称大小写规则沿用 SQLite 唯一约束。
description 可空，最长 2000 字符；enabled 默认为 true；change_summary 默认“初始配置”，最长 500 字符。
config.model 的 provider/model 必填，其余配置字段使用 Day 1 契约的默认值并完整保存。

示例为人工合成配置，模型 ID 必须替换为 /options 返回的实际白名单项：

~~~json
{
  "name": "资料研究助手",
  "config": {
    "model": {"provider": "deepseek", "model": "configured-model-id"},
    "allowed_course_ids": [],
    "tools": {"web_search": false}
  }
}
~~~

空 allowed_course_ids 表示无资料空间授权，不能解释为所有空间。
供应商必须已经配置凭据，即使 enabled=false 也不允许保存无效执行配置；本日没有 draft 状态。

### 修改与并发协议

PATCH 必填 expected_row_version，必须匹配最新身份 row_version。至少提供
name、description、enabled、config 之一：
- name/enabled/config 不允许显式 null；description=null 清空描述。
- config 按完整配置替换，省略其可选子字段会采用 Schema 默认值，不做递归局部合并。
  编辑器应从详情读取完整 config 再修改。
- 提交 config 即追加新 revision（即使哈希相同），旧配置字节不修改。
- 单独修改名称/描述/启停不追加配置版本。
- 每次成功 PATCH 消耗一次 row_version，即使提交相同值，也形成并发检查边界。
- change_summary 仅与 config 一起提交；单独填写不会被静默忽略。
- 停用不要求外部依赖仍可用；重新启用会重新校验当前配置。
- 冲突返回 409 / CONFLICT，不在服务端或客户端自动重试覆盖。

~~~json
{
  "expected_row_version": 1,
  "enabled": false
}
~~~

并发写入先通过 SQLAlchemy 乐观锁更新身份行，再追加 revision，并在同一事务提交。
重复名称、过期版本、SQLite 写锁冲突明确返回 409；任何后续失败均回滚身份和 revision。

### 复制与恢复

copy 的 name 必填；revision_id 不填时复制读取时的当前版本，填写时必须属于原智能体。
description 可重新填写，默认 null；enabled 默认 true。新身份从 r1/row_version=1 开始，
配置哈希可与来源一致，但身份 UUID 和 revision UUID 独立；变更说明记录来源身份与版本号。
复制可以从停用智能体读取配置，但保存前必须通过当前依赖校验。

restore 必填 expected_row_version 和 revision_id，change_summary 可选。
恢复是追加 max(revision_number)+1，不修改旧版本，不移动历史会话绑定，也不自动启用停用身份。

### 读取响应

AgentProfileRead 包含 id、name、description、enabled、row_version、created_at、
updated_at 和 current_revision。AgentRevisionRead 包含 id、agent_profile_id、revision_number、
完整 config、config_sha256、change_summary、created_at。读取时验证快照结构与哈希。

历史读取不重新要求模型、资料空间和评测注册表仍可用：这些依赖失效后，用户仍可查看历史、
停用或修改展示信息。创建、复制、恢复、提交新 config、重新启用时必须重新校验依赖。

## 配置校验和权限边界

- provider/model 对应且在服务端白名单内；凭据存在但不对其远程有效性作承诺。
- 当前生成客户端按模型名路由，因此重复出现在多个供应商的模型 ID 会被拒绝，避免歧义。
- 允许的空间 UUID 必须全部存在；保存后删除空间不会改写快照，Day 3 执行前仍需重验。
- 工具仅允许现有 Web Search，数值和数量关系沿用 Day 1 严格配置契约。
- 评测引用校验整个冻结 registry 的 release version 和原始文件 SHA-256；读取和计算哈希使用同一份字节。
- offline/advisory 映射仅依据 registry 内明确的允许用途；FiQA/TRACe 只允许 offline，
  lexical hallucination 和 NLI 可 offline/advisory，均无生产阻断用途。
- Day 2 reject / Day 3 deferred 候选不在冻结 baseline registry，无法借用本接口进入配置。
- options 不包含 Key、Base URL、本机路径或模型权重；不加载模型或读取 Benchmark 样本。
- 注册表不可读/损坏时返回 409；未配置评测的智能体创建不依赖该注册表。

已提供可测试的请求权限辅助函数：服务端联网总开关 ∩ revision 权限 ∩ 本轮允许；
仅资料请求和总结禁止联网；冲突模型/越权空间拒绝。它是 Day 3 的接入基础，
本日没有将其接入旧问答或 SSE，也没有宣称 enabled 已阻断未接入的运行链路。

## 错误语义

| HTTP | code | 新接口含义 |
|---:|---|---|
| 400 | INVALID_INPUT | 白名单/空间/评测身份或用途不匹配 |
| 404 | NOT_FOUND | 智能体或属于它的版本不存在 |
| 409 | CONFLICT | 版本冲突、名称重复、写锁冲突、保存快照或本地注册表校验失败 |
| 422 | VALIDATION_ERROR | 字段缺失、未知字段、非法类型/范围/null 或空修改 |
| 503 | LLM_NOT_CONFIGURED | 所选供应商尚无凭据 |

前端仅对 /agent-profiles 接口保留服务端的具体错误提示；原资料与文件错误翻译不变。

## 测试与后续

当前针对性测试 26 passed，覆盖管理闭环、版本不变、并发单胜者、原子回滚、空间删除、
凭据失效、注册表失效、研究用途限制与安全响应；strict Mypy 108 个源文件通过。
最终验证结果：

| 检查 | 结果 |
|---|---|
| Day 2 针对性 API / 权限测试 | 26 passed |
| 后端全量测试 | 361 passed，24.33 秒 |
| Ruff（app/tests/scripts） | 通过 |
| strict Mypy | 108 个源文件通过 |
| 前端单元测试 | 12 passed |
| 前端类型检查、生产构建 | 通过；1,748 个模块 |
| 前端修改文件 Oxlint / ESLint | 通过，无自动改写 |
| OpenAPI | 1.2.2 / 26 个路径，新增 7 个路径、9 个操作 |
| 前端与 OpenAPI 对象字段 | 12 组映射一致 |
| 本地文档链接 | 120 个，0 断链 |
| Day 1 数据保留 | 4 个目录、499 个文件、20,216,754 bytes；数量和体积不变，备份及演练库仍在 |
| git diff --check | 通过 |

测试禁用正式 .env 文件读取，使用独立 week07-day02 临时数据库及现有 Fake/Mock 测试设施。
本次无正式数据库迁移或业务写入，不运行 Benchmark/test split，不发送真实模型请求。
当前工作区包含 Day 1 和 Day 2 共 30 个修改/新增文件，不包含业务数据库、模型、原始资料或预测载荷。

Day 3 接入会话和运行策略，Day 4 增加管理页面。Day 2 只提供前端 DTO、API 客户端和错误处理，
保留现有 v1.2.2 界面。旧 /courses、会话 DTO 和 SSE 均未改变，数据库迁移仍为 20260907_05。
