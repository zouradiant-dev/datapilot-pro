# P7 RAG 只读归因与本地 Embedding A/B

2026-10-29。完成非付费研究，**两个候选都值得进入受限迁移验证，当前生产默认保持不变**。Qwen3 覆盖更好，BGE-M3 的稳态 CPU 开销和内存更低；尚未完成它们的生产 MCP/Worker/Report 接入，不能将本轮研究当作旧英文题修复或业务 Live 验收。

## 已知英文案例：四个环节的只读证据

仅检查已观测 tps-07 的原签名工件，并以原 BGE、原授权 Index 和真实只读 PG/MCP 重查两次查询。没有启动 Run、重评分或改写旧结果。候选模型没有编码这道旧题，也没有用它调参。

| 环节 | 观测 |
| --- | --- |
| 原问向量召回 | `How should API keys be rotated?` 对真实来源排阈值前第 1，cosine **0.52006365**；被 0.55 过滤，MCP 返回 0 条 |
| 改写查询召回 | 原模型的改写 `API key rotation procedure secrets management` 得分 **0.68490122**，MCP 返回 1 条授权来源 |
| 宿主目标评分 | 同一片段对原宿主目标仍是 **0.52006364**，不足 0.55；改写不能改变宿主目标或把查询分数替代目标分数 |
| Required Source | 候选的 corpus/index/source/document/version/hash 与所需 Pin **1/1 匹配**；没有来源授权/Hash 错误。但无完成收据进入 Report，最终有效 Required Coverage 仍为 **0/1** |

原 EVIDENCE_INSUFFICIENT → WORKER_LIMIT → blocked 保留。此前的 Scorer null-receipt 修复也不改变该业务结局。这里可确认门槛过滤和原问相关性门控的作用，没有发现 pgvector cosine 算错或 Source Pin 丢失；不能把“检索到了真实来源”直接等同于目标证据充分。

## 新 Dev 的预登记与隔离

[公开输入及 Gold](../tests/fixtures/rag/embedding-ab-dev.json) 在任何新模型推理前登记：**56 条查询实例、28 份新合成文档**。校准 28、验证 28，正例主题各四类且不交叉；覆盖 zh→zh、en→en、zh→en、en→zh、多来源、混合 Required Pin、缺源、相关但无法证明业务结论、恶意文档指令、SQL 字符串和权限负例。

Plan SHA256：`b0093ac7c910342b728a84c21b2061585ace7e7f63b008c8af80cf341130db7a`。质量结果产生前固定代码、模型工件及推理输出的评测 Freeze SHA256：`3598f68f582c27b6a1cc2dec65cfc72e4c25afc7259cbd0c9bf5b492c8007850`。

这是同一作者构建的**公开、非盲 Dev**。同主题的语言变体相关，不能称为 56 个独立业务任务；通用缺源及安全控制的题面在两个 split 重复，零误命中也不能外推为独立阴性集的成功率。没有读取历史封存 Gold 来优化模型、规则或阈值。

新建专用数据库 `datapilot_test_embedding_ab_v1_20261029`，独立 `embedding_ab` Schema。其表按原生维度保存 512/1024 向量，初始化仅为该新库配置 SELECT Reader / SELECT+INSERT Ingest 权限，没有修改既有库 grants 或全局角色。现有生产 `rag.chunks` 和 ModelSpec 固定 512 维，因此新候选使用**可信研究探针的固定只读 SQL**；没有伪装为已经兼容原生产 MCP。

复用原 UTF-8 有界解析、192 字符/32 overlap、来源 ID、原文 SHA、ChunkSpan 和行号；每份短文实际都是一个 Chunk。两个 Corpus 共六个模型独立 IndexVersion，原文/文档身份跨模型相同，模型 Manifest、模型/分词器文件 SHA、recipe、维度和 IndexVersion 不混用。真实 PG 查询绑定版本与可信允许来源名单，结果逐条复核向量 Hash、文档/跨度/原文 Hash，并用独立 float64 cosine 对照 PG。

## 模型与公平性

| 模型 | 固定 revision | 原生维度与方式 |
| --- | --- | --- |
| 当前 BGE-small-zh-v1.5 | `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59` | 512；原 Qdrant 优化 ONNX、原中文 query prefix、CLS/L2 |
| BGE-M3 | `5617a9f61b028005a4858fdac845db406aefb181` | 1024；官方 dense PyTorch、无 query instruction、CLS/L2 |
| Qwen3-Embedding-0.6B | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | 1024；官方 PyTorch、固定英文 retrieval instruction、last-token/L2 |

依据 [BGE-M3 官方说明](https://huggingface.co/BAAI/bge-m3)与 [Qwen3 官方说明](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)配置各自推荐用法。没有截断向量或新做量化；所有输出为 F32 单位向量，未训练。使用匿名官方文件下载，按固定 commit 的 LFS SHA256/Git blob 校验，本地加载关闭 remote code；BGE-M3 官方 bin 仅用 PyTorch weights_only=True，Qwen 使用 safetensors。权重不提交 Git。

同机串行、CPU、2 线程、batch=1、最大 512 Token且超限拒绝；每模型 28 文档向量和 32 个唯一 query/goal，加两个固定不评分 warmup。没有 GPU、稀疏、多向量、Reranker、ANN 或 LLM 查询生成。Baseline 的 ONNX 与候选 PyTorch、各自推荐 instruction 不同，属于“实际部署 recipe”的比较，不是仅替换权重的纯 A/B。

独立实验环境使用 Python 3.11.16、torch 2.8.0+cpu、transformers 4.57.1、tokenizers 0.22.2；Baseline 保留原 ORT 1.31.0/tokenizers 0.23.3。实验版本与带 Hash 锁定记录另存；生产 pyproject/uv.lock/虚拟环境未改。

## 阈值及验证集结果

先用独立 calibration split 比较预登记 0.20–0.95、步长 0.05 的网格：约束缺源阴性误命中为零，依次最大化 macro Source Recall、Required Coverage、返回精度，同分取更高阈值。**每模型将 calibration-lock 写入后才读取 validation 排名**；验证结果没有反向调阈值。当前生产 0.55 仍保留，额外校准的 baseline 0.50 只是研究对照。

每模型验证 28 条，其中 2 条预期 Scope 拒绝单独计数，26 条检索：23 条有相关来源、22 条适用 Required、3 条 Gold 无相关来源。

| 校准后验证 | BGE-small | BGE-M3 | Qwen3 |
| --- | ---: | ---: | ---: |
| 锁定阈值 | 0.50 | 0.60 | 0.50 |
| Macro Source Recall@3 | 54.35% | 90.22% | **98.91%** |
| Macro Precision@3（固定分母3） | 23.19% | 36.23% | 39.13% |
| Macro returned Precision | 69.23% | **92.86%** | 89.13% |
| Micro returned Precision | 16/27＝59.26% | **25/28＝89.29%** | 27/32＝84.38% |
| Mean Required Coverage | 52.27% | 88.64% | **97.73%** |
| 所有 Required 均覆盖 | 11/22 | 19/22 | **21/22** |
| MRR@3 | 0.5652 | 0.9130 | 1.0000 |
| 有相关 Gold 却空召回 | 10/23 | 2/23 | **0/23** |
| 缺源阴性误召回 | 0/3 | 0/3 | 0/3 |
| 返回的无关来源条目 | 11 | **3** | 5 |

Recall 对非空相关 Gold 按 query 平均；Required Coverage 对适用 query 平均，Required 不能被补充来源替代。Macro returned Precision 对非空返回集合平均，包含阴性误命中为0、排除空返回，因此必须同时看 Recall；micro 为总相关返回/总返回，后者仅为补充统计，没有用于改阈值。该短文 Dev 的 Chunk/Document/Source 一一对应，数值相同，不外推长文分块效果。

一条 mixed-source query 有4个相关来源但 Top-k=3，导致 Macro Recall 的理论上限就是 **98.91%**；Qwen 达到的是这个小型 Dev 的上限，不能称为真实产品接近100%成功。

阈值前 Raw Recall 为 93.48% / 98.91% / 98.91%。统一0.55后的 Recall 为 54.35% / 90.22% / 90.22%，对应无关条目 7/12/4；独立校准后分别为 11/3/5。Baseline 仅降低阈值没有改善本验证集 Recall，反而增加无关条目。这支持比较模型与分数分布，不能只为旧题全局降低阈值。

普通语言矩阵每格4条验证 query：

| query→文档 | BGE-small | BGE-M3 | Qwen3 |
| --- | ---: | ---: | ---: |
| zh→zh | 4/4 | 4/4 | 4/4 |
| en→en | 4/4 | 4/4 | 4/4 |
| zh→en | **0/4** | 4/4 | 4/4 |
| en→zh | **0/4** | 4/4 | 4/4 |

当前模型的主要新 Dev 弱点是跨语言，不能依据一个旧短问声称所有英文都不可用。

## 延迟、内存与残留错误

本机 32 logical CPU、约15.73GiB RAM，开始时空闲约2.32GiB；RTX 5060 Laptop 8GB 存在但未用。后台服务、OS文件缓存和固定模型顺序未控制，不能据冷启动总时间排名推理速度。

| 本地资源（单进程观测） | BGE-small | BGE-M3 | Qwen3 |
| --- | ---: | ---: | ---: |
| 唯一 query 编码 p50 / p95（32条，ms） | 5.20 / 7.30 | 92.68 / 110.17 | 201.03 / 224.49 |
| 模型加载及文件验证（s） | 0.60 | 34.29 | 7.29 |
| Peak process RSS（GiB） | 0.197 | 2.670 | 3.641 |
| 进程 CPU seconds | 1.16 | 23.20 | 24.69 |
| 完整编码进程 wall seconds | 0.92 | 40.85 | 18.51 |
| PG排名＋来源校验 p50 / p95（26条，ms） | 6.30 / 9.92 | 7.53 / 10.89 | 5.42 / 7.09 |

p50取中位数、p95 nearest-rank。PG计时使用既有向量，不含编码、MCP或Agent；不能把两组分位数直接相加冒充实测 E2E。RSS 是进程物理工作集峰值，不是整个系统成本。Qwen 的总进程较短但稳态编码更慢；加载格式、权重大小、Hash I/O与OS缓存不同，不能倒推 Qwen 推理比M3快。三模型实测都在900秒观察限额内，内存硬上限5GiB未触发；没有以无界加载替代资源记录。

全部质量失败保存为30条“模型×案例”记录及完整排名，没有改 Gold 或重选阈值：

- BGE-small 的 v-03/04 等跨语言查询在原始Top3内存在正确来源，过滤后为空。
- BGE-small 的 v-27/28 模糊改写查询仍空召回，泛化查询不能自动等价于宿主目标。
- BGE-M3 的 v-27/28 也空召回；新模型并非任意改写都成功。
- **三个模型的 v-19** 都只覆盖1/2 Required Pin，尽管相关来源精度为1；替代语言版本不是所需的精确来源快照。
- BGE-M3 的 v-01/02/04、Qwen 的 v-01/02/03/04仍返回相关任务之外的额外来源；不是越权，但会增加报告选择证据的负担。
- Qwen 的 v-23能命中含恶意指令的相关背景，同时返回一条无关来源。本轮只有解析、编码、固定SQL和Scope检查，无生成式Agent，**不能声称完整Agent已通过Prompt Injection实测**。
- v-22 可返回背景资料，但 Gold 明确没有业务/因果保证；Source 覆盖不等于事实证明，本轮全部 business_verified=false，未生成报告。

## 安全、验证与完整性

三模型真实执行156次原生PG质量排名、另78次只读PG计时；生成6个新IndexVersion、84条真实模型向量。12条跨Source/owner请求均在取数据前拒绝，3条伪造Index拒绝。Reader默认只读事务实际拒绝CREATE/DELETE（25006）；在独立负例事务中覆盖只读设置后，数据库grants仍拒绝（42501），共4次实际拒绝，无成功DDL/删除或权限更改。

第一次安全探针误以为必定先得到42501，实际被更早的25006挡住而断言失败，日志保留。后续将两个安全层分别验证；没有放宽角色或检索检查。

Python3.11/3.13 定向回归各 **39 passed、13 integration deselected**，涵盖新16项指标/范围/向量边界及原语言/Scorer反例。新模型质量证据来自真实本地推理＋新PG，绝非这些单元测试。原历史诊断确实使用原PG/MCP；新模型的原生产MCP接口、Worker/Stop Hook/Report/Durable、多进程恢复、GPU、长文/ANN、完整pytest/CI、DeepSeek Live 均 **not_run**。

662份既有文件和原结果Seal保持；`src/`、生产默认、P3、角色规则、Scorer、旧Gold/封存均无字节变化。既有业务库只有明确的只读诊断，无新业务写入；所有实验索引只写新Dev库。生产依赖锁文件未改，未Seed、删数据库/Volume、训练、调用付费API或提交推送。

## 是否迁移及最小后续方案

两个候选都通过预登记的 Dev 候选 Gate（Recall和Required提升，缺源阴性及无关条目不增加，范围/Hash检查通过）。**建议优先将 Qwen3 作为覆盖率候选，M3作为较低CPU/RSS的备选，进入一次单独授权的迁移验证；当前不直接切换默认。** 只有3条验证阴性、四个正例主题，且校准针对query阈值；新目标相关性策略仍需独立标签与更强的无关高相似度负例。

1. 先用新独立 Dev 确认召回/Required/误召回，选定一个固定模型 profile。此次56条已被观测，不能反复充当未来 sealed Holdout。
2. 新增明确的1024维迁移与版本化 ModelSpec/Index/Citation 契约，保留旧512表、旧模型缓存和旧Index/Run绑定。模型选择只能来自可信宿主/索引Manifest，不能由LLM扩权或静默按新默认解释旧证据。
3. 为新Embedding绑定新版本search/goal policy和独立阈值；保留Required/Supplement、事实/因果、P3及权限验证。不能把Qwen阈值塞进名为 bge-host-goal-cosine-v1 的旧策略。
4. 复用现有MCP加载缓存，先验证可信预热、10秒MCP超时、取消与Durable恢复。M3冷加载34秒是直接替换的明显风险；Qwen7秒也需连同进程/Hash/检索开销实测，不能直接放宽时限或盲重发。现有缓存不足时才另行讨论常驻方式，不预建第二套服务。
5. 最后对新独立业务Dev验证完整MCP→Worker→Receipt→Report→恢复，取得新Freeze和单独Live授权后再做有界真实模型Smoke。

[机器结果、全部Bad Cases与指标定义](research/p7-embedding-ab-results.json)记录模型Manifest Hash、六个IndexVersion、分组结果和代价。原始本地材料在忽略目录 `artifacts/p7/embedding-ab-v1/`，包含预登记、模型文件Manifest、带Hash的实验依赖锁、CPU进程记录、校准锁、完整排名/跨度/源Hash、负例和旧结果保护检查；本地路径不代表可公开下载。研究实现见 [experiment.py](../evaluation/embedding_ab/experiment.py)、[evaluate.py](../evaluation/embedding_ab/evaluate.py)、[model_worker.py](../evaluation/embedding_ab/model_worker.py)及[测试](../tests/test_embedding_ab.py)。本轮到此停止。
