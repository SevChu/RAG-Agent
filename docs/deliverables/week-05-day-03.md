# 第 5 周计划日 3：FiQA 经典检索基线

## 当前状态

计划日 3 已完成。Agentic 已在冻结的 BEIR FiQA-2018 完整 test split 上完成 BM25、BGE-M3
Dense、BM25 + Dense RRF 融合和 BGE Reranker 四组经典检索基线。四组结果均已保存为标准
TREC run 文件，并通过脱离模型的独立复评分与 SHA-256 校验。

本日未下载新数据或模型，未调用任何生成模型 API，也未读取资料空间、对话或本地候选测试集。
FiQA 原始数据、向量缓存、run 和本地 summary 均位于 Git 忽略目录。

## 固定实验协议

| 项目 | 固定值 |
|---|---|
| 数据集 | BEIR FiQA-2018，frozen manifest |
| 语料 | 57,638 条，包含 38 条官方空占位文档 |
| split | test，648 queries，1,706 qrels |
| 指标截断 | K = 1、3、5、10、20、100 |
| 输出深度 | Top-100 |
| 随机种子 | 42；当前算法均为确定性路径 |
| 测试集调参 | 禁止；参数均在运行前固定 |
| BM25 | Okapi BM25，k1 = 1.2，b = 0.75，英文确定性 tokenizer |
| Dense | BGE-M3，归一化 1024 维向量，全语料 exact cosine |
| 融合 | BM25 Top-100 + Dense Top-100，等权 RRF，rank constant = 60 |
| 重排 | 对 RRF Top-100 使用 BGE Reranker v2 M3，max length = 512 |
| 硬件 | Intel 28 logical CPUs，RTX 4070 Laptop 8 GiB，CUDA 12.8 |
| 软件 | Python 3.11.15，PyTorch 2.11.0+cu128 |

BGE-M3 revision 为 84790c1a606f60d06c6932e4ecdd174b466d84ac，权重 SHA-256 为
993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e。BGE Reranker
revision 为 953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e，权重 SHA-256 为
d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286。

## 正式质量结果

| 方法 | Precision@10 | Recall@10 | Recall@100 | MRR@10 | MAP@100 | nDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.0640 | 0.2891 | 0.4976 | 0.2871 | 0.1855 | 0.2309 |
| BGE-M3 Dense | 0.1127 | 0.4723 | **0.7188** | 0.5039 | 0.3538 | 0.4126 |
| BM25 + Dense RRF | 0.0983 | 0.4216 | 0.6993 | 0.4316 | 0.2959 | 0.3523 |
| RRF + BGE Reranker | **0.1170** | **0.4961** | 0.6993 | **0.5162** | **0.3682** | **0.4299** |

Dense 相对 BM25 的 nDCG@10 提升 78.74%，Recall@100 提升 44.44%。重排相对 Dense 的
nDCG@10 提升 4.18%、MRR@10 提升 2.46%、MAP@100 提升 4.07%，但 Recall@100 相对下降
2.70%。原因不是重排丢失文档，而是重排输入使用 RRF Top-100；RRF 候选本身已经把 Dense 的
Recall@100 从 0.7188 降至 0.6993。

## 延迟与资源

| 方法 | 一次性阶段 | 查询均值 | P95 | 吞吐 | 峰值工作集 | 峰值 CUDA allocated |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 索引 3.52 s | 35.58 ms | 64.21 ms | 28.10 q/s | 1.24 GiB | 0 |
| BGE-M3 Dense | corpus 编码 735.02 s | exact search 1.18 ms | 1.20 ms | 847.13 q/s | 4.11 GiB | 1.29 GiB |
| RRF | 无模型索引 | 0.32 ms | 0.12 ms | 3155.97 q/s | 0.92 GiB | 0 |
| BGE Reranker | 模型加载计入总运行 | 705.17 ms | 839.08 ms | 1.42 q/s | 4.23 GiB | 1.11 GiB |

Dense 的 1.18 ms 只表示已编码查询向量对全语料矩阵的精确搜索；648 条查询的编码与搜索总耗时
4.66 s。语料向量缓存为 236,085,376 bytes，生成耗时 735.02 s，后续实验可复用。38 条官方空
占位文档保留为零向量，不注入伪文本。

## 可复现产物

本地目录：backend/datasets/benchmarks/beir-fiqa-2018/runs/week05-day03/

| run | SHA-256 |
|---|---|
| bm25.run | fff2ebb762dc5c0904fb839e2ba1ec5120a0ab62f04fdddf5904a5b8c25e2be2 |
| dense.run | 697605821136ea0f658492cd0432e96a091dc1692f2d0dc6e26583d032389f5a |
| hybrid.run | 0e949aba7207afea3931c04681370c7ac3138c9ff04bf6eea1a7131b4b332258 |
| rerank.run | ccb5e405bdd85596145e6224defdaa013009bde07f873b4b384630d30dc87505 |

运行命令：

    cd backend
    .venv\Scripts\python.exe scripts\run_retrieval_benchmark.py

运行器会验证 frozen dataset 文件哈希；已完成方法默认恢复，只有显式指定
--force-methods METHOD 才会复跑。所有方法完成后可使用 read_trec_run 和
evaluate_retrieval 对 run 文件独立评分。

## 结论与后续优化入口

1. 当前 FiQA 检索默认基线应优先采用 BGE-M3 Dense；它提供最高 Recall@100。
2. 固定等权 RRF 不应成为默认方案。它同时降低 Dense 的召回与排序质量，说明融合候选截断、
   权重或 rank constant 需要在 dev split 上研究。
3. BGE Reranker 能显著修复 RRF 候选内的排序，但每条查询约增加 705 ms，且不能恢复候选集合
   之外的相关文档。
4. 下一轮检索算法研究应先做候选保留策略，例如 Dense 全量保留加 BM25 补充、加权 RRF 或
   score calibration；只能在 train/dev 上选择参数，test 继续只做最终验证。
5. FiQA 是英文金融领域单一检索集，不能代表中文、多领域或生成答案质量。本结论必须在后续
   公开数据和最终自有人工金标集上交叉验证。

## 验证证据

- 检索核心、Dense 精确检索和重排通用接口定向测试：11 passed；
- 后端全量测试：242 passed；
- TREC run 独立复评分：4/4 指标与 summary 完全一致；
- run SHA-256：4/4 与 summary 完全一致；
- 重排完整复跑：质量指标和 run SHA-256 与首次运行一致；
- Ruff：通过；Mypy strict：102 个源文件通过；
- 数据、缓存、run 和 summary：均受 /backend/datasets/ Git 忽略规则保护。

## 计划日 4 入口

计划日 4 需要先确定回答评分器基线的数据来源。RAGBench 与 RAGTruth 仍处于 candidate 状态，
未取得下载批准；在用户逐项批准前，只能先实现不联网的评分器契约和确定性指标，不得下载数据。
