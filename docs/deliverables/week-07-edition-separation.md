# Week 7 补充：产品版与研发/科研版分离

完成日期：2026-09-11。用户要求普通智能体全流程不需要 Benchmark，科研用途再准备评测集；
本次从额度中断处继续完成。状态：实现和自动验证完成，供用户继续验收；v1.3.0 尚未发布。

## 交付行为

| 项目 | 产品版 | 研发/科研版 |
|---|---|---|
| 资料、检索、问答、总结、组卷、快速对话、智能体管理 | 完整保留 | 完整保留 |
| 智能体研究设置 | 隐藏，不加载注册表 | 显示研究关联和适用范围提示 |
| 离线评测模块、工具、冻结配置、公开聚合结果 | 源码包不包含 | 源码包包含 |
| 原始评测集和研究模型 | 不需要、不下载 | 具体实验按需另行准备 |
| 安装 | 默认运行依赖 | 另加 research 依赖组 |

完整仓库默认 AGENTIC_EDITION=product。科研包默认 research；纯产品包不允许仅通过环境变量
开启缺失的科研功能。两版入口均为 app.main:app，默认后端 8000、前端 5173。
安装见[产品版](../editions/product.md)和[科研版](../editions/research.md)，
技术边界见[设计决策](../design-decisions/product-research-editions.md)。

产品模式保留旧 revision、哈希和旧研究引用作为历史元数据；编辑运行参数、启停、恢复、
继续固定版本对话无需注册表。复制时去掉研究引用，新建/新增引用在产品模式下拒绝。
没有新增迁移、修改正式数据库、删除旧智能体、清理 Day 1 数据/备份或本机研究资产。

## 验证与证据

- 完整后端：402 passed，46.22 秒；新增版本边界、历史兼容和打包测试。
- 前端：25 passed；类型、Oxlint/ESLint 和生产构建通过（1,756 模块）。
- Ruff 与 strict Mypy 通过；Mypy 覆盖应用、测量脚本和打包器，共 113 个源文件。
- 产品浏览器 22 项、科研浏览器 3 项检查通过，无页面错误；科研提示经截图复核。
- 解压产品源码包，阻止 app.evaluation / PyArrow 导入，运行管理、资料上传、会话、
  四类生成、删除及供应商模拟路由：80 passed、1 deselected。排除的是专门创建科研引用
  的测试；跨模式历史兼容由完整仓库测试覆盖。应用确认从解压产品目录导入。
- 验证使用隔离 SQLite、合成资料、FakeGateway / MockTransport；未调用真实供应商。
- 169 个锁定依赖的版本/来源不变；研究显式依赖移入 research 组。产品默认依赖树无
  PyArrow；scikit-learn 仍作为检索共享传递依赖安装。

产品验证复用已有开发环境，并通过导入阻断检查依赖边界；没有执行全新联网环境的依赖安装，
也没有重新验证真实检索模型/供应商的回答质量。安装脚本提供明确依赖组，不自动准备模型或评测数据。

## 本地源码制品

使用 scripts/build_editions.py --edition both 构建到 output/editions：

- agentic-v1.3.0-candidate-product-source.zip
- agentic-v1.3.0-candidate-research-source.zip

包内 edition-manifest.json 记录模式、应用版本与逐文件 SHA-256。外部 SHA256SUMS.txt 用于
核对 ZIP；本地 audit.json 记录制品校验。排除 .env、业务数据库、上传/索引、模型、原始评测集、
缓存、node_modules、venv 和 dist。这是源码候选包，非预装依赖的桌面安装器。
应用元数据仍为 1.2.2，没有 commit、Tag、push 或 Release。

科研关联不等于性能保证；客户自有评测套件、完整运行环境快照与自动重新评测仍为后续工作。
