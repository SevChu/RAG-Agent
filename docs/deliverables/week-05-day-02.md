# 第 5 周计划日 2：公开 Benchmark 契约与 FiQA 接入

## 当前状态

计划日 2 已完成：统一 Benchmark 数据契约、数据集注册表、BEIR Adapter、安全下载与冻结清单
脚本均已实现并通过测试。首个正式检索集已由 BEIR SciFact 调整为 BEIR FiQA-2018。

用户于 2026-08-25 明确批准下载 FiQA 到项目目录。数据已通过官方 MD5、逐文件 SHA-256、结构、
记录计数和 qrels 引用完整性校验，本地 manifest 状态为 frozen。

## 选型结论

| 数据集 | 规模与任务 | 本周定位 | 结论 |
|---|---|---|---|
| BEIR SciFact | 5,183 语料、300 测试查询；科学事实检索 | 小型冒烟测试 | 不作为首个正式基线 |
| BEIR NFCorpus | 约 3.6K 语料、323 测试查询；生物医学检索 | 密集 qrels 验证 | 没有解决数据规模问题 |
| BEIR FiQA-2018 | 57,638 语料、648 测试查询；金融问答检索 | 完整检索 benchmark | 已接入并冻结 |
| RGB refined | 给定上下文的噪声、拒答、整合和反事实鲁棒性 | 生成能力诊断 | 后续单独审批 |
| RAGBench | 约 95.4K 标注样本；TRACe 维度 | 评分器验证 | 计划日 4 单独审批 |
| RAGTruth | 17,790 回答、14,289 幻觉片段 | 幻觉检测器验证 | 计划日 4 单独审批 |

FiQA 比 SciFact 更适合作为第一个正式检索基线：语料约大 11 倍、测试查询约大 2 倍，仍可在本地
完整建立 BM25、BGE-M3、融合检索与重排基线。它属于英文金融领域，不能单独代表中文或跨领域
质量，因此后续报告必须与 RGB、RAGBench、RAGTruth 及最终自有金标集联合解读。

## 已实现内容

- registry.json 记录来源、主页、下载端点、许可、引用、语言、领域、split、官方 MD5 和审批状态；
- 生命周期固定为 candidate → approved → downloaded → verified → frozen；
- 统一契约覆盖 corpus、query、reference answer、qrels、response、普通标签和细粒度标签；
- BeirAdapter 将 BEIR JSONL/TSV 归一为统一 corpus/query/qrels 对象；
- qrels 中的 query 和 corpus 引用会做完整一致性检查；
- 下载器只接受注册表中明确为 approved 的数据集；
- 下载器限制压缩包文件数、解压总体积，并拒绝路径穿越和符号链接；
- 下载后同时校验官方 MD5、归档 SHA-256、逐文件 SHA-256、语料数和测试查询数；
- 本地数据保存于 Git 忽略目录，不能随仓库上传。

## FiQA 下载与冻结记录

- 数据集：BEIR FiQA-2018 完整 BEIR 格式；
- 用途：仅用于 Agentic 的非商业研究评测和检索 benchmark；
- 官方任务页：https://sites.google.com/view/fiqa/home
- BEIR 数据表：https://github.com/beir-cellar/beir/wiki/Datasets-available
- 下载端点：https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/fiqa.zip
- 用途限制：FiQA 官方页注明训练和测试数据仅限非商业使用；
- 压缩包大小：17,948,027 bytes；
- 本地目录：backend/datasets/benchmarks/beir-fiqa-2018/；
- 官方 MD5：17918ed23cd04fb15047f73e6c3bd9d9；
- 归档 SHA-256：32c7df99ed21252fdfb2cf3f5673502a8d245ee0c44c4a133570d92ce2b3ad02；
- split 查询数：train 5,500、dev 500、test 648；
- qrels 数：train 14,166、dev 1,238、test 1,706；
- corpus 数：57,638，其中官方空占位文档 38 条，原样保留；
- 执行命令：python scripts/manage_benchmarks.py download beir-fiqa-2018；
- 校验命令：python scripts/manage_benchmarks.py verify beir-fiqa-2018；
- Git 边界：backend/datasets/ 已整体忽略，数据和冻结清单均不会上传 GitHub。

## 自动验证

- 新增 Adapter 与审批守卫单元测试：5 项通过；
- Ruff：通过；
- Mypy strict：通过；
- 注册表校验：通过；
- 官方 MD5、归档 SHA-256 和 5 个数据文件 SHA-256：通过；
- corpus/query/qrels 记录计数和引用完整性：通过；
- 独立 frozen manifest 复验：通过；
- FiQA 状态：注册表 approved，本地数据 frozen。

## 计划日 3 入口

下一步在冻结的 FiQA 完整语料与 qrels 上建立 BM25 基线，再依次运行当前 BGE-M3 Dense、融合检索
和 BGE Reranker。所有实验使用相同 test split 与指标协议，不使用 test split 调参。
