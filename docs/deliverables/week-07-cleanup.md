# 第七周验收后清理记录

执行日期：2026-09-11。用户通过日志和 README，并明确要求清理 Day 1～Day 5 不再需要的文件和缓存。

## 实际范围

- tmp 下 16 个 week07-day01～day05 测试/演练目录，包括旧 UI 隔离库和 Day 5 审计工作目录。
- Day 1 单独 rehearsal.db，以及 Day 2/3 的旧 OpenAPI 快照。
- 后端 Mypy/Ruff、前端 Vite/工具缓存，以及应用、测试、脚本的 Python __pycache__。
- 合计 52 个目标、2,153 个文件、237,041,868 bytes（约 226 MiB，按删除文件逻辑大小统计）。

删除前逐一解析绝对路径，确认在工作区内；拒绝符号链接/junction，检查没有引用这些路径的活动
进程。仅在核对后使用 PowerShell 原生文件操作，不跨 shell 构造删除命令。

## 保留与验证

Day 4 截图/result.json 归档为 output/releases/v1.3.0-cleanup/day04-ui-evidence.zip；
Day 5 审计记录保留在同目录 day05-audit。详细清单和结果为 cleanup-plan.json / cleanup-result.json。
这些证据仅在本地留存，不作为 Release 附件。

正式 data/app.db、删除功能升级备份以及仓库外 Day 1 完整备份的数据库 SHA-256，清理前后完全一致。
uploads、Qdrant、本机 .env、研究数据、模型、backend/.venv 与 frontend/node_modules 的已安装
依赖保留。本地继续启用 research 模式。迁移脚本、测试源码与冻结研究记录均保留。

## 例外

backend/.pytest_cache 的 Windows ACL 拒绝读取目录及权限信息，无法检查其内容，故未递归删除。
其他已列明目标均确认不存在。此旧缓存不影响发布或现有独立 basetemp 测试；未取得系统管理员
权限，也未更改系统 ACL。后续可由具有该目录权限的本机账户清理。
