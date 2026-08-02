# 第 2 周工程日志：知识库入库

## 周信息

| 项目 | 内容 |
|---|---|
| 计划周 | 第 2 周 |
| 周主题 | 知识库入库 |
| 当前状态 | 进行中 |
| 已完成计划日 | 计划日 1～3（计划日 3 包含合并任务 A、B） |
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

---

## 计划日 3 合并任务 A：PDF 原生解析与扫描页 OCR

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际完成日期 | 2026-08-01 |
| 状态 | 已验收并提交 |
| OCR 依赖 | PaddleOCR 3.7.0、PaddlePaddle 3.3.1 |
| PDF 依赖 | pypdf 6.x、pypdfium2 5.x |
| 模型 | PP-OCRv6 small 检测与识别模型 |

### 当日目标

- PDF 逐页优先读取原生文本层；
- 仅对没有有效文本的页面执行本地 OCR 回退；
- 所有正文和 Chunk 保留精确一基页码；
- 对普通中文段落、基础表格、连续公式和代码执行基础版面重建；
- 覆盖原生文本、纯扫描、混合、空白、损坏和加密 PDF；
- 提供单页抽查入口，避免验收一页时先 OCR 完整本教材。

明确不实施：

- 复杂数学公式的结构化还原；
- 复杂表格、图示、流程图或图片语义理解；
- 通用复杂页面版面理解和任意多栏语义重排；
- 上传后后台索引、状态推进、Embedding 或 Qdrant 入库。

### 完成内容

#### 逐页解析策略

- 使用 pypdf 打开和校验 PDF，并拒绝损坏、畸形和加密文件；
- 原生文本只有达到 20 个有效字母/数字且可读字符比例不低于 35% 才被采用；
- 有效原生页不渲染、不加载 OCR 模型；
- 无有效文本页以 220 DPI 通过 PDFium 渲染，只对该页运行 OCR；
- OCR 识别行低于 0.35 置信度时丢弃并产生页级警告；
- 页面没有任何可用原生/OCR 文本时产生 `EMPTY_PDF_PAGE`，整份文档无正文时返回
  `EmptyDocumentError`；
- `--page-number` 支持只解析一页，并以 `PARTIAL_PDF_PARSE` 明示这不是完整解析结果。

#### OCR 版面与语义重建

- 根据首行缩进、行距和区域边界，将逐行 OCR 结果重建为语义段落；
- 过滤页面顶部和底部的页眉页脚区域；
- 将右侧浮动基础表格与左侧正文分离，不再按全页横向坐标交错；
- 将整页基础表格按行列重建为受保护表格块；
- 将连续基础公式与常见 C++ 代码分别组织为受保护块；
- OCR 段落不再生成从句中开始的部分重叠，避免 Chunk 首部语义中断。

#### 来源与分块衔接

- `SourceLocation` 新增 `native_pdf` / `ocr` 解析方式和 OCR 置信度；
- PDF 每个块保留精确 `page_number`；
- Chunk 元数据新增涉及的解析方式集合与最低 OCR 置信度；
- 抽查输出新增解析方式计数、最低和平均 OCR 置信度；
- 真实抽查的 PDF Chunk 均只引用对应页面，来源覆盖无缺口。

#### 模型与离线约束

- 用户在下载前获知并批准模型名称、官方来源、大小和最终绝对路径；
- `PP-OCRv6_small_det` 位于
  `D:\Agentic\data\models\paddleocr\PP-OCRv6_small_det`；
- `PP-OCRv6_small_rec` 位于
  `D:\Agentic\data\models\paddleocr\PP-OCRv6_small_rec`；
- 有效模型文件合计 31,481,281 字节（约 30.02 MiB）；
- 下载归档 SHA-256 分别为检测模型
  `BFB7C1E59F0FAA6B540EBDCA93AEA3F4B1F2477805B389FBEE117820D68FE9F5`、识别模型
  `DA460F968CE9F88325AC3A34FA302077D6E9B0DCEFB16BA3137CD7796F879D06`；
- 未下载文档方向、图像矫正或文字行方向模型；
- 运行时显式使用本地模型目录并关闭模型源联网检查；
- PaddleX 缓存根目录固定在已批准的 PaddleOCR 模型目录，不使用用户主目录；
- Windows CPU 上关闭有兼容问题的 oneDNN 可选加速路径，普通 Paddle CPU 推理正常。

### 真实样本验证

现有 66.9 MB 教材共 355 页：第 1～354 页主要为扫描图，第 355 页带原生英文/JSON
文本层，可同时充当纯扫描页和混合 PDF 验收样本。

| 抽查页 | 路径 | 结果 |
|---|---|---|
| 10 | OCR | 39 行，最低置信度 0.6766，3 个 Chunk，页码均为 10 |
| 50 | OCR | 10 个语义段落、3 个 Chunk；中文正文连续，无句中重叠 |
| 60 | OCR | C++ 类、字段、函数签名和中英文注释基本完整 |
| 100 | OCR | 2 个正文、2 个表格、1 个代码块；左右区域不交错，代码续行不分离 |
| 355 | 原生文本 | 未触发 OCR，直接得到英文说明与 JSON 元数据 |

PDF 技能要求的视觉核验已执行：渲染查看第 10、50、60、100、200 和 355 页，确认
页面图像清晰、页码对应正确，OCR 抽查文本与页面内容一致。临时 PNG 在核验后已删除。

### 验证结果

| 检查 | 结果 |
|---|---|
| PDF/OCR 布局/分块专项测试 | 14 项全部通过 |
| 后端全量测试 | 69 项全部通过 |
| Ruff | 通过 |
| Mypy strict | 通过，46 个源文件无问题 |
| uv lock | 依赖解析一致，112 个包 |
| 模型有效文件 | 31,481,281 字节 |
| 当前后端虚拟环境总文件量 | 865,887,262 字节（约 825.77 MiB） |
| 模型归档 | SHA-256 校验后删除，不重复占用磁盘 |

### 主要文件

| 文件 | 用途 |
|---|---|
| `backend/app/ingestion/parsers/pdf.py` | PDF 原生提取、有效性判断、PDFium 渲染和 OCR 回退 |
| `backend/app/ingestion/parsers/_ocr_layout.py` | OCR 段落、表格、公式与代码的基础版面重建 |
| `backend/app/ingestion/models.py` | 解析方式与 OCR 置信度来源契约 |
| `backend/app/ingestion/chunking/models.py` | Chunk 解析方式和最低 OCR 置信度元数据 |
| `backend/app/ingestion/inspect.py` | PDF 单页抽查与 OCR 统计 |
| `backend/tests/test_ingestion_pdf_parser.py` | PDF/OCR 确定性测试 |
| `docs/deliverables/week-02-day-03.md` | 用户抽查说明与通过标准 |

### 下一计划日入口

本合并任务只完成解析层，不把 355 页 OCR 放进同步 HTTP 请求。任务 A 已由用户验收，
对应提交为 `8c2bd25 feat: add PDF OCR layout reconstruction`。同日继续执行原定计划日 3
的 Embedding 与 Qdrant（任务 B）。

---

## 计划日 3 合并任务 B：Embedding 与 Qdrant

### 基本信息

| 项目 | 内容 |
|---|---|
| 实际完成日期 | 2026-08-02 |
| 状态 | 已验收并提交 |
| Embedding | BAAI/bge-m3，1024 维 Dense Embedding |
| 推理依赖 | PyTorch 2.11.0+cu128、Sentence Transformers 5.6.1 |
| 向量库 | Qdrant Client 1.18.0 Local Mode |
| Collection | `knowledge_chunks_v1`，Cosine，1024 维 |

### 模型审批与安装

- 下载前向用户报告模型、固定版本、官方来源、文件清单、大小、SHA-256、最终路径、
  PyTorch CUDA 运行时和预计总占用；
- 用户明确批准后才安装依赖并下载模型；
- 固定版本为 `84790c1a606f60d06c6932e4ecdd174b466d84ac`；
- 最终路径为 `D:\Agentic\data\models\embedding\bge-m3`；
- 只下载 SafeTensors、tokenizer、Pooling 配置及 Sparse/ColBERT 小型头，不下载重复的
  `pytorch_model.bin` 或 ONNX 权重；
- 12 个有效文件合计 2,295,339,486 字节（约 2.138 GiB）；
- `model.safetensors` SHA-256 为
  `993B2248881724788DCAB8C644A91DFD63584B6E5604FF2037CB5541E1E38E7E`；
- 模型加载固定 `local_files_only=True`，并关闭远程代码信任，运行期不联网；
- 模型与 OCR 合计约 2.167 GiB；GPU 依赖安装后 `.venv` 约 5.184 GiB。

### Embedding 与设备回退

- 批量输入非空 Chunk 文本，输出 1024 维 `float32` 归一化 Dense 向量；
- `auto` 优先选择 CUDA，显式 `cpu` 可强制 CPU；
- CUDA 不可用时直接选择 CPU；CUDA 加载或推理出现 `RuntimeError` 时释放 GPU 模型并
  在 CPU 上重新执行同一批次；
- RTX 4070 Laptop 实测 3 条中英文文本成功使用 CUDA；
- 强制 CPU 实测同一模型成功输出 1024 维向量；
- GPU 实测中英同义句余弦相似度约 0.739，向量范数约为 1。

### Qdrant Collection 与课程隔离

- 正式路径 `D:\Agentic\data\qdrant` 已建立 `knowledge_chunks_v1` 空 Collection；
- Collection 为单一 Dense Vector、1024 维、Cosine，元数据记录模型和隔离键；
- Point ID 由 `course_id + document_id + chunk_index` 确定性生成；
- Payload 保存课程、文档、Chunk、文件、章节、源块、页码、幻灯片、解析方式和 OCR
  置信度；
- 文档重新索引时，仅删除同课程同文档旧点，再按批次写入新点；
- 写入前验证 Chunk 自带的课程/文档来源与目标完全一致，验证失败时不删除旧点；
- 搜索入口没有无课程版本，内部始终添加 `course_id` 必选 Filter；
- 文档删除同时使用 `course_id` 和 `document_id` Filter，不会影响其他课程的同名文档。

### 真实验证

- 真实 Markdown 解析为 4 个 Chunk，经 GPU bge-m3 批量向量化并写入临时 Qdrant；
- 同一 4-Chunk 内容分别写入 `validation-course-a` 和 `validation-course-b`；
- 临时库总计 8 点，两个课程各 4 点；课程 B 查询只返回课程 B Payload；
- 验证完成后临时 Qdrant 已删除；正式 Collection 保持 0 点，未混入验收数据；
- 整个过程不读取 DeepSeek Key、不调用 DeepSeek API。

### 验证结果

| 检查 | 结果 |
|---|---|
| Embedding/Qdrant 专项测试 | 9 项全部通过 |
| 后端全量测试 | 78 项全部通过 |
| Ruff | 通过 |
| Mypy strict | 通过，应用与测试共 67 个源文件无问题 |
| uv lock | 依赖解析一致，151 个包 |
| GPU | PyTorch 2.11.0+cu128 识别 RTX 4070，真实推理通过 |
| CPU | 强制 CPU 真实推理通过 |
| 模型与 OCR 总量 | 2,326,825,620 字节（约 2.167 GiB） |
| 后端虚拟环境 | 5,566,692,318 字节（约 5.184 GiB） |

### 主要文件

| 文件 | 用途 |
|---|---|
| `backend/app/knowledge/embedding.py` | 本地 bge-m3 批量向量化与 CUDA/CPU 回退 |
| `backend/app/knowledge/vector_store.py` | Collection、批量写入和课程隔离 |
| `backend/app/knowledge/indexing.py` | Chunk → Embedding → Qdrant 编排与课程内搜索 |
| `backend/app/knowledge/inspect.py` | 真实文档入库和检索抽查命令 |
| `backend/tests/test_knowledge_embedding.py` | GPU 选择和 CPU 回退确定性测试 |
| `backend/tests/test_knowledge_vector_store.py` | 课程隔离、替换和维度验证 |
| `backend/tests/test_knowledge_indexing.py` | 批量索引编排测试 |

### 当前边界与下一入口

- 本任务完成可调用的解析、分块、Embedding 和 Qdrant 层，但未把它接入上传后的后台
  状态机；后台任务、失败重试及 SQLite 状态推进属于下一计划日；
- 当前仅写 Dense Vector；bge-m3 的 Sparse/ColBERT 混合检索留给后续检索优化；
- Qdrant 当前使用单机 Local Mode，后续可在不改变课程 Payload 规则的情况下切换服务端。
