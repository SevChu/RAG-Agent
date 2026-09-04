# 第六周计划日 4：下载与数据派生核验报告

## 结论

用户于 2026-09-04 批准审批材料中的 A、B、C，并要求下载完成后先停止、等待再次审核。
三项前置工作现已完成，`w6-d4-sentence-nli-spans` 已具备精确、可复验的 `ready` 身份；
本轮没有加载 NLI 权重、没有执行 tokenizer/模型前向计算、没有运行 validation 或 test。

后续状态：用户已完成下载后复审并批准执行；实施结果见
[句级 NLI 幻觉定位报告](week-06-day-04.md)。本文件继续保留为前置核验记录。

## A. 固定模型下载核验

- 本地目录：`data/models/nli/nli-deberta-v3-base/`（Git 忽略）
- 上游：`cross-encoder/nli-deberta-v3-base`
- 固定 revision：`6c749ce3425cd33b46d187e45b92bbf96ee12ec7`
- 下载范围：审批 allowlist 中的 8 个文件，无缺失、无额外顶层文件
- 合计：748,853,373 bytes
- 下载方式：普通 HTTPS；未安装可选 `hf_xet`
- 未下载：`pytorch_model.bin`、ONNX、量化变体

| 文件 | Bytes | SHA-256 |
|---|---:|---|
| `README.md` | 2,856 | `b6a6dd82d5fee7036e3b815ce1d28458df294d8525fc234fb7e7277b6b79d878` |
| `added_tokens.json` | 26 | `a4b6bfe668f2b3cf6f0cd535e98a0663d2d0d4a4a15f13075ad3597d33985a23` |
| `config.json` | 1,052 | `897e756eb59d3183adb505952e7910e7cbc7750a43f3b3747a96b688d2b02a47` |
| `model.safetensors` | 737,726,552 | `d8148c6d49e0a7925134294c56326c71fe0ab1dc390e37355e00c7efbb488afa` |
| `special_tokens_map.json` | 301 | `ed7c099c988dbb414b18a6980d20cb57b91b7cd119f6f6941eb364b0e892e712` |
| `spm.model` | 2,464,616 | `c679fbf93643d19aab7ee10c0b99e460bdbc02fedf34b92b05af343b4af586fd` |
| `tokenizer.json` | 8,656,624 | `5124ef2ead1a10a717703bc436de7f353da76d6340e4587719b42b1693707964` |
| `tokenizer_config.json` | 1,346 | `f3eecd07c370ef0bf7dd3780d3cd68cf9c8b00c267e21a208ddcd8f82bfec1a6` |

下载缓存的 8 项 revision 元数据均指向上述固定 commit。该核验只读取文件清单、长度、下载
元数据与字节哈希，没有反序列化 safetensors 张量。

## B. RAGTruth train-only 派生核验

新增 `backend/scripts/prepare_ragtruth_train_only.py`。工具先核对父文件冻结哈希，再从混合 JSONL
中流式识别 split；排除行在 JSON 解析前丢弃，不进入领域对象、特征、统计、日志或输出。只复制
train response 及其引用 source，最后使用现有适配器仅对派生目录进行完整结构、引用、唯一性和
标签边界验证。

- 派生目录：`backend/datasets/benchmarks/ragtruth/derived/train-only/`（Git 忽略）
- 派生 ID：`ragtruth-stream-filter-train-v1`
- 父 revision：`c103204b9ce28d6bbad859304bf30de72b8ed8fe`
- 派生 manifest SHA-256：`e70a891458a68861554da76dc9087b67356abf19b5e22b4ab5842545ff058cbc`
- `response.jsonl`：18,454,939 bytes；SHA-256
  `2438f264d769b823904f6728f326a9521eebe07fce4ff6fa52e6406810287870`
- `source_info.jsonl`：12,812,339 bytes；SHA-256
  `cc958136772940c289896a8aee63b0d7bb4b8557e980fe3bf75992990c06d000`
- train 聚合计数：2,515 sources、15,090 responses、6,721 hallucinated responses、12,756 spans

派生清单只含聚合计数、hash、bytes、父 revision 和转换代码 hash，不含样本 ID、原文、标签内容
或逐条预测。官方 test 仍封存，且不在派生目录中。

边界测试使用“能识别为排除项、但不是合法 JSON”的 fixture，证明排除项不会进入 JSON 解码；
同时覆盖父文件哈希变化与拒绝覆盖已有派生目录。

## C. Experiment Registry 核验

`w6-d4-sentence-nli-spans` 已从 `draft` 改为 `ready`，并冻结：

- dataset：`ragtruth-train-only`、父 revision + 派生算法、派生 manifest SHA-256；
- model：`cross-encoder/nli-deberta-v3-base`、固定 revision、权重 SHA-256；
- 单变量对照：`lexical-dense-logistic` 与
  `lexical-dense-logistic-plus-sentence-nli`；
- test access：仍为 `forbidden`。

注册表注释明确：`ready` 只表示下载和派生前置条件已冻结；模型加载与推理仍等待用户本次复审。

## 本轮验证

- 派生工具 Ruff：通过；
- 派生工具 strict mypy：通过；
- 派生边界与注册表定向测试：8 项通过；
- 模型 allowlist、revision 元数据、字节数与 SHA-256：通过；
- RAGTruth 父哈希、派生哈希、聚合计数与适配器结构验证：通过。

## 下一审批点

下一步只有在用户再次明确批准后才会：

1. 首次加载 tokenizer 与 NLI safetensors；
2. 做小批次 GPU 显存/标签顺序 smoke check；
3. 实现并运行只访问 train-only 派生数据的 fit/calibration/validation 候选；
4. 继续禁止官方 test，test 是否运行留到计划日 5 单独审批。

本报告当时不构成自动授权；用户随后已明确批准执行，官方 test 仍需 Day 5 单独审批。
