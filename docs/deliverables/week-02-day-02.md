# 第 2 周计划日 2 验收说明：结构化分块

## 交付结论

计划日 2 已按照原定内容完成结构化分块：章节感知组合、列表/表格/代码保护、完整
来源元数据，以及 Chunk 长度、数量、重叠、来源覆盖和异常统计均已实现。

用户于 2026-08-01 完成抽查并确认验收通过。

同日完成的 DOCX/PPTX 解析作为额外前置成果保留，但不再替代本计划日的正式验收
对象。本日未新增运行依赖，未创建模型目录，也未下载任何模型。

## 默认参数说明

- 目标长度：600 estimated tokens；
- 目标重叠：80 estimated tokens；
- 不跨章节或 PPTX 主标题合并；
- 列表项、表格和代码块不从中间切断；
- 普通长段落优先沿句末、换行或空白拆分；
- 80 是同一章节发生拆分时的目标，不会为了凑重叠而跨章节复制正文。

因为 BGE-M3 尚未到计划下载日，目前使用确定性 token 估算器，不声称是模型真实
token 数。后续加载 BGE-M3 tokenizer 时可以替换计数器并重新校准，Chunk 接口和
来源元数据无需重写。

## 建议抽查

以下命令均为只读，不修改原文件、数据库或上传状态。

### 1. Markdown：章节、列表和代码保护

```powershell
cd D:\Agentic\backend

uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\04-课程学习笔记.md" `
  --chunks `
  --max-blocks 1 `
  --max-chunks 4 `
  --course-id acceptance-course `
  --document-id acceptance-markdown
```

应看到：

- `target_tokens` 为 600，`overlap_tokens` 为 80；
- 8 个源块全部覆盖，`uncovered_source_blocks` 为 0；
- 生成 4 个 Chunk，长度为 46～70 estimated tokens；
- 每个 Chunk 开头包含所属标题路径；
- 列表仍是完整列表，Python 代码仍是完整代码块；
- `anomaly_count` 和 `warning_count` 均为 0。

### 2. DOCX：章节感知与完整来源

```powershell
uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\计算机大型课程结构作业\01-课程指导文档.docx" `
  --chunks `
  --chunk-index 0 `
  --max-blocks 1 `
  --course-id acceptance-course `
  --document-id acceptance-docx
```

应看到：

- 76 个源块全部覆盖，生成 14 个 Chunk；
- 长度范围为 29～379，异常数为 0；
- Chunk 0 只属于“实验一… / 实验目的”，没有混入下一章节；
- “了解 ZStack 平台”等列表项保持完整；
- 来源中包含传入的课程/文档 ID、文件、解析器、章节、精确源块索引和块类型。

### 3. PPTX：幻灯片隔离与重复标题来源

```powershell
uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\02-课程课件.pptx" `
  --chunks `
  --chunk-index 2 `
  --max-blocks 1 `
  --course-id acceptance-course `
  --document-id acceptance-pptx
```

应看到：

- 3147 个源块全部覆盖，`uncovered_source_blocks` 为 0；
- 生成 137 个 Chunk，长度范围为 6～597；
- Chunk 2 为“主要内容”幻灯片，`slide_numbers` 仅包含 3；
- Chunk 不混入相邻幻灯片；
- 重复标题按出现位置分别保存，不会指向另一页同名标题；
- 超目标、受保护块超长和异常数量均为 0。

### 4. TXT：600/80 长文本效果

```powershell
uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\03-测试数据.txt" `
  --chunks `
  --chunk-index 0 `
  --max-blocks 1 `
  --course-id acceptance-course `
  --document-id acceptance-txt
```

应看到：

- 3427 个源块全部覆盖，生成 755 个 Chunk；
- 长度范围为 3～600，平均约 375.4；
- 748 个 Chunk 含重叠，平均实际重叠约 66.93 estimated tokens；
- 没有超过 600 的 Chunk，没有来源覆盖缺口或其他异常；
- Chunk 0 的段落衔接自然，没有在单词或句子中间出现明显破碎。

## 通过标准

- 四条命令均正常退出，没有 Python Traceback；
- 四份资料的 `covered_source_blocks` 等于 `source_block_count`；
- `uncovered_source_blocks`、`over_target_chunks` 和 `anomaly_count` 均为 0；
- 标题上下文与正文匹配，不跨章节或幻灯片污染；
- 列表项、表格和代码没有从中间切开；
- 普通长文本的相邻 Chunk 有合理重叠；
- 每个 Chunk 的课程、文档、文件、章节和原始位置能够追溯；
- 抽查 Chunk 在语义上可独立理解；
- 你认可 600/80 作为当前默认参数。

如果语义明显被切断、不同章节混入同一 Chunk、列表/表格/代码从中间断裂、来源页码
或幻灯片错误、存在未覆盖源块，或者统计与上述结果明显不符，则计划日 2 不通过。

结构化资料的平均 Chunk 会明显小于 600，这是“不跨章节”的预期结果；600 是上限
目标，不是必须填满的固定长度。如果你认为 DOCX/PPTX 的 Chunk 过碎，可以在验收时
提出，但不建议仅为了接近 600 而跨章节合并。
