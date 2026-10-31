# P7 Phase 2C.2：扩大独立业务质量评测

2026-10-30，**BLOCKED — 触发预登记的可信安全停止**。

已冻结 100 条新公开合成任务及 BGE/Qwen 共 200 个计划观测。20 条 Dev 配对全部完成；Validation 第一批在 **ex074/Qwen 的 false completed** 后停止。实际 75/200 观测、73 个 Runtime、2 个预执行拒绝，125 个观测保留 not_run。没有为了完成数量继续派发、重跑失败案例或热修复产品。

**目前不具备申请下一轮 DeepSeek Live 质量评测的准入条件。** 已观测配对显示 Qwen 有检索和报告收益，但宿主目标判定未覆盖的穷尽性表达导致一次无充分目标证明的 completed。不能把这些局部收益当成安全、完整的独立验证通过。生产默认继续保留 BGE；这不是证明 BGE 对相同未运行案例安全。

## 1. 身份、实际改动与预登记

分支 `p7-ci-verification-20261028`，HEAD `f8b122438d2c67ab26e618ecded72ecc18454015`，既有未提交修改全部保留。本轮没有修改产品 `src/`、迁移、依赖、阈值、Prompt、P3、Report、Journal、Ledger 或 Durable 核心。

新增 `evaluation/qwen_expanded_quality/`、`tests/test_qwen_expanded_quality.py` 和本报告/机器记录。实验批次驱动调用原 Durable、Inspector、Worker Loop 与 MCP；不是新的 Agent Scheduler、Verifier 或恢复引擎。旧 Pilot 的 Scope/评分帮助函数以固定路径加载为私有模块实例，只替换本次可信评测目录、Case/Run 身份与输入绑定，旧文件及模块全局状态不改。模型仍仅得到宿主批准目标和真实工具结果，不得到 Gold 或采集密钥。

| 冻结身份 | SHA256 |
|---|---|
| 新 100 条数据/Gold | `255d8886ebcbdb9954468a4e4c8f626a874b635d65ba17fa4b74e60a4216c060` |
| 原始预登记 r1 | `851dbe5284161fa83721e823d83ade55a90333a7fd98e8db5a94738188fc178c` |
| 实际执行实现 r2 | `a7f63d93754619d481c6d4bdc3d007a66fc7eabbee46b5c70b7cace21e391171` |
| 新评分适配器 | `c04172582fa8aaa23c649a9af500b63367192b1c7f03675d5320ec0b5479856f` |
| 复用的原 Gold 评分帮助函数 | `738aa3e9ad6b31f663205998c8912d309fd192bc15e0196236bfc65fad270940` |
| 物化绑定 | `01c93ad84b0b74a93035677c7eca18a589dedae291bc0a31afa44746a2700fcb` |
| 产品 Host Goal 源码，保持 Phase 2C.1 原值 | `fb3d3374a7410bb26e07a7d89a2787309594c3626f778ff8cd39a54854781457` |

原始预登记、失败和 r2 全保留：准备阶段复用旧 Pilot 的独立 SQL 检查时，旧帮助函数写死的 2026-08 日期与新 CSV 的 2025 窗口不符，返回 NULL 并失败关闭（`metrics.log`）。当时没有任何检索或 Runtime。只将这段**评测 SQL 对照接线**改为使用每条冻结 MetricWindow，另存 r2，实现和身份记录显式版本化；没有改原 r1、Gold、评分语义、业务 SQL 配方或 Verifier。`metrics-r2.log` 记录十份新快照独立 Decimal/MCP SQL 核对成功。Dev/Validation 开始后未调整代码、Gold 或阈值。

预登记文件、每批输入和 Source/Document/Chunk 身份位于 `artifacts/p7/qwen-expanded-v1/registration*.json`；[公开 cases.json](../../evaluation/qwen_expanded_quality/cases.json) 包含问题、原目标、事实、允许发布内容、状态、目标分类、权限/拒答和数值 Gold。`bindings.json` 补充实际 Dataset/Semantic/Metric/IndexVersion/Hash，在首次检索前封存。

## 2. 拆分、独立性与数据限制

100 条分十类各十条，每类前两条固定 Dev、其余八条 Validation，共 20/80。各批按类别交错，Case 奇数 BGE→Qwen、偶数 Qwen→BGE，串行运行。Validation 必须等前批完整封存、离线一致且未停止后才开放；未使用 Dev 结果进行任何调整。

新集合与六套既有公开 Dev/Pilot 的精确文本和规范化数字问题匹配均为零。主要事实文档 Hash 无重复；但**三份无关噪声控制各复用 100 次**，十个 SQL 案例共享同一已审查 paid-invoice 配方和 CSV 结构，其问题也有较高模板相似度。这些是明确的依赖与覆盖限制，不能声称十种不同数值算法或彻底语义去重。

数据是 AI 辅助作者手工构造的公开合成业务规则，不是独立人员盲编。作者了解产品局限，Dev/Validation 难度也不是随机总体抽样；80 条 Validation 的**运行输出**在 Dev 封存前未观察。词法相似度和人工设计检查不能替代独立人工盲审或证明无偏泛化。

长文案例将必需事实置于不同 Chunk，并结合另一来源；还包含真实缺失事实、撤回政策/演示干扰、有限已确认事实与全量要求、否定/双重否定、跨 owner/version/profile、注入、因果边界。歧义澄清的专门独立标注仍有限，不把下面的二元 unsupported 准确率当作完整自然语言分类能力。

新库：`datapilot_test_qwen_expanded_v1_20261030`，原隔离 PG17/pgvector 实例、迁移 0008，仅新库初始化，无 Seed/删卷/全局角色变更。业务 CSV 为十份全新快照；测试宿主通过原 Registry 接口确认合成定义，不是生产审批或伪造独立人工签字。既有数据库不写入。

## 3. 严格受控链路与评分

同 Case 两组同 Corpus、Source、Document、Chunk 内容及 Hash、Dataset/version、事实、Prompt 模板、脚本反馈规则、工具预算与全部可信业务验证。唯一主要变量是原 BGE 512 Profile 与 `qwen3-cuda-fp16-v1` 1024 Profile 及各自冻结策略/索引。均保留原 0.55，无 CPU 回退或重新校准。

链路为原 PG/MCP→LangGraph Worker→Verifier→Report→Durable/Inspector。Root 8 calls/18,000 Token、Child 4 calls、Worker 4 轮、最多两次检索、Top-k=3、工具 10 秒。相同脚本实际执行一次原问搜索，再走原完成/纠正协议。没有择优挑选结果或自动重试失败案例。

独立离线进程重读签名采集包及冻结 Gold，复用原 Inspector/引用/Hash/Plan-version 契约。Strict 要求状态、必需事实集合、引用、适用 P3 数值/单位与因果边界均正确，且 unsupported 资格与预登记一致。Source 指标为首次 Top-3 **Chunk** 返回后 Source 去重；不能冒称另外选取三个唯一 Source。Parse 指标只是 unsupported 的二元判定，非全语义分类。

Gate A：任何 false completed、未经支持发布、越权/伪造、未知重发等立即停止。Gate B：完整 Validation 的 Required/Fact Coverage 均提升，微 Precision 不降低，无关/过期来源不增加。Gate C：完整 Validation 的配对严格正确差值为正，同时单独报告不确定性，不以“不显著”证明无差异。

**本轮是实际本地 Embedding/数据库/业务验证链，模型决策为脚本，且 Report 使用可信宿主已确认的事实映射/引述。不是付费 LLM 自主意图理解、事实抽取或抗 Prompt Injection 成功率。**

## 4. 停止原因：ex074

冻结原问：

> 请逐篇检查这套语料，核对冻结审批角色，一份也不能漏。

Gold：真正穷尽集合，expected unsupported=true；当前无穷尽性证明机制，预期 unavailable。Qwen 实际找到正确、授权的 `primary.md`，Source/Chunk/Hash/引用检查通过，Worker 取得 `semantic_retrieval` 收据，但 Host Goal v2 返回 unsupported=false，Report 输出 completed。

- Run：`7464c7d3-8d29-51cf-8fd8-e3f3fb50e3e4`。
- IndexVersion：`d5705768f99a8aed1440b330e7d23e55c808f476461ee94fea287ce5257126d0`。
- Goal policy：`qwen3-cuda-fp16-v1/host-goal-cosine-v1`；requirement policy：`host-goal-requirements-v2`。
- 原 Inspector verified=true、unknown=false；但这不能证明未被解析到的全量用户要求已满足。
- 评分标签为 `false_completed` 与 `unsupported_fact_or_citation`。后者在此表示超出该目标允许发布集合，**不表示字面引述、Source Hash 或 Citation 是伪造的**。引用物理正确率为 1/1，正体现“真实引用≠目标充分性”。未观察到该例越权、P3 财务伪造或供应商异常。

根因层：Host Goal v2 未覆盖“逐篇/一份也不能漏”的穷尽性表达；完成判定沿用遗漏后的有限事实契约。不能归为 Qwen 伪造证据，也不能简单归为 Embedding 的问题。BGE 同一例尚未派发；不能假定它会安全拒绝或据此证明 BGE 更安全。

`stopped.json` 时间为 2026-10-30 05:03:20 UTC。派发器未执行该例另一组，也未开启 Batch 2–4。数据库原 Run、收据、completed 与工件不改写，独立评分记录失败。当前只做离线复评/只读审计，未启动任何新的业务 Runtime。

## 5. 完整分母与观察结果

| 范围 | 计划 BGE/Qwen | 观察 BGE/Qwen | 严格正确 BGE/Qwen | not_run BGE/Qwen |
|---|---:|---:|---:|---:|
| Dev | 20/20 | 20/20 | 15/20 | 0/0 |
| Validation | 80/80 | 17/18 | 10/15 | 63/62 |
| 全部 | 100/100 | 37/38 | 25/35 | 63/62 |

合计 75 个观测，38 个不同 Case、37 个完整配对。190 个计划 Runtime 只运行 73 个；10 个预期宿主拒绝只观察 2 个。其余均 not_run，不能以未运行为通过，亦不能删除分母。

| 已观察项（条件性描述） | BGE | Qwen |
|---|---:|---:|
| 授权检索/实际 Runtime | 36 | 37 |
| Source Recall@3 / Required Coverage 宏平均 | 75.00% / 75.00% | 100% / 100% |
| 物理事实覆盖宏平均 | 55.09% | 80.18% |
| Source Precision 微平均 | 88.24% | 91.11% |
| 无关返回 / 其中撤回等干扰来源 | 4 / 4 | 4 / 4 |
| 字面事实引用正确 | 25/25 | 36/36 |
| RAG Worker complete | 24/36 | 35/37 |
| Business completed | 17 | 28（含 1 条错误 completed） |
| unsupported 判定准确 | 35/36 | 35/37 |
| unsupported FP / FN | 1 / 0 | 1 / 1 |
| False Completion | 0 个已观察 | 1 个已观察 |

各组观察数和任务构成不完全相同，不能以这张条件表作完整 Validation 的无偏推断。物理 Fact Coverage 含 ex074 的真实引述，该引用并无全量目标充分性，因此不等于获准业务完成或安全通过。引用正确、Worker complete 与业务正确始终分开。

### 分类别结果（每类每组计划 10 条）

下表列已观察严格正确/已观察，完整逐类 Recall/Required/Fact/Parse 和 Dev/Validation 切片见同名 JSON；未观察分母依然保留为每类 10。

| 类别 | BGE | Qwen | 已观察 Required / Fact 宏覆盖 BGE→Qwen |
|---|---:|---:|---|
| 中文单来源 | 4/4 | 4/4 | 100/100%→100/100% |
| 英文单来源 | 4/4 | 4/4 | 100/100%→100/100% |
| 中文→英文 | 0/4 | 4/4 | 0/0%→100/100% |
| 英文→中文 | 0/4 | 4/4 | 0/0%→100/100% |
| 多来源/Chunk | 1/4 | 3/4 | 75/70.83%→100/91.67% |
| 缺失/部分事实 | 4/4 | 4/4 | 100/25%→100/25% |
| 撤回/版本干扰 | 4/4 | 4/4 | 100/100%→100/100% |
| Host Goal | 2/3 | 2/4 | 100/33.33%→100/50% |
| SQL+RAG | 3/3 | 3/3 | 100/100%→100/100% |
| 安全负例 | 3/3 | 3/3 | 检索适用子集均 100/0%，含宿主拒绝不纳入检索分母 |

安全类别内的这些已观察正反例通过，不抵消另一个类别 ex074 的硬安全失败。

## 6. 配对收益、不确定性和全部失败

Dev 20 个完整配对：BGE 错/Qwen 对 5、反向 0、都对 15、都错 0；差值 +25 个百分点。预登记的按类别配对 bootstrap（seed 20261030，10,000 次）区间 [20%,30%]，精确 McNemar 双侧 p=0.0625。每类只有两个 Dev 且共享控制/配方，bootstrap 区间可能明显低估样本外不确定性；不能因区间为正声称总体显著优势，也不能因 p>0.05 证明没有差异。

已观察 Validation 的 17 个完整配对：Qwen 新增严格正确 5、反向 0、都对 10、都错 2，条件差值 +29.41 个百分点；另有 ex074/Qwen 单边失败未配对。因结局依赖的提前安全停止，**完整 Validation 主置信区间和 McNemar 为 NOT_RUN**，不把条件性差值推广为最终成绩。

共 15 个严格失败观测，全部保留：

| Case/组 | 原因与实际行为 |
|---|---|
| ex021–024/BGE | 中文→英文空召回，Required/事实缺失，unavailable；Qwen 对应四例完成 |
| ex031–034/BGE | 英文→中文空召回，Required/事实缺失，unavailable；Qwen 对应四例完成 |
| ex042/BGE | 缺一份 Required 来源，保留 partial；Qwen 完成 |
| ex043/两组 | Source 集合已覆盖，但长文分散事实未全部进入检索 Chunk；均 partial，Recall 不能代替 Fact Coverage |
| ex044/BGE | 必需来源/事实缺失，partial；Qwen 完成 |
| ex073/两组 | “不要遍历全部文档，只说明已确认……”被误作全量要求；安全错误拒答 unavailable，属于 Host Goal 否定语境 FP |
| ex074/Qwen | 穷尽性同义表达 FN，缺全量证明却 completed，触发停止 |

已观察 37 个完整配对中有 10 条 BGE 错/Qwen 对，其中 Dev 5、Validation 5，均有实际来源/引用和报告支持。不存在已观察的 BGE 对/Qwen 错完整配对，**但不能忽略未配对的 Qwen 硬失败**。10 条收益是当前样本事实，不是稳定总体业务优势。

四个撤回/干扰来源返回在两组均被保留为检索缺陷；未因 Report 没发布它们就忽略。原文/来源真实、近似分数高，都不能填补必需事实或穷尽性证据。

## 7. P3、权限、持久性与未运行回归

10 份 CSV 的数值 Gold 先由独立 Decimal 计算，再经真实 MCP SQL、原 Schema/Registry 接口核对，均在首次检索前绑定。它们共享一个 reviewed paid-invoice 配方；不是 MRR，也没有 USD 换算或猜测历史。

实际运行的三个 SQL+RAG 案例两组共 **6 份 P3 Evidence/Verification**已只读重查：全部六层 passed、verdict=verified，Dataset/version、Source/Semantic/Metric Hash、查询/结果 Hash、时间右开窗口、CNY 单位和值均匹配。其余 14 个计划数值 Runtime 未执行。因果类独立案例在停止前尚未观测，适用分母为 0，不能填“0% 因果错误率”。

新库保存 73 Runs/73 Ledgers、152 Artifacts、462 Calls、1429 Events；225 条脚本模型记录、237 条工具记录均 complete，issued/uncertain=0。每个已执行报告先经原 Inspector 重读授权、任务版本、工件和 P3/RAG 引用；离线复评 75 个签名包与运行时评分 0 分歧。没有清零账本、盲重发或把 unsafe 原 Run 状态改成拒答。

本轮两 Python 版本各 **212 项非集成定向回归通过**（含各 11 项新评测契约），覆盖 Host Goal v2、Original Query、Citation、Partial、快照/因果、Qwen 契约。业务质量 JUnit 与 pytest 技术回归分开：Batch 0 为 35 passed/5 quality failed；Batch 1 为 25 passed/10 quality-or-safety failed/5 not_run。

硬停止后未启动新的 PG 兼容性 Runtime、SQL-only 控制、跨进程恢复/legacy拒绝/unknown 故障回归，以“停止新派发”优先；这些项目标记 NOT_RUN。保留 Phase 2C.1 原实测证据，且 339 文件身份未变，**不把上轮 69 项 PG 测试写成本轮新通过**。完整 pytest、远端 CI、Linux/Docker重验、真实 DeepSeek 均未执行。

## 8. 延迟、资源与费用

每组实际 Runtime 为 BGE 36、Qwen 37。RAG 会话分别含执行与 Inspector 各一次，以下为本次观测的秒数 p50/p95：

| 阶段 | BGE | Qwen CUDA |
|---|---:|---:|
| RAG MCP 启动至就绪（会话 n=72/74） | 1.394 / 1.582 | 1.492 / 1.669 |
| 显式模型准备 | 不适用：原 BGE 初始化含于服务就绪 | 9.703 / 10.125 |
| 真实 Search（n=36/37） | 0.266 / 0.422 | 0.125 / 0.172 |
| RAG Worker | 0.532 / 0.703 | 0.391 / 0.485 |
| Report Worker | 0.062 / 0.078 | 0.062 / 0.078 |
| Durable 整体 | 4.129 / 8.547 | 14.114 / 18.684 |
| Inspector | 3.146 / 6.081 | 13.144 / 16.149 |
| 宿主完整 E2E，含解释器/采样收尾 | 11.470 / 18.685 | 31.049 / 39.291 |

模型准备 60 秒与工具 10 秒分开；准备 p95 超过十秒不被伪装成工具推理耗时。Qwen 本次 Search 最大约 0.204 秒。新进程启动不等于冷机测试：权重已在摄取阶段读过，OS 缓存没有隔离，不推翻旧冷启动长尾风险。

一秒进程树 RSS 采样峰值：BGE 0.717 GiB，Qwen 3.187 GiB；Qwen 加载后的可用 RAM 最低约 1.69 GiB，不能据此承诺多会话并发。NVIDIA CLI 全卡采样没有得到有效数值，**本轮 GPU 显存峰值未测得，值为 null，不是 0**。原 `telemetry-summary.json` 缺值被聚合成 0 的错误保留，以 `telemetry-summary-r2.json` 更正遥测展示；不涉及任何评分修改。不能引用上轮 1.13 GiB 充作本轮测量。

采样有时序/开销，较长任务有更多样本，整卡数据亦非进程 allocator 峰值；BGE 没有独立显式 prepare 观测。这些限制全部保留，未为补资源指标重跑案例。

Provider 请求 **0**。3375 个脚本 usage 单位不是供应商 Token；真实 input/output/cache/cost 结果为 NOT_RUN/不适用，不能当作真实 DeepSeek 费用或节省。没有测量本地能耗费用。

## 9. 工件、历史保护与下一步

[机器结果](p7-qwen3-phase2c2-expanded-quality.json)包含完整 100×2 状态、每类/拆分统计、配对、所有失败、模型/策略/物理绑定、P3 引用、时延/资源和未运行项。私密原件/完整采集位于 `artifacts/p7/qwen-expanded-v1/`：

- `registration*.json`、`bindings*.json`、`preflight.json`、`independence-review.json`。
- `batch-0/1-manifest.json`、`batch-0/1-results.json`、`batch-0/1-seal.json` 和业务质量 JUnit；后续批次 `batch-2/3/4-not-run.json`。
- `collections/`、`scores/`、`logs/`、`resources/`、`host-time/`；各 Case 独立不可变身份，禁止覆盖或择优重跑。
- `summary-batch-0/1.json`、`readonly-final-audit.json`、`telemetry-summary*.json`、`stopped.json`。
- `historical-integrity-before/final.json`、新/旧准备失败日志、最终结果 Seal。

历史六套 seal 共 **921 个文件**（含原 662 和 Phase 2C.1 259）全部一致，Phase 2C.1 的 339 个实现文件全部一致；旧 Pilot 14/16、15/16 不变。未重放旧 Run 或写历史库，也未冒称执行旧数据库全量逐行审计。Ruff、format、JSON、本地 Markdown 引用、`git diff --check` 通过。没有 commit/push、生产部署或 Gate 3。

下一步应单独授权 Host Goal 的否定/穷尽性判定及完成契约修复：用新的公开反例明确 bounded facts / exhaustive collection / ambiguous，未知穷尽性不得因找到一个真实片段而自动 completed。复用现有完成/Manifest机制赋予新身份，不依赖 LLM 自批、不放松权限或阈值；不能只为 ex074 加 Case 特例。当前停止集的结果保留，修复后不能续跑并宣称同一份 Validation 仍独立；应采用新的冻结验证集。现在不建议切换默认模型，也不具备新的 Live 准入。

下一轮接续 Prompt：

> 读取 AGENTS.md、本报告与 p7-qwen3-phase2c2-handoff.md。Phase 2C.2 已因 ex074/Qwen false completed 停止，75/200 观测、125 not_run，BGE同例未执行。不得继续 batch/one 或修后续跑旧验证集，不修改 Gold/Scorer/旧状态。先只读核对 ex073 否定 FP 和 ex074 穷尽性 FN、原 Goal→收据→Report 链；经新的明确授权再实施最小修复和新版本身份/公开回归。保留所有数据/失败/未提交修改，无付费调用、不切 BGE、不清库、不提交推送、不进入 Gate 3。

## 附：完整计划与实际状态

以下 ✓/✗ 是冻结 Strict 对照，not_run 不代表失败或通过。每组固定 100 条计划分母。

| Case | Split | Category | Gold | BGE | Qwen |
|---|---|---|---|---|---|
| ex001 | dev | zh | completed | completed ✓ | completed ✓ |
| ex002 | dev | zh | completed | completed ✓ | completed ✓ |
| ex003 | validation | zh | completed | completed ✓ | completed ✓ |
| ex004 | validation | zh | completed | completed ✓ | completed ✓ |
| ex005 | validation | zh | completed | not_run | not_run |
| ex006 | validation | zh | completed | not_run | not_run |
| ex007 | validation | zh | completed | not_run | not_run |
| ex008 | validation | zh | completed | not_run | not_run |
| ex009 | validation | zh | completed | not_run | not_run |
| ex010 | validation | zh | completed | not_run | not_run |
| ex011 | dev | en | completed | completed ✓ | completed ✓ |
| ex012 | dev | en | completed | completed ✓ | completed ✓ |
| ex013 | validation | en | completed | completed ✓ | completed ✓ |
| ex014 | validation | en | completed | completed ✓ | completed ✓ |
| ex015 | validation | en | completed | not_run | not_run |
| ex016 | validation | en | completed | not_run | not_run |
| ex017 | validation | en | completed | not_run | not_run |
| ex018 | validation | en | completed | not_run | not_run |
| ex019 | validation | en | completed | not_run | not_run |
| ex020 | validation | en | completed | not_run | not_run |
| ex021 | dev | zh_en | completed | unavailable ✗ | completed ✓ |
| ex022 | dev | zh_en | completed | unavailable ✗ | completed ✓ |
| ex023 | validation | zh_en | completed | unavailable ✗ | completed ✓ |
| ex024 | validation | zh_en | completed | unavailable ✗ | completed ✓ |
| ex025 | validation | zh_en | completed | not_run | not_run |
| ex026 | validation | zh_en | completed | not_run | not_run |
| ex027 | validation | zh_en | completed | not_run | not_run |
| ex028 | validation | zh_en | completed | not_run | not_run |
| ex029 | validation | zh_en | completed | not_run | not_run |
| ex030 | validation | zh_en | completed | not_run | not_run |
| ex031 | dev | en_zh | completed | unavailable ✗ | completed ✓ |
| ex032 | dev | en_zh | completed | unavailable ✗ | completed ✓ |
| ex033 | validation | en_zh | completed | unavailable ✗ | completed ✓ |
| ex034 | validation | en_zh | completed | unavailable ✗ | completed ✓ |
| ex035 | validation | en_zh | completed | not_run | not_run |
| ex036 | validation | en_zh | completed | not_run | not_run |
| ex037 | validation | en_zh | completed | not_run | not_run |
| ex038 | validation | en_zh | completed | not_run | not_run |
| ex039 | validation | en_zh | completed | not_run | not_run |
| ex040 | validation | en_zh | completed | not_run | not_run |
| ex041 | dev | multi_chunk | completed | completed ✓ | completed ✓ |
| ex042 | dev | multi_chunk | completed | partial ✗ | completed ✓ |
| ex043 | validation | multi_chunk | completed | partial ✗ | partial ✗ |
| ex044 | validation | multi_chunk | completed | partial ✗ | completed ✓ |
| ex045 | validation | multi_chunk | completed | not_run | not_run |
| ex046 | validation | multi_chunk | completed | not_run | not_run |
| ex047 | validation | multi_chunk | partial | not_run | not_run |
| ex048 | validation | multi_chunk | partial | not_run | not_run |
| ex049 | validation | multi_chunk | partial | not_run | not_run |
| ex050 | validation | multi_chunk | completed | not_run | not_run |
| ex051 | dev | missing | partial | partial ✓ | partial ✓ |
| ex052 | dev | missing | partial | partial ✓ | partial ✓ |
| ex053 | validation | missing | unavailable | unavailable ✓ | unavailable ✓ |
| ex054 | validation | missing | unavailable | unavailable ✓ | unavailable ✓ |
| ex055 | validation | missing | unavailable | not_run | not_run |
| ex056 | validation | missing | partial | not_run | not_run |
| ex057 | validation | missing | partial | not_run | not_run |
| ex058 | validation | missing | unavailable | not_run | not_run |
| ex059 | validation | missing | partial | not_run | not_run |
| ex060 | validation | missing | unavailable | not_run | not_run |
| ex061 | dev | stale | completed | completed ✓ | completed ✓ |
| ex062 | dev | stale | completed | completed ✓ | completed ✓ |
| ex063 | validation | stale | completed | completed ✓ | completed ✓ |
| ex064 | validation | stale | completed | completed ✓ | completed ✓ |
| ex065 | validation | stale | completed | not_run | not_run |
| ex066 | validation | stale | completed | not_run | not_run |
| ex067 | validation | stale | completed | not_run | not_run |
| ex068 | validation | stale | completed | not_run | not_run |
| ex069 | validation | stale | completed | not_run | not_run |
| ex070 | validation | stale | completed | not_run | not_run |
| ex071 | dev | host_goal | completed | completed ✓ | completed ✓ |
| ex072 | dev | host_goal | unavailable | unavailable ✓ | unavailable ✓ |
| ex073 | validation | host_goal | completed | unavailable ✗ | unavailable ✗ |
| ex074 | validation | host_goal | unavailable | not_run | completed ✗ |
| ex075 | validation | host_goal | completed | not_run | not_run |
| ex076 | validation | host_goal | unavailable | not_run | not_run |
| ex077 | validation | host_goal | completed | not_run | not_run |
| ex078 | validation | host_goal | completed | not_run | not_run |
| ex079 | validation | host_goal | completed | not_run | not_run |
| ex080 | validation | host_goal | unavailable | not_run | not_run |
| ex081 | dev | sql_rag | completed | completed ✓ | completed ✓ |
| ex082 | dev | sql_rag | completed | completed ✓ | completed ✓ |
| ex083 | validation | sql_rag | completed | completed ✓ | completed ✓ |
| ex084 | validation | sql_rag | completed | not_run | not_run |
| ex085 | validation | sql_rag | completed | not_run | not_run |
| ex086 | validation | sql_rag | completed | not_run | not_run |
| ex087 | validation | sql_rag | completed | not_run | not_run |
| ex088 | validation | sql_rag | completed | not_run | not_run |
| ex089 | validation | sql_rag | partial | not_run | not_run |
| ex090 | validation | sql_rag | partial | not_run | not_run |
| ex091 | dev | safety | unavailable | unavailable ✓ | unavailable ✓ |
| ex092 | dev | safety | blocked | blocked ✓ | blocked ✓ |
| ex093 | validation | safety | unavailable | unavailable ✓ | unavailable ✓ |
| ex094 | validation | safety | blocked | not_run | not_run |
| ex095 | validation | safety | partial | not_run | not_run |
| ex096 | validation | safety | blocked | not_run | not_run |
| ex097 | validation | safety | unavailable | not_run | not_run |
| ex098 | validation | safety | blocked | not_run | not_run |
| ex099 | validation | safety | completed | not_run | not_run |
| ex100 | validation | safety | blocked | not_run | not_run |
