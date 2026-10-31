# P7 Gate 2B 首轮 Live：Scorer v2 与离线根因审计

2026-10-25。完成本轮 Scorer 修复、原 31 条签名观测的离线复评及六条 Bad Case 分析。**没有重新执行原 Campaign，也没有调用模型、检索、Embedding 或数据库；剩余 29 条仍 not_run，Gate 2B 完整 Live 仍未验收。**

原 [首次 Live 报告](p7-gate2b-live.md)、v1 25 passed / 6 failed、60 条状态账本、61 次调用、77,897 Token 和 USD 0.009241476 估算费用原样保留。该费用仍不是实际账单；本轮新调用数为 0。修订成绩来自同一份响应的评分器契约修复，不是新一轮模型效果。

## 1. 已确认的版本键缺陷与最小修复

源码及实际持久记录相互吻合：

- `src/datapilot/state.py::RunState` 用 results / verifications 的版本化映射保存并行结果，保留 plan_history 与 reuse_origins。
- `orchestration/coordinator.py::key` 产生 `version:task_id`；Replan 增加 plan_version，只在宿主明确允许时复制未变化且已验证的源任务，设置 reused_from。
- 原签名 bh2-030 的当前 Plan 为 v1，RAG TaskResult 和 VerificationResult 位于 `1:documents`；其 unavailable / empty 完成收据有真实提交工具与模型调用对应。原 Scorer 两处却查 `results.get("documents", {})`，丢失了该结果。

只改 `scripts/p7_business_evaluator.py`：新增唯一的 `rag_result` 定位函数，供原拒答检查及 RAG 完成统计共用，删除两处未版本化查找。没有修改 Gold、拒答词表、阈值或业务成功条件。

定位依据及每项新增检查的必要性：

1. 用原 Plan / plan_history / 当前 plan_version 定位精确键；不扫描“最新的同名结果”，不回退未版本化别名。防止选到旧任务或错误 Worker。
2. 复用原 Plan、TaskResult、VerificationResult DTO，核对 Run、目标、Worker、版本和当前编排检查。没有完整当前任务证明就 fail-closed，不能仅凭 succeeded。
3. Replan 复用要求原 reuse_origins、旧 Plan 的相同 TaskSpec、匹配的原结果及原 Verification；原始 Artifact/Receipt 可以保留原版本，但不能借复用换目标或扩大授权。
4. 按原 Artifact/Hash 契约解析引用，核对所属 Run/任务/源版本；收据必须绑定原宿主目标与实际 refs，不能丢失或跨任务取证。
5. 只读核对签名采集中原 Journal 的提交工具/模型配对、payload Hash、调用 ID、参数及收据一致性。这是离线结果定位的完整性检查，不重新运行 P3/RAG Verifier，不改变它们的 verdict。

没有新增 Scheduler、状态机、账本、数据库字段或恢复入口。新测试文件只使用公开合成契约；本地审计脚本只读取封存与签名结果，输出到新的忽略目录，均拒绝覆盖已有输出。原 `score_case`、REASONS、Gold、评分阈值、Runner/Collector、`src/`、依赖和迁移未变。

本轮文件范围：Scorer 新增 127 行、删除 5 行，集中在共享结果定位与必要的授权/持久证明检查；新增 `tests/test_p7_scorer_versions.py` 的 32 条反例，新增本报告及两份 `p7-scorer-v2-*` 研究记录，AGENTS/evaluation 只补阶段边界和索引。清理的是两处重复且错误的查找，没有额外重构核心业务。工作区原有 SQL NUMERIC 修复和其他未提交文件继续保留，不算本轮新增改动。

## 2. 冻结与历史兼容

| 对象 | SHA256 |
|---|---|
| 首轮 Live Implementation Freeze（保留） | `0094ab595c62b2fadef192728399300855754a97455b19a35d4bb24ffc0ed18f` |
| Scorer v1 原源码 / 私有原件副本 | `1661613be0daaa1b2d63bf73494aa2be38646cd203958851a41dc8045a763270` |
| 原首次 Live summary.json | `295574c6e1a3cc81f41303c2771cb2b32f354a1f7430b6250f6ac0b0841094cd` |
| Scorer v2 源码 | `170af96e860570b51def0004775a994f0d7c9159ecd3be367f0137abe1779363` |
| 本轮离线 Scorer Freeze | `b7aa0acb517271f8424a3421675659faf03bdd6c7c22c56dd1b154023b2a6e46` |

原 152 个冻结文件仅有 Scorer 的工作副本发生获授权变化，其余 151 个 Hash 相同；旧 Scorer 在修改前按原字节归档，可重现原逐 Case 评分。**原 Freeze/Seal 未改；工作副本已不是旧 Freeze，不能再拿原许可启动 Campaign。** 本轮新 Freeze 只允许离线评分，不是新的 Live Implementation Freeze 或许可。

[Scorer v2 Freeze](research/p7-scorer-v2-freeze.json) 包含源码/测试、父 Freeze、原评分、修订结果、逐 Case 差异及审计脚本 Hash。v1/v2 Gold Seal、原 Gold 字节、签名观测、P3 Evidence/Verification、首次 Live 私密资产和原响应均未修改；审计开始前固定的 219 个原始文件逐个核验。

## 3. 同一批 31 条响应的独立离线复评

先用归档 v1 代码逐条重算，结果字段与原 summary 的 31 条记录完全一致；再以 v2 评分。Python 3.11 / 3.13 的复评除观察时间字段外完全相同。

| 路径 | 计划 | 已观测 | v1 正确 | v2 正确 | v2 未通过 | not_run |
|---|---:|---:|---:|---:|---:|---:|
| SQL-only | 20 | 20 | 18 | 18 | 2 | 0 |
| RAG-only | 20 | 11 | 7 | 8 | 3 | 9 |
| SQL+RAG | 20 | 0 | — | — | — | 20 |
| 合计 | 60 | 31 | 25 | 26 | 5 | 29 |

唯一严格评分变化为 **bh2-030：false → true**，修复版本键后正确读到原 unavailable / empty 收据。其他 30 条严格判定不变；未通过仍为 011/017/024/026/031。原 25/31 和修订 26/31 分别留存，不能覆盖成一条“首次成功成绩”。

v2 已观测严格正确率为 SQL 18/20、RAG 8/11；SQL+RAG 无本次观测，率为 null。26/60 只表示完整计划中已核实正确的覆盖下界，不是无偏的完整成功率，也没有减少原 60 条分母。三条已执行宿主拒绝仍按原契约计分，不把它们描述为模型业务成功。

原 RAG 完成汇总 0 修为 **8/11**，不等于业务成功：024 检索完成而业务 partial；030 合法拒答而严格业务契约通过。两种“8”包含的 Case 不同，完整集合和逐 Case 改动在 [结构化对照](research/p7-scorer-v2-results.json) 及本地 [60 行差异 JSONL](../artifacts/p7/scorer-v2-audit/final/case-differences.jsonl)。原数值、引用、召回排序、用量、失败响应和报告都未变化。

原 v1：[首次评分](../artifacts/p7/gate2b-v2/private/campaign-results/business-v2-958ee94411d6a6b4/summary.json)。独立输出：[v1 重现](../artifacts/p7/scorer-v2-audit/final/v1-reproduced.json)、[v2 复评](../artifacts/p7/scorer-v2-audit/final/v2-results.json)、[3.13 对照](../artifacts/p7/scorer-v2-audit/final-py313/v2-results.json)。

## 4. bh2-031：精确上下文与预算根因

仅用原签名 Collector 输出、固定 Prompt/Schema 构造函数及原工具反馈，离线重建三个已发送 RAG 输入；三次 Journal input fingerprint 均逐字匹配，最终未发送视图的 ContextUsage 也完全一致。原件见本地 [私有消息与工具视图](../artifacts/p7/scorer-v2-audit/private-budget-context.json)，公开统计见 [预算分析](../artifacts/p7/scorer-v2-audit/budget-analysis.json)、[补充分类](../artifacts/p7/scorer-v2-audit/budget-supplement.json)。没有重新查询或生成新模型答案。

### 4.1 原账本与失败点

根账本 4 次 / 6,482 Token，RAG 子账本 3 次 / 5,866 Token；差额 616 为 Planner。根上限 8 次 / 18,000，子上限 4 次 / 18,000，pending=0。

最终 9 条消息 + 3 个工具 Schema 的 JSON 为 11,769 UTF-8 字节；原估算 `bytes + 128` 得 11,897，输出预留 1,200，总预留 13,097。根累计需求 `6,482 + 13,097 = 19,579`，子累计需求 `5,866 + 13,097 = 18,963`，两者均超过 18,000。原 BudgetLedger 在调用前拒绝，未生成第五条 provider 请求，没有 unknown-outcome 或重复扣减。

在原 Ledger 的内存副本上按原接口请求同样预留，确实得到 `BUDGET_EXCEEDED`，拒绝前后状态相同；[检查收据](../artifacts/p7/scorer-v2-audit/reservation-check.json) 中数据库查询/写入、模型调用均为 0。

### 4.2 11,897 的具体组成

| 部分 | 原序列化字节 | 解释 |
|---|---:|---|
| System | 1,321 | 固定安全/工具规则及宿主检索目标 |
| 初始用户任务 | 552 | 任务及 RAG Scope/索引版本摘要，不是完整 SQL Schema |
| 三个 assistant 消息 | 3,720 | 搜索、读取、提交决策及 LangChain 消息元数据 |
| search_documents 反馈 | 1,489 | 一个结果 Artifact，含两个授权片段的预览/refs |
| read_context 反馈 | 889 | 有界片段、引用、跨度等元数据 |
| submit_rag_result 错误反馈 | 485 | 原 `EVIDENCE_INSUFFICIENT`，不代表新的来源内容 |
| 一次宿主完成纠正 | 751 | 原 Stop Hook 的纠正与后续提交要求 |
| 消息数组分隔及 JSON 外壳 | 43 | 消息数组 18 + 外壳 25 |
| 工具 Schema | 2,519 | 三个工具，四个视图中均相同 |
| 合计字节 / 估算 Token | 11,769 / 11,897 | 后者加原固定 128 余量 |

不存在逐条完全重复的消息，也没有重复注入整份 Schema。存在正常闭合历史累积和 **59 字已在搜索预览中的片段再次被 read_context 返回**；两个搜索预览正文共 106 字，来源正文并非大量增长。工具反馈包含必要 refs/Hash/跨度，不能为压缩率静默丢掉。

assistant 字段单独剔除的离线字节贡献为 response_metadata 1,698、usage_metadata 473、additional_kwargs 120、id 168；本次 additional_kwargs 只有 refusal，没有第二份原始 tool_calls。说明原字节估算计入了响应元数据，不能把全部 11,897 当作真实供应商输入 Token。

| 已发送 RAG 调用 | 原输入预留估算 | Provider 实际 input | Provider output |
|---|---:|---:|---:|
| 1 | 4,549 | 1,293 | 78 |
| 2 | 7,226 | 1,896 | 149 |
| 3 | 9,335 | 2,317 | 133 |

最终拒绝视图未发送，实际 input Token **未知**；不能按前三次比例外推账单或宣称一定可容纳。以上剔除字段只是根因分解，没有修改估算器或 Provider 协议。

### 4.3 为什么 L1–L4 没有启动

原 ContextManager 按单次窗口/冷却判断压力：最终文本 11,371 字符低于 `16,000 × 0.8 = 12,800`，估算输入加输出 13,097 也低于 `18,000 × 0.8 = 14,400`。没有冷却压缩，也没有 context_compression 事件。Trace 的 model_context=accepted 只证明窗口可容纳，不证明累计预算预留已获准或请求已发送。

此时根/子剩余 Token 分别是 11,518 / 12,134，比所需 13,097 少。**单次窗口压力与剩余累计预算压力没有衔接**是直接工程原因；保守序列化估算、正常历史和一次错误纠正共同促成触顶，不是账本算错。子调用额度只剩一次，L4 摘要加 follow-up 需要两次，不能靠额外摘要绕过预算。

还有独立业务阻断：原 retrieval_goal 将“已经固定的最新快照”标为 unsupported_requirements=true；尽管本次片段 query scores 为 0.59256 / 0.56730，goal scores 为 0.74700 / 0.58658，完成工具仍按原规则拒绝。这与预算失败不是同一个问题。**仅解决预算也不能证明此 Case 会 completed**，原 Gold/Source Pin/Host Policy 本轮不改。

### 4.4 仅供下一版本的开发集 A/B 方案

另建至少 24 条公开合成 dev：覆盖短任务、闭合历史、预览后重复读取、长元数据、显式固定快照/真正开放式最新请求、肯定/否定因果、空召回及注入。不得以本次 60 条结果反复调 Prompt 或阈值；未来正式验证需新封存集或预先冻结的独立对照。

- A：当前估算与窗口触发基线。
- B：只在安全可计算的剩余父子预算压力下尝试既有 L1–L3，保持权威 refs、原始存档、assistant/tool 配对和原子预留。没有足够摘要+后续调用额度就不进入 L4，不释放未知调用费用。
- C（独立变量）：验证与当前锁定 SDK 投影一致、含有明确安全余量的输入估算；先离线验证上界及元数据重复计入，再独立授权小批真实校准，不能直接用字节除以常数代替安全上界。

同模型/数据/源版本/权限/温度/预算/并发下冻结任务顺序与时序，比较完整业务正确性、错误完成/拒绝、权威引用不变量、实际输入/输出/cache、预留误拒绝、摘要/恢复全部费用和时延。不得仅凭压缩率验收；阈值/Prompt/预算/语义守卫的变更必须分开实验。此处没有实施优化或运行 A/B，没有新增付费授权。

## 5. 六个 Bad Cases：影响层和下一版本建议

| Case | 原始证据与根因 | 影响层 / 是否需要产品代码变更 | 下一版本最小行动 |
|---|---|---|---|
| 011 | 原 P3 Evidence `25c07aa2-8ce7-46ab-bd27-6d5a4ca97a14` / Verification `df175deb-2e2b-4415-9b31-3df16e7abb80`：零起始 cohort 的复算 ValueError 被 Repository 折叠为 `data_not_verifiable`；verdict=unavailable，报告沿用该码，Gold 要求 zero_denominator | 确定性复算→Proof→报告原因传递信息丢失；拒算本身正确，不是数值错误。需要后续受限产品修复 | 用可审阅的类型化业务原因传递，未知异常仍 fail-closed；不靠报错文本猜码，不把 generic code 加入所有拒答别名 |
| 017 | Evidence `badce195-a008-48dd-91c1-fbedf4aedb94` / Verification `26fbb0f4-8986-4052-a635-ca416d0d18bd`：重复记录粒度的复算 ValueError 同样折叠为 generic code，verdict=unavailable；Gold 要求 duplicate_record_grain | 同上；重复粒度拒绝正确，严格原因未传递。需要后续产品修复 | 与 011 共用类型化原因契约；重复粒度仍禁止求和，不改 SQL 配方或业务口径 |
| 024 | 原 Scope causal_requested=false、事实 3/3、检索收据完成，但 Report 对问题中否定的“证明”也命中因果正则，额外附 causal_conclusion_not_verified，导致 partial 而非 Gold completed | 报告目标识别的否定范围误判。需要后续产品修复；无需为了这次评分改 Gold | 在可信宿主目标契约中区分“请求证明”与“禁止宣称证明”；事实任务不平白加因果目标，真正因果请求仍必须保持未验证 |
| 026 | 两次英文查询各返回真实 no_matches，工具 Artifact 均为空，最终 unavailable/empty，Gold 可回答；没有捏造引用 | 确认是召回缺失造成错误拒答；不能仅凭日志判定为模型、阈值或跨语言向量的唯一责任。暂不直接改产品 | 原日志未保存阈值以下距离，不能补造分数。新 dev 上对比原问题/同语言/英文改写，控制索引与 0.55 阈值，先定位再决定是否需要查询策略；不默认降低阈值或增加 Reranker |
| 030 | 当前 `1:documents` 为 unavailable，原 empty 收据及配对真实；v1 读取 documents 丢失证据 | 仅 Scorer 版本键缺陷，本轮已修；无 Runtime/P3/权限修改 | v2 离线严格通过，保留 v1 失败。合法拒答不计为检索完成 |
| 031 | 详见第 4 节；保守估算+剩余预算压力未触发压缩。原固定快照要求还被标为 unsupported | 预算触发策略与检索需求解析分别为后续产品候选；账本安全拒绝正常 | 新 dev 分别验证预算压力与固定快照语义，不扩大源授权、不放宽真正“全量/最新”未知范围；本轮不实现、不补跑 |

原 `semantics/recompute.py` 产生 011/017 的领域 ValueError，`semantics/repository.py::proof` 捕获后生成通用 MissingRequirement；六层记录是 recomputation not_applicable，其余层通过，不能写成 P3 rejected 或通过。`reporting/service.py::build` 的关键词正则解释 024；`rag/storage.py::search` 的 scope/min_score 过滤与原 no_matches 解释 026 的可观察边界。完整 Hash、字段、查询指纹及源码依据保存在本地 [六例证据摘要](../artifacts/p7/scorer-v2-audit/bad-case-evidence.json)，原件链接不会泄露数据库凭据或公开正文。

## 6. 实际验证与命令

| 验证 | 实际结果 |
|---|---|
| 最终 32 条公开反例在归档 v1 上运行 | 32 failed，真实缺陷/守卫反例；没有改写为 xfail |
| 最终源码 Python 3.11：新反例 + 原 Scorer/Campaign/Gate2B 契约 | 82 passed（含 32 条新测试） |
| 最终源码 Python 3.13：同一集合 | 82 passed |
| 原始 31 条签名观测，v1 重现 | 每条结果字段与原 summary 一致，仍 25/6 |
| 同一观测，Scorer v2 双版本离线复评 | 26/5，差异仅 030；未运行仍 29，两版本结果一致 |
| 原 219 文件 / 原 Seal / 原 Freeze / Gold / 业务源码 | 完整性校验；仅获授权 Scorer 工作副本与旧 Freeze 不同，其余 151 文件一致 |
| 原 Ledger 内存副本定向预留 | 原错误复现，账本无变化、pending=0 |

新测试覆盖正常版本键、当前版本新执行、显式复用、多个同名版本、旧 Plan 改目标、复用来源/Verification 缺失或失败、错误 Run/Task/Worker/版本、Artifact 缺失/Hash、收据/目标/调用配对、伪造 succeeded 和“检索完成≠业务成功”。测试编写初期的 fixture 缺默认字段/调用键等调试失败也保留在目录内；这些日志不作为业务缺陷证据，以最终 `frozen-tests-v1-red-py311` 的 32 项失败为准。

实际命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_p7_scorer_versions.py tests/test_p7_campaign.py tests/test_p7_business_v2.py tests/test_p7_gate2b.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_p7_scorer_versions.py tests/test_p7_campaign.py tests/test_p7_business_v2.py tests/test_p7_gate2b.py -q
.venv\Scripts\python.exe artifacts/p7/scorer-v2-audit/offline-rescore.py --output <新的独立输出目录>
.venv-313\Scripts\python.exe artifacts/p7/scorer-v2-audit/offline-rescore.py --output <另一个新的独立输出目录>
```

离线脚本和源记录都在本机忽略目录，不能将未上传的私有数据说成公开可下载；输出目录必须不存在。不要运行原 Campaign 派发命令。测试日志/JUnit：[3.11](../artifacts/p7/scorer-v2-audit/final-regression-py311.xml)、[3.13](../artifacts/p7/scorer-v2-audit/final-regression-py313.xml)、[v1 红例](../artifacts/p7/scorer-v2-audit/frozen-tests-v1-red-py311.xml)；[复评脚本](../artifacts/p7/scorer-v2-audit/offline-rescore.py) 的 Hash 在新 Freeze。

本轮仅做适用 Scorer/契约回归，不重复运行整个产品 pytest、浏览器或新 PG 集成，也不伪称它们已再次通过。Ruff、Diff、JSON、引用及最终冻结/隐私校验另见本地 [最终检查](../artifacts/p7/scorer-v2-audit/final-validation.json)。v2.4/v2.5 用户规划文件保留原 Hash，格式检查排除 v2.5 已有代码块格式问题。

实际静态结果：`ruff check .` 通过；`ruff format --check --extend-exclude docs/codex-prompts-v2.5.md .` 为 298 files already formatted；`git diff --check` 通过。未运行新的 GitHub CI，没有暂存或提交。

## 7. 停止与剩余风险

Scorer 修复与本次离线审计完成；五个严格失败、未观测的 SQL+RAG、其余 29 条和原预算停止都保留。既有 Holdout 已被观测，后续产品优化不能在这批结果上反复刷分。尚无 031 未发送请求的真实 Token、026 阈值以下原始排名或新的完整业务成功率；不编造补齐。

预算感知压缩、领域原因传递、否定因果和固定快照语义都只是下一版本建议，未在本轮实施。未调用 DeepSeek、未补跑、未改变权限或业务定义、未进入 Gate 3、未提交/推送。
