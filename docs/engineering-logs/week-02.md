# 第 2 周工程日志：知识库入库

## 周信息

| 项目 | 内容 |
|---|---|
| 计划周 | 第 2 周 |
| 周主题 | 知识库入库 |
| 当前状态 | 进行中 |
| 已完成计划日 | 计划日 1～2 |
| 实际开始日期 | 2026-07-31 |
| 当前分支 | `main` |

同一自然日可以完成多个计划日。“计划日”表示里程碑顺序，不表示必须占用一个自然日。

## 已确认约束

- 五类资料最终均转换为同一种解析结果；
- PDF 原生文本优先，对无有效文本的页面执行 OCR 回退并保留页码；
- 知识库按课程严格隔离，同一文件允许进入不同课程；
- 同一课程继续按 SHA-256 拒绝重复内容；
- 模型统一位于用户批准的 `D:\Agentic\data\models\`；
- 模型只在对应计划日按需下载，每次下载前仍报告名称、来源、大小和子目录；
- 当前真实样本足以继续，不要求用户立即寻找补充资料。
- 每个计划日实施完成并通过用户抽查后提交 Git；有必要时将功能和文档拆分提交。

---

## 计划日 1：解析基础与文本类文档

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际完成日期 | 2026-07-31 |
| 状态 | 已完成 |
| 模型下载 | 无 |
| 新增运行依赖 | 无 |

### 当日目标

- 在接入具体复杂格式前固定统一解析契约；
- 建立可扩展的解析器路由；
- 完成无需第三方模型的 Markdown 和 TXT 结构化解析；
- 用确定性单元测试和工作区真实样本验证解析结果。

明确不实施：

- DOCX、PPTX 和 PDF 正文解析；
- OCR 依赖安装和模型下载；
- 文档分块、Embedding 和 Qdrant；
- 上传后异步索引与状态流转。

### 完成内容

#### 统一解析契约

- `ParsedDocument` 保存文件名、文件类型、解析器版本、结构块和警告；
- `ParsedBlock` 保存块类型、正文、章节路径、代码语言和来源位置；
- 块类型覆盖标题、段落、列表、代码和表格；
- `SourceLocation` 当前保存原始行号，并预留 PDF 页码、PPTX 幻灯片编号；
- 块索引强制从 0 连续递增，供后续分块和引用稳定使用；
- 解析结果不可变，避免后续管线意外改写来源元数据。

#### 解析器路由

- 使用解析器协议隔离具体文件格式；
- 注册表按不区分大小写的文件类型选择解析器；
- 重复注册同一类型会失败；
- 当前默认注册 `md` 和 `txt`，后续计划日按相同接口增加其他类型；
- 未注册类型返回明确的 `UnsupportedParserError`，不会伪装成已完成解析。

#### TXT

- 支持 UTF-8 和 UTF-8 BOM；
- 统一 CRLF、CR 和 LF 换行；
- 按空白行形成段落，保留段内换行、顺序及起止行号；
- 拒绝空白正文、非法 UTF-8 和空字节。

#### Markdown

- 识别 ATX 标题和章节层级；
- 识别普通段落、连续列表、Markdown 表格和 fenced code block；
- 代码块保存语言标识；
- 每个结构块保存章节路径和原始起止行号；
- 未闭合代码围栏保留已读取代码，并生成结构化警告；
- 标题中的有效 `#` 字符（例如 `C#`）不会被误删。

#### 人工检查入口

新增只读命令：

```powershell
cd D:\Agentic\backend
uv run python -m app.ingestion.inspect "<文件绝对路径>" --max-blocks 20
```

输出包含摘要、警告和限定数量的结构块。该命令不修改源文件、数据库或上传状态。

### 验证结果

| 检查 | 结果 |
|---|---|
| 新增解析测试 | 11 项全部通过 |
| 后端全量测试 | 35 项全部通过 |
| Ruff | 通过 |
| Mypy strict | 通过 |
| 真实 Markdown | 8 个结构块、264 个正文字符、0 个警告 |
| 真实 TXT | 3427 个段落块、772819 个正文字符、0 个警告 |
| 模型目录或模型下载 | 未创建、未下载 |

测试环境的系统默认临时目录权限不可用，因此 pytest 临时文件被显式限制在
`data/test-runtime/`。这不影响功能，且该目录位于 Git 忽略的数据区。

### 主要文件

| 文件 | 用途 |
|---|---|
| `backend/app/ingestion/models.py` | 统一解析结果与来源元数据 |
| `backend/app/ingestion/errors.py` | 解析领域异常 |
| `backend/app/ingestion/registry.py` | 解析器注册和路由 |
| `backend/app/ingestion/parsers/text.py` | TXT 与共享 UTF-8 读取 |
| `backend/app/ingestion/parsers/markdown.py` | Markdown 结构化解析 |
| `backend/app/ingestion/inspect.py` | 本地只读抽查命令 |
| `backend/tests/test_ingestion_text_parsers.py` | 解析自动测试 |

### 下一计划日入口

下一计划日可在同一契约上增加 DOCX 和 PPTX 解析，重点保留标题层级、段落、
表格、图片占位信息和幻灯片编号。OCR 与扫描 PDF 仍留到对应计划日，在下载
任何 OCR 模型前先向用户报告确切信息并再次确认。

---

## 计划日 2：结构化分块

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际完成日期 | 2026-08-01 |
| 状态 | 已完成并通过用户抽查 |
| 模型下载 | 无 |
| 新增运行依赖 | 无 |
| Git 提交 | `cd9aed5 feat: add structured document ingestion and chunking` |

### 当日目标

- 实现章节感知分块，不跨章节或 PPTX 幻灯片合并正文；
- 保护列表项、表格和代码块，只在安全边界拆分；
- 为每个 Chunk 保存课程、文档、文件、章节及原始位置元数据；
- 使用默认 600/80 参数输出长度、数量、重叠、来源覆盖和异常统计；
- 提供只读抽查命令，让用户判断语义完整性和默认参数是否合适。

明确不实施：

- PDF 原生文本解析和扫描页 OCR；
- OCR 依赖、OCR 模型或其他模型下载；
- 图片语义识别、复杂公式或 SmartArt/图表语义还原；
- Embedding、Qdrant、后台索引任务和状态流转。

### 完成内容

#### 章节感知分块

- 新增独立 `DocumentChunk`、`ChunkSourceMetadata`、`ChunkingConfig`、
  `ChunkingStats` 和 `ChunkWarning` 契约；
- 默认目标长度为 600 estimated tokens，重叠目标为 80 estimated tokens；
- 每个 Chunk 重复携带 Markdown 风格的章节路径，使检索文本自身包含章节语境；
- 同一章节内按源块顺序贪心组合，不跨不同章节或不同 PPTX 主标题合并；
- 重复标题按出现位置分别维护上下文，避免同名章节或同名幻灯片串在一起；
- 超长普通段落优先在句末、换行或空白边界拆分，并按 80 目标建立重叠；
- 标题页即使没有正文也保留独立 Chunk，不丢弃其来源。

#### 受保护结构

- 列表项、表格、代码块、图片占位和内容型小标题均作为不可从中间切开的原子单元；
- 多个列表项可以装入同一 Chunk，超长列表只在列表项之间拆分；
- 单个受保护单元超过可用长度时保持完整，同时产生
  `PROTECTED_UNIT_OVER_TARGET` 异常，不静默截断；
- 章节标题上下文本身超过目标时产生 `SECTION_CONTEXT_OVER_TARGET`；
- 若任何解析源块没有被 Chunk 引用，产生 `SOURCE_COVERAGE_GAP`。

#### 完整来源元数据

每个 Chunk 保存：

- `course_id`、`document_id`、文件名、文件类型和解析器版本；
- `section_path` 和提供章节上下文的标题块索引；
- 起止块、精确源块索引和涉及的块类型；
- 原始行号范围、精确 PDF 页码集合和 PPTX 幻灯片编号集合；
- Chunk 序号、estimated token 长度和实际重叠长度。

本地抽查没有数据库记录时，课程和文档 ID 可以为空；生产入库调用必须传入实际 ID。

#### 长度、数量和异常统计

`ChunkingStats` 输出：

- 源块总数、已覆盖和未覆盖源块数；
- Chunk 总数、最小/最大/平均 estimated token 长度；
- 发生重叠的 Chunk 数和平均实际重叠长度；
- 超目标 Chunk、超长受保护单元和全部异常数量。

当前尚未下载 BGE-M3，因此长度使用无需模型的确定性估算器：中文字符单独计数，
英文和数字按固定子词宽度估算。Embedding 计划日加载真实模型 tokenizer 后，应使用
同一分块接口替换计数器并重新校准 600/80；当前输出明确标记为 estimated tokens，
不会伪装成模型的真实 token 数。

#### 只读检查入口

`app.ingestion.inspect` 新增：

- `--chunks`：执行结构化分块并输出配置、统计、警告和 Chunk；
- `--target-tokens`、`--overlap-tokens`：覆盖默认 600/80；
- `--max-chunks`、`--chunk-index`：限制或定位抽查结果；
- `--course-id`、`--document-id`：验证完整索引上下文元数据。

### 同日额外完成：Office 解析前置能力

计划日 2 实施初期曾错误地把 Office 解析当作当日正式范围。发现偏差后没有删除成果，
而是将其保留为后续五类文档统一入库的额外前置能力；计划日 2 的正式验收对象已经
纠正为本节之前的结构化分块。

#### 共享 OOXML 安全读取

- 使用 Python 标准库直接读取 Office Open XML ZIP 容器，未新增运行依赖；
- DOCX 必须包含 `[Content_Types].xml` 和 `word/document.xml`；
- PPTX 必须包含内容类型、演示文稿主体和关系文件；
- 拒绝损坏容器、缺少必要成员、畸形 XML、加密成员、越界关系目标和超过
  32 MiB 的单个 XML 成员；
- 只解压需要的 XML，不读取或解码大型媒体二进制内容。

#### DOCX

- 按正文顺序读取普通段落、内容控件内的段落和表格；
- 根据段落直接大纲级别、样式及继承样式识别 1～9 级标题；
- 根据直接编号或继承样式识别列表；
- 将表格按行列顺序转换为稳定文本块；
- 为 DrawingML 和旧式 VML 图片生成 `image` 块，并优先保留替代文本、标题或名称；
- 所有正文块继承当时的标题章节路径。

DOCX 的 OOXML 正文不提供稳定的物理页码，因此本日不伪造页码；后续引用以章节路径
和块索引为准。PDF 页码仍在 PDF/OCR 计划日处理。

#### PPTX

- 通过 `presentation.xml` 的关系顺序读取幻灯片，不依赖文件名排序；
- 解析普通文本形状、项目符号、表格和图片占位；
- 标准标题占位符、标题命名形状和无占位符封面均可识别标题；
- 每页将主标题规范化到该页结构块首位，其他块保留形状树顺序；
- 每个块记录 `source.slide_number`，并以主标题作为该页 `section_path`；
- 对没有可读文本、表格或图片的空白页产生 `EMPTY_SLIDE` 警告。

演讲者备注、图表内部数据、SmartArt 语义和图片像素内文字不在本日解析范围内。

#### Office 解析检查入口

计划日 1 的只读检查命令继续可用，并新增：

- `--kind heading|paragraph|list|code|table|image`：按结构块类型抽查；
- `--slide-number N`：只查看指定 PPTX 幻灯片；
- 摘要增加各块类型数量、匹配块数量及最大页码/幻灯片编号。

### 验证结果

| 检查 | 结果 |
|---|---|
| 新增结构化分块测试 | 11 项全部通过 |
| 新增 Office 解析测试 | 9 项全部通过 |
| 解析与分块相关测试 | 31 项全部通过 |
| 后端全量测试 | 55 项全部通过 |
| Ruff | 通过 |
| Mypy strict | 通过，54 个源文件无问题 |
| Markdown 600/80 | 8 源块全部覆盖、4 Chunks、46～70 tokens、0 异常 |
| DOCX 600/80 | 76 源块全部覆盖、14 Chunks、29～379 tokens、0 异常 |
| PPTX 600/80 | 3147 源块全部覆盖、137 Chunks、6～597 tokens、0 异常 |
| TXT 600/80 | 3427 源块全部覆盖、755 Chunks、3～600 tokens、0 异常 |
| 真实 DOCX | 76 块、1400 字符、25 个图片占位、0 个警告 |
| 真实 PPTX | 3147 块、25988 字符、覆盖 134 页、0 个警告 |
| PPTX 结构类型 | 136 标题、1842 段落、1001 列表、124 表格、44 图片 |
| 新增运行依赖 | 无 |
| 模型目录或模型下载 | 未创建、未下载 |

真实 PPTX 首次抽查发现前两页使用非标准标题形状，随后增加了无标准标题占位符时的
标题推断，并补充回归测试。修正后第 1 页“数据结构2”和第 2 页“图（Graph）”均为
`heading`，每页主标题位于该页结果首位。

### 主要文件

| 文件 | 用途 |
|---|---|
| `backend/app/ingestion/chunking/models.py` | Chunk、来源、配置、统计和异常契约 |
| `backend/app/ingestion/chunking/tokens.py` | 确定性 token 估算、语义边界拆分和重叠 |
| `backend/app/ingestion/chunking/chunker.py` | 章节感知结构化分块器 |
| `backend/app/ingestion/parsers/_ooxml.py` | 共享、有限制的 OOXML 容器读取 |
| `backend/app/ingestion/parsers/word.py` | DOCX 结构化解析 |
| `backend/app/ingestion/parsers/powerpoint.py` | PPTX 结构化解析 |
| `backend/app/ingestion/models.py` | 增加图片块和页/幻灯片级警告元数据 |
| `backend/app/ingestion/inspect.py` | 解析块与 Chunk 的只读检查、过滤和统计 |
| `backend/tests/test_ingestion_chunking.py` | 结构化分块确定性测试 |
| `backend/tests/test_ingestion_office_parsers.py` | Office 解析确定性测试 |
| `docs/deliverables/week-02-day-02.md` | 用户抽查说明与通过标准 |

### 下一计划日入口

下一计划日按原计划进入 PDF 解析，并落实“原生文本优先、无有效文本页面 OCR
回退、保留页码”的策略。如果该日需要安装 OCR 依赖或下载 OCR 模型，必须先报告
确切模型、官方来源、预计大小、`D:\Agentic\data\models\` 下的具体子目录和总存储
占用，得到用户确认后才能执行。
