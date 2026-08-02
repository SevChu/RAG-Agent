# 第 2 周整体验收说明：知识库入库

## 整体结论

第二周“知识库入库”的计划功能已经全部实现，自动验收通过，等待用户完成最后的资料结构
肉眼抽查。系统现在具备从五类课程资料上传到课程隔离 Qdrant 的完整本地闭环：

```text
上传 → 解析/OCR → 结构化分块 → BGE-M3 → Qdrant → completed
                         ↘ 失败清理 → 中文原因 → 重新处理
```

## 五个计划日完成情况

| 计划日 | 交付 | 结果 |
|---|---|---|
| 日 1 | 统一解析契约、TXT、Markdown | 已验收 |
| 日 2 | 章节感知分块、Office 解析、来源与统计 | 已验收 |
| 日 3 | PDF 原生/OCR、BGE-M3、Qdrant、课程隔离 | 已验收 |
| 日 4 | 自动任务、状态、失败提示、重试与删除清理 | 已验收 |
| 日 5 | 三方一致性审计、真实五类入库、周级回归 | 自动部分通过，待肉眼抽查 |

## 周目标对照

| 原周目标 | 完成证据 |
|---|---|
| 五类文件解析 | PDF、PPTX、DOCX、MD、TXT 全部真实入库 completed |
| PDF 原生优先、扫描 OCR | 原生/扫描/混合路径有测试；七页真实扫描教材完成 OCR 入库 |
| 页码保留 | PDF 12 个 Chunk 全部带 1～7 页码 |
| 结构化分块 | 默认 600/80，章节感知，保护列表/表格/代码，输出异常统计 |
| Embedding | 本地 bge-m3，1024 维 Dense，GPU/CPU 回退已验证 |
| Qdrant 入库 | `knowledge_chunks_v1`，真实验收共 711 Point |
| 课程隔离 | 所有向量操作要求 `course_id`；跨课程同内容实测允许 |
| 重复检测 | 同课程相同 SHA-256 实测返回 409 |
| 索引状态 | pending → processing → completed/failed，前端自动轮询 |
| 删除与重索引 | 单份/批量/课程清理向量；重索引替换旧 Point |
| 一致性检查 | 可重复审计 SQLite、原文件、Qdrant 及来源元数据 |

## 真实周级验收结果

隔离验收课程“第二周整体验收-数据结构”保留 5 份资料：

| 指标 | 结果 |
|---|---:|
| 课程 | 1 |
| completed 资料 | 5 |
| 上传原文件 | 5 |
| Qdrant Point | 711 |
| PDF OCR Chunk | 12 |
| PPTX Chunk | 137 |
| TXT Chunk | 539 |
| Markdown Chunk | 9 |
| DOCX Chunk | 14 |
| 自动一致性错误 | 0 |
| 自动一致性提醒 | 0 |

另验证重复上传、CSV、损坏 PDF、跨课程同内容、课程删除和重新索引。临时异常记录与隔离
课程均已清理，最终审计没有孤儿文件或孤儿向量。正式库保持 0 资料、0 文件、0 Point，
没有被验收数据污染。

## 质量结果

| 检查 | 结果 |
|---|---|
| 后端 pytest | 94 项通过 |
| Ruff | 通过 |
| Mypy strict | 72 个源文件通过 |
| 前端 Vitest | 2 个文件、8 项通过 |
| 前端 Lint | 通过 |
| TypeScript | 通过 |
| Vite production build | 通过 |
| npm audit | 0 个已知漏洞 |
| 真实五类端到端 | 5/5 completed |
| SQLite / 文件 / Qdrant 审计 | 通过 |

## 你如何完成整体结果验收

先按 `docs/deliverables/week-02-day-05.md` 打开本地结构报告，抽查 PDF、PPTX、Markdown、
DOCX 和 TXT 的开头/中部/末尾样本。然后确认下面三项：

1. 五类资料的解析结构和来源位置符合原文件；
2. 扫描 PDF 的公式、基础表格、代码和上下文达到当前可用标准；
3. 你认可下方已知边界留待后续优化，而不阻塞进入第三周。

如果三项都认可，回复“计划日 5 和第二周整体验收通过”即可。之后会按约定提交当天 Git，
将第二周状态改为“已完成”，再进入第三周。

## 已知边界

- OCR 第一版保证普通中英文、代码、基础公式/表格和阅读顺序，不承诺复杂公式语义、复杂
  多栏排版、跨页合并单元格或图示语义；
- PDF OCR 能保守识别 `2. 标题` 一类独立编号标题，但复杂样式、多栏标题或无明显编号的
  标题仍弱于带显式样式的 Markdown/DOCX/PPTX；
- 当前只写 bge-m3 Dense Vector，Sparse/ColBERT、检索与重排属于第三周；
- Qdrant 使用 Local Mode，索引和删除在单 FastAPI 进程内串行；
- 后台任务不是分布式队列，但应用重启会恢复 pending/processing；
- TXT 会保守识别独立 Book、罗马数字、短标题和编号标题；没有明显标题形态时仍只按段落
  和句子边界分块，不会强行推断章节。

## 验收文件

- 日 5 操作说明：`docs/deliverables/week-02-day-05.md`；
- 本地结构报告：`data/acceptance/week-02/structure-review.md`；
- 完整审计结果：`data/acceptance/week-02/audit.json`；
- PDF 原页摘录：`output/pdf/第二周验收-数据结构教材代表页.pdf`；
- 每日历史说明：`docs/deliverables/week-02-day-01.md` 至
  `docs/deliverables/week-02-day-04.md`。

本周验收数据与模型均在 Git 忽略目录，源码和说明中不包含课程资料正文、模型权重或密钥。
