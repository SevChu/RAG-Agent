# 第 4 周计划日 1 验收说明

## 验收目标

确认混合来源的基础契约、选择器、双来源展示和独立 Web Search 适配器已经可用，同时确认
“仅课程资料”不会搜索。计划日 1 不验收混合答案；条件搜索与 `[外n]` 正文引用属于计划日 2。

## 1. 自动测试

后端：

```powershell
cd D:\Agentic\backend
.venv\Scripts\python.exe -m ruff check app tests scripts
.venv\Scripts\python.exe -m mypy app
.venv\Scripts\python.exe -m pytest -q
```

预期：Ruff 与 Mypy 无错误，`143 passed`。

前端：

```powershell
cd D:\Agentic\frontend
npm.cmd run type-check
npm.cmd run test:unit -- --run
npm.cmd run build
```

预期：类型检查通过，`10 passed`，Vite 构建成功。

## 2. 前端回答范围与课程引用

按项目原有方式启动后端和前端，打开 `http://127.0.0.1:5173/assistant`：

1. 确认“回答范围”默认是“课程资料 + 外部补充”；
2. 切换到“仅课程资料”，确认说明文字明确不会发起 Web Search；
3. 选择已有资料的课程，提出资料能够回答的问题；
4. 展开引用卡片，确认正文和卡片显示 `[课1]`，仍可查看文件、章节、页码或行号；
5. 查看回答底部，确认显示本次回答范围和外部搜索状态说明。

通过标准：两个范围可切换，默认值正确；当前页面明确说明 Day 1 仍按课程证据作答，不会把尚未
接入的能力伪装成混合回答；课程引用可正常恢复、展开和核验。

## 3. “仅课程资料”后端边界

自动测试 `test_course_only_scope_is_preserved_and_search_is_not_requested` 已验证：请求
`answer_scope=course_only` 时响应保持该范围，`external_search.triggered=false`、
`status=not_requested`，并返回“仅课程资料模式已关闭外部检索”。

也可在浏览器中选择“仅课程资料”后询问课程外问题。通过标准：仍按既有证据门拒答，不出现
`[外n]`，不使用模型常识静默补齐。

## 4. 真实外部搜索适配器

以下命令会产生一次真实 API 请求和少量模型费用：

```powershell
cd D:\Agentic\backend
.venv\Scripts\python.exe -m scripts.verify_external_search "Python 3.14 官方发布文档与主要变化"
```

通过标准：

- `status: succeeded`；
- `raw/qualified` 至少有 1 条合格结果；
- 输出使用 `[外n]`，每条包含质量类别、发布方、真实 HTTPS URL 和证据摘要；
- Python 官方文档或 Python Software Foundation 页面应排在普通博客之前；
- 输出中不出现 API Key。

外部服务偶发超时、限流或 HTTP 5xx 时，脚本会显示 `status: failed` 和安全原因，而不是泄露
密钥或堆栈中的响应内容；可稍后重试。该结构化失败状态将在计划日 2 用于课程回答降级。

## 整体通过标准

- 默认范围、可选课程范围、请求/响应字段和会话快照一致；
- `[课n]` 与未来 `[外n]` 的编号、字段和卡片样式已分离；
- 外部搜索结果必须来自服务端真实结果 URL，无法对齐的摘要会被丢弃；
- 学术、机构和官方来源优先，低质量站点不作为合格证据；
- 课程范围不会搜索，Day 1 页面不误称已经完成混合回答；
- 自动测试和真实搜索脚本满足上述结果。

## 用户验收结果

用户于 2026-08-04 完成验收并确认“验收通过，基本上没问题”。第 4 周计划日 1 正式完成。
