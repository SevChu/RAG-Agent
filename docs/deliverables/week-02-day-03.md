# 第 2 周计划日 3 合并任务 A 验收说明：PDF 原生解析与 OCR 回退

## 交付结论

本说明对应计划日 3 当日合并的 PDF/OCR 补充任务；原定计划日 3 的 Embedding 与
Qdrant 是同日任务 B。任务 A 已完成 PDF 原生文本优先、逐页 OCR 回退、基础版面
重建和精确页码保留。解析器不会把
“含有任意几个字符”误判为有效文本层；页面只有达到最低有效字符数和可读字符比例
后才走原生解析，否则以 220 DPI 渲染并调用本地 PaddleOCR。

OCR 检测行不会再直接等同于段落：解析器依据首行缩进、行距和版面区域重建中文段落，
将基础表格、连续公式和代码组织为受保护块；OCR 段落参与分块时不使用可能从句中开始
的截断式重叠。

本次新增并固定使用：

- `PP-OCRv6_small_det`：`D:\Agentic\data\models\paddleocr\PP-OCRv6_small_det`；
- `PP-OCRv6_small_rec`：`D:\Agentic\data\models\paddleocr\PP-OCRv6_small_rec`；
- 两个模型的有效文件合计 31,481,281 字节（约 30.02 MiB）；
- 下载归档已做 SHA-256 校验并在解压后删除，不重复占用磁盘；
- 文档方向、图像矫正和文字行方向三个可选模型未下载；
- PaddleX 的缓存根目录也被限制在 `D:\Agentic\data\models\paddleocr`，不会写入
  用户主目录。

## 建议抽查

以下命令只读取样本和本地模型，不修改 PDF、数据库或上传状态。首次启动需要加载
模型，耗时会明显长于后续单页识别。

### 1. 普通中文扫描页

```powershell
cd D:\Agentic\backend

uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\01-课程教材.pdf" `
  --page-number 50 `
  --max-blocks 20 `
  --chunks `
  --max-chunks 3
```

应看到：

- `parser_name` 为 `pdf-native-with-paddleocr-fallback-v1`；
- `extraction_method_counts.ocr` 大于 0，且没有 `native_pdf`；
- 所有块的 `page_number` 都是 50；
- 中文正文、`rectangle`、`square`、`triangle`、`polygon` 和 `draw` 等中英文内容
  基本连续可读；
- 该页通常重建为约 10 个语义段落，而不是几十个逐行碎片；默认 600/80 参数下约为
  3 个 Chunk，Chunk 应从段落边界开始，不应出现句中截断形成的重叠片段；
- Chunk 的 `page_numbers` 为 `[50]`、`extraction_methods` 为 `["ocr"]`，并带有
  `minimum_ocr_confidence`；
- 除只读抽查产生的 `PARTIAL_PDF_PARSE` 外，不应出现空页或低置信度警告。

### 2. C++ 代码页

```powershell
uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\01-课程教材.pdf" `
  --page-number 60 `
  --max-blocks 70
```

重点检查：

- `class SeqList`、`protected:`、`public:` 能识别；
- `int length;`、`bool IsEmpty() const;`、`void Clear();` 等函数和字段基本完整；
- 中英文注释仍按页面从上到下输出；
- 少量空格、下划线或标点误差可以接受，整段代码不可完全缺失或乱序。

### 3. 基础公式和表格页

```powershell
uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\01-课程教材.pdf" `
  --page-number 100 `
  --max-blocks 100
```

应能找到 `32 - 26`、`6 * 5`、`28 / 4`、`30 + 7`、`x^y^z`、
`bool IsOperator(char ch)` 等内容。当前样本页应重建为 2 个连续正文段落、2 个完整表格
块和 1 个连续代码块；右侧表 4-1 不应切断左侧正文，表 4-2 的多行步骤不应被拆散，
`if (...)` 及其续行应保留在同一代码块。个别数字、引号或操作符的 OCR 误识别可以
接受，但不能再出现正文、表格和代码按全页坐标交错的旧行为。

### 4. 同一真实 PDF 的原生文本页

```powershell
uv run python -m app.ingestion.inspect `
  "D:\Agentic\data\test-materials\day-03\valid\数据结构\01-课程教材.pdf" `
  --page-number 355 `
  --max-blocks 5
```

应看到：

- `extraction_method_counts.native_pdf` 为 1，且没有 `ocr`；
- `page_number` 为 355；
- 能直接读取英文说明和 JSON 文本；
- 证明混合型 PDF 是逐页选择解析方式，而不是发现扫描页后整本强制 OCR。

## 验收标准

满足以下条件即可确认计划日 3 合并任务 A 通过：

1. 第 50、60、100 页均显示 `ocr`，第 355 页显示 `native_pdf`；
2. 四次抽查的来源页码准确，Chunk 不引用其他页；
3. 第 50 页中文段落语义连续，Chunk 不从 OCR 行中间制造截断式重叠；
4. 第 100 页正文、两个表格和代码分区正确，相关表格行及代码续行不被拆散；
5. 基础算式和运算符大体保留，接受少量 OCR 字符错误；
6. 复杂合并单元格、复杂多栏或复杂公式不要求完整还原，但不得把这类能力标成已经
   完整支持；
7. 不出现模型缺失、用户目录下载、PDF 损坏或运行崩溃错误。

## 自动验证覆盖

新增 9 项 PDF、4 项 OCR 布局确定性测试，并增加 1 项 OCR 分块重叠测试，覆盖：

- 原生文本优先且不触发渲染/OCR；
- 纯扫描页 OCR、低置信度行过滤和置信度保存；
- 混合 PDF 仅对无有效文本页回退；
- 页码、解析方式和 OCR 置信度进入 Chunk 元数据；
- 中文缩进段落重建和页眉页脚区域过滤；
- 右侧浮动表格、整页表格、连续公式和代码块分区；
- 运算符密集的代码续行不被误判为公式；
- OCR Chunk 不生成从句中开始的部分重叠；
- 单页抽查不会处理其他页；
- 空白、加密、损坏和越界页明确失败。

最终后端全量 69 项测试通过，Ruff 与 Mypy strict（46 个源文件）均通过。

## 已知边界

- 当前版面重建覆盖普通中文段落、右侧浮动基础表格、整页基础表格、连续公式和常见
  代码；它不是通用文档版面理解模型；
- 复杂多栏、跨页表格、合并单元格、嵌套表格仍可能需要后续专门处理；
- 复杂数学公式、图示语义和图片内容理解不在本计划日承诺范围；
- 整本 355 页扫描教材会逐页执行 CPU OCR，生产索引时应放入后续后台任务，不应阻塞
  HTTP 请求；后台状态流转不属于本计划日。
