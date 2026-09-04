# 第六周计划日 4：NLI 幻觉定位审批前置

## 当前状态

- 前置审查日期：2026-09-04
- 实验 ID：`w6-d4-sentence-nli-spans`
- 审批结果：A、B、C 已于 2026-09-04 获批
- 当前注册状态：`ready`
- 当前模型状态：固定 revision/hash 已下载并静态核验，尚未加载
- 实施状态：用户已完成下载后复审并批准执行；validation 已完成
- 已完成：模型下载校验、RAGTruth train-only 派生、注册表单变量修订
- 未实施：NLI 权重加载、模型推理、validation/test 运行

本文件保留审批依据；前置结果见[下载与数据派生核验报告](week-06-day-04-readiness.md)，正式结果见
[句级 NLI 幻觉定位报告](week-06-day-04.md)。

## 推荐结论

推荐使用
[`cross-encoder/nli-deberta-v3-base`](https://huggingface.co/cross-encoder/nli-deberta-v3-base)，
理由是它直接输出 contradiction/entailment/neutral 三类，模型卡报告 SNLI test accuracy 92.38、
MNLI mismatched accuracy 90.04；相对 small 版本质量更高，相对 RoBERTa-large-MNLI 参数和权重
约减半，适合当前 8 GiB RTX 4070 Laptop GPU。

官方 Sentence Transformers 的
[NLI 模型表](https://github.com/huggingface/sentence-transformers/blob/main/docs/cross_encoder/pretrained_models.md#nli)
同样列出该模型的 MNLI mismatched 90.04，并给出 contradiction、entailment、neutral 的句对预测
用法。

## 候选比较

| 模型 | 声明许可 | 参数量 | Safetensors | 官方 NLI 参考 | 结论 |
|---|---|---:|---:|---:|---|
| `cross-encoder/nli-deberta-v3-base` | Apache-2.0 | 184,424,451 | 737,726,552 B | MNLI-mm 90.04 | 推荐 |
| `cross-encoder/nli-deberta-v3-small` | Apache-2.0 | 141,897,219 | 567,605,820 B | MNLI-mm 87.55 | OOM/吞吐备选 |
| `FacebookAI/roberta-large-mnli` | MIT | 356,412,419 | 1,425,698,116 B | 355M 经典基线 | 不推荐，资源更重 |

RoBERTa-large 的 355M 参数规模由
[Fairseq 官方 RoBERTa 文档](https://github.com/facebookresearch/fairseq/blob/main/examples/roberta/README.md#pre-trained-models)
给出；模型仓库的
[官方模型卡](https://huggingface.co/FacebookAI/roberta-large-mnli)声明其为英文 MNLI 模型和 MIT
许可。

## 推荐模型固定身份

| 项目 | 固定值 |
|---|---|
| Hugging Face repo | `cross-encoder/nli-deberta-v3-base` |
| Revision | `6c749ce3425cd33b46d187e45b92bbf96ee12ec7` |
| Repo 状态 | public、ungated、not disabled |
| Repo 最后修改 | 2025-04-11T09:56:48Z |
| 声明许可 | Apache-2.0 |
| Base model | `microsoft/deberta-v3-base`，其模型卡声明 MIT |
| 训练数据标签 | SNLI、MultiNLI |
| 架构 | `DebertaV2ForSequenceClassification`，12 层、hidden 768、12 heads |
| 最大位置长度 | 512 tokens |
| 标签顺序 | 0 contradiction、1 entailment、2 neutral |
| 权重格式 | Safetensors only；不下载 pickle `.bin` 或 ONNX |
| `model.safetensors` | 737,726,552 bytes |
| 权重 SHA-256 | `d8148c6d49e0a7925134294c56326c71fe0ab1dc390e37355e00c7efbb488afa` |
| `spm.model` SHA-256 | `c679fbf93643d19aab7ee10c0b99e460bdbc02fedf34b92b05af343b4af586fd` |

固定 revision 的
[`model.safetensors`](https://huggingface.co/cross-encoder/nli-deberta-v3-base/blob/6c749ce3425cd33b46d187e45b92bbf96ee12ec7/model.safetensors)
页面可独立核对 737,726,552 bytes 与权重 SHA-256。Base model 的
[Microsoft 模型卡](https://huggingface.co/microsoft/deberta-v3-base)声明 MIT 许可。

### 许可边界

Hugging Face repo metadata/model card 声明 Apache-2.0，但仓库文件清单中没有独立 `LICENSE`
文件。因此若获批：

1. `THIRD_PARTY_NOTICES.md` 记录模型 repo、固定 revision、声明许可、base model 与训练数据来源；
2. 权重只保存在 Git 忽略的本地模型目录，不随 Agentic 仓库或 Release 分发；
3. 不把该模型描述为 Agentic 原创或重新许可；
4. 如未来需要重新分发权重，先重新进行法律与上游许可复核。

这不是法律意见；当前审批只覆盖本地研究评测。

## 下载范围与资源预算

若获批，只允许从固定 revision 下载以下 8 个文件：

- `README.md`
- `added_tokens.json`
- `config.json`
- `model.safetensors`
- `special_tokens_map.json`
- `spm.model`
- `tokenizer.json`
- `tokenizer_config.json`

合计 748,853,373 bytes，约 714.16 MiB。不下载 `pytorch_model.bin`、任何 ONNX、量化变体或
其他模型。下载后先核对 revision、文件 allowlist、权重 SHA-256 和 SentencePiece SHA-256；
任何不一致立即停止，不运行模型。

当前 D 盘可用约 405.95 GiB，空间足够。GPU 为 NVIDIA RTX 4070 Laptop、8,188 MiB。按
184.4M 参数估算，FP16 权重约 352 MiB；推理初始 batch 8、max length 512，并设定：

- GPU peak allocated 预算上限 4 GiB；
- 如果 batch 8 OOM 或越过预算，只允许降到 batch 4，不改变模型、数据或分数；
- batch 4 仍失败则停止并回到审批，不自动切换模型；
- 不训练或微调 NLI 权重，不产生新 Adapter。

显存数字是下载前保守估算，最终实测 peak 会在 validation 报告中记录。

## RAGTruth 数据边界发现

RAGTruth 官方 revision 为 `c103204b9ce28d6bbad859304bf30de72b8ed8fe`。本地官方发布把
train/test response 混在同一个 `response.jsonl`，所有 source 混在同一个
`source_info.jsonl`。现有适配器虽然先检查 `split`，再访问 response、labels 与 gold，但在文件
系统层面仍会打开并顺序扫描整个混合 JSONL。因此不能声称直接复用原始文件是“test 文件零读取”。

若获批，计划先执行一次受控派生：

1. 流式扫描 frozen 原始 JSONL；test response 只用于识别 `split` 并立即丢弃，不进入领域对象、
   特征、缓存、统计或日志；
2. 只复制 train response 与其引用的 source，生成本地 `derived/train-only/`；
3. 记录父文件 revision/hash、派生文件 hash、train row/source 计数与转换代码 hash；
4. 验证派生 response 全部为 train、引用完整、无重复 ID、标签边界有效；
5. 后续 fit/calibration/validation 与 NLI runner 只允许打开派生文件；
6. 派生数据与特征继续由 Git 忽略，不保存原文或逐条预测到受版本控制目录。

该预处理不可避免地顺序读取混合文件的字节，是唯一需要明确批准的数据边界例外；它不会查看、
评估或输出 test 标签与指标。若不批准这项例外，则计划日 4 无法在当前官方文件布局上继续。

## 预登记实验协议

### 数据划分

只使用官方 train：

- 按 `source_id + task_type` 分组，任何同源回答不得跨 split；
- seed 42 固定划分 fit、calibration、validation；
- 建议比例 60% / 20% / 20%，并按 task_type 分层；
- fit 只拟合 Logistic Regression；
- calibration 只选 response/span 阈值；
- validation 只运行一次最终候选比较；
- 官方 test 在计划日 4 始终禁止，计划日 5 是否运行另行审批。

### 输入和聚合

- premise：现有 1,200 字符、120 字符 overlap 的 context chunk；
- hypothesis：保持原 offset 的 response sentence；
- tokenizer：pair encoding、max length 512、`truncation="only_first"`，优先保留 response
  sentence；
- 对每个 sentence × source chunk 计算三分类概率；
- sentence 级保留 `max_entailment`、`max_contradiction`、`max_neutral` 三个数值特征；
- 不保存 premise/hypothesis 文本或逐 pair logits 到 tracked artifact。

### 单变量修订建议

当前 draft 把主变量写成：

```text
baseline: lexical-coverage
candidate: sentence-level-nli
```

这会同时改变特征与评分结构，归因不够严格。获批后建议在真正运行前修改为：

```text
baseline: lexical+dense logistic
candidate: lexical+dense logistic + frozen sentence-level NLI features
```

两者使用相同 Logistic Regression、class weight、fit split、calibration split、阈值搜索和评估
函数，唯一变量是三个冻结 NLI 特征。历史 `lexical_coverage` 继续作为第二参考方法报告，但不承担
单变量因果对照。

## 晋级门与输出

主要指标：RAGTruth derived validation micro span char F1。

候选必须同时满足：

1. span char F1 高于同协议 `lexical+dense logistic`；
2. response AUPRC 不回退；
3. response recall 不回退；
4. mean latency 相对 baseline 增幅不超过 250 ms/response；
5. source-cluster bootstrap 95% CI 不支持稳定收益时，只能 provisional，不能冻结；
6. domain/task、class、length、evidence count、error type 五类切片全部输出脱敏聚合。

另行报告历史 `lexical_coverage`，但不读取 Week 5 test prediction 或以历史 test 数值调参。

本地产物只包含 aggregate summary、slice summary、缓存和哈希；不生成逐条 prediction。实现完成
后运行定向测试、后端全量测试、Ruff、mypy strict、缓存命中复跑和隐私字段审计。

## 本次需要批准的三项

### A. 模型下载

批准从固定 revision 下载推荐模型的 8 个 allowlist 文件，共约 714.16 MiB，只用于本地研究
评测并按上述哈希校验。

### B. 一次性 train-only 派生

批准对 RAGTruth 两个 frozen 混合 JSONL 做一次受控流式扫描，生成并冻结 train-only 副本；test
行不进入模型对象、特征、统计、日志或输出。后续优化只访问派生副本。

### C. 注册表单变量修订

批准把主对照改为相同 Logistic Regression 下的 `lexical+dense` 与
`lexical+dense+sentence-NLI`，并在 A/B 完成核验后将实验从 draft 改为 ready。

A、B、C 已获得明确批准并完成前置落地；用户随后完成下载后复审并批准 validation 实施。
