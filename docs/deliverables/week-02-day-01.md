# 第 2 周计划日 1 验收说明

## 交付结论

计划日 1 已完成统一解析契约、解析器路由、Markdown 结构化解析和 TXT
段落解析。没有安装新运行依赖，没有创建模型目录，也没有下载 OCR、
Embedding 或 Reranker 模型。

## 建议抽查

在 PowerShell 中执行：

```powershell
cd D:\Agentic\backend

uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\04-课程学习笔记.md" `
  --max-blocks 20

uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\03-测试数据.txt" `
  --max-blocks 5
```

Markdown 重点看：

- `summary.block_count` 为 8；
- `summary.warning_count` 为 0；
- 当前真实样本中的 `kind` 能区分 `heading`、`paragraph`、`list` 和 `code`；
- 标题下的块具有正确的 `section_path`；
- Python 代码块的 `language` 为 `python`；
- `source.line_start`、`source.line_end` 与原文件行号相符。

TXT 重点看：

- `summary.block_count` 为 3427；
- `summary.character_count` 为 772819；
- `summary.warning_count` 为 0；
- 前 5 个段落顺序与原文件一致；
- 块索引从 0 连续递增，起止行号合理；
- 只展示 5 个块，不会把大文件全部输出到终端。

## 通过标准

- 两条命令退出码为 0，没有 Python Traceback；
- 中文、英文和代码没有明显乱码或丢失；
- Markdown 结构类型、章节归属和 Python 代码语言正确；
- TXT 段落顺序正确；
- 行号抽查与源文件一致；
- 两个真实样本均无解析警告；
- 原文件内容和时间不被修改。

如果结构块错误、章节路径串到错误标题、正文乱码、块顺序改变、行号明显错误，
或命令异常退出，则本计划日应判定为未通过并返工。

PDF、PPTX、DOCX、OCR、分块、Embedding、Qdrant 和自动索引状态不属于本次
抽查范围，不能因为这些能力尚未出现而判定计划日 1 失败。
