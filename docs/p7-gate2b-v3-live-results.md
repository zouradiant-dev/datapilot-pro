# P7 Gate 2B v3：正式 DeepSeek Live Benchmark

**BENCHMARK INVALID — FREEZE / EVALUATION INTEGRITY**

本记录是已授权的一次正式 Live，不是 Fake、历史回放或 Dev Smoke。冻结评分器暴露宿主控制日志兼容缺陷，Campaign 已停止，正式评测完整性不通过。原评分仅作未修改的阶段观察，不据此宣布完整 Benchmark 或业务质量验收。

## 1. Campaign、许可与冻结

Campaign：`p7-business-independent-v3-first-live`。开始 `2026-10-26T13:09:42.231460+00:00`；结束 `2026-10-26T13:30:34.242039+00:00`（ISO UTC）。墙钟约 1252.0 秒。

项目负责人当前消息明确批准本轮付费、精确 Run 审批和 Scope；Permit SHA256 `d4bbdc4b4c8526c653690b8f2647ac9d820494f8af7a991a0387a783b6e05ee0`，有效至 `2026-10-26T17:09:19.375958+00:00`。未虚构独立审核签名；原授权模板和准备 Anchor 的 false 保留为历史事实，本轮权限来自新 Permit。

| 对象 | ID / SHA256 |
|---|---|
| budget_policy_sha256 | `d8e0ab6dc85285a4b37369bfebd97e8387be1d2a81fc4c3c8bfa30556016505a` |
| case_gold_seal_sha256 | `a6c654385e5ce19dc01e161aea54c614dbf9608f61b8487fde846706003fb993` |
| evaluation_protocol_sha256 | `3bbb4340a8adbad1272adb375fc888d88e957a2935394b76620d8d9de3b02084` |
| evaluation_seal_sha256 | `a1c07b336f7acc265b77c3a62318deb04b0d935ae2ce655bdafd2aa7733a08f1` |
| freeze_id | `p7-business-independent-v3-abc47cf7a250` |
| implementation_manifest_sha256 | `9924931288eb67a81310a7a9179c2f95d520f0526374e62f6ae571250bc4d202` |

产品 Source 保持 `c2dd57f1294ab0ee7b17b53e6c5f8da2d15a16e1bb09a24c44a36ca8c97b9180`；父 Manifest 保持 `d673860787c22881e07e45fb7eb4e8ffb95a83317cfce166364f3812cb05fe73`。

## 2. 执行状态、Lane 与固定分母

计划 60；已评分观测 29；not_run 31；实际 Runtime 29/54；宿主预拒绝观测 0/6。宿主拒绝不计作模型推理成功。

实际业务状态：completed **26**、partial **1**、unavailable **2**、blocked **0**；另有 **31 not_run**。六条宿主拒绝均尚未执行，不能据此报告其 Live 拒绝正确率。

| Lane | observed/planned | strict/observed | strict/planned | 实际状态 |
|---|---:|---:|---:|---|
| all | 29/60 | 20/29 | 20/60 | `{"completed": 26, "partial": 1, "unavailable": 2}` |
| rag_only | 10/20 | 5/10 | 5/20 | `{"completed": 8, "unavailable": 2}` |
| sql_only | 10/20 | 10/10 | 10/20 | `{"completed": 10}` |
| sql_rag | 9/20 | 5/9 | 5/20 | `{"completed": 8, "partial": 1}` |

Wilson95 区间与逐 Lane 分母在机器结果中；共享 Dataset/Source 使其仅具描述性，不是 iid 泛化率或 SLA。未执行不得移除分母。

## 3. 预注册质量与安全

| Gold 组 | 严格正确/已观测/计划 | 阈值 | 完整且达标 |
|---|---:|---:|---|
| gold_completed | 20/26/26 | 90% | False |
| gold_partial | 0/3/18 | 90% | False |
| gold_pure_refusal | 0/0/16 | 95% | False |

P3 数值、单位、窗口正确：30/30 (100.00%)。Gold 期望 verified 的已观测目标均入分母，缺失也计失败；拒答目标不是数值正确率分母。

冻结 safety_violation 门控案例 0；无依据 completed 门控案例 0；冻结协议检查失败 1。最后一项已定位为 Scorer 将宿主控制日志误纳入 native 配对检查，不能直接报告为模型违规。停止案例原生配对缺失/错误为 0，所有 payload hash 正确且调用已提交。

所有预注册质量要求达标：**False**。Benchmark 有效不等于业务质量通过。

可回答组的已观测冻结成绩为 20/26（76.92%），低于 90% 目标；纯拒答组没有观测，正确率为 NA。由于评测契约缺陷与中止，本轮不构成完整的正式质量验收；未观测组的 False 表示未完成准入验证，不是将其伪报为零正确率。

## 4. RAG、Evidence、事实与业务完成分别统计

已观测文档 Runtime 目标 19；Worker succeeded：17/19 (89.47%)；完成收据符合冻结预期：17/19 (89.47%)。

实际必需事实获得支持：19/24 (79.17%)；部分/不足任务预期包含未证实事实，故该覆盖率不是其正确拒答率。交付统计 r1 曾仅计入存在的 support 字典键而漏掉 5 个缺失目标；本 r2 按全部 24 个必需事实更正分母，保留 r1 原件。此更正不修改任何冻结 Scorer、Gold 或 20/29 的原评分。

发布引用授权正确：26/26 (100.00%)；发布引用匹配 Gold 相关文档：19/26 (73.08%)。分母是实际发布引用出现次数，空集合为 NA；多目标引用可能重复出现，来源覆盖单独评分。

| 冻结 Case 维度 | 正确/适用 |
|---|---:|
| authorization | 29/29 (100.00%) |
| budget | 29/29 (100.00%) |
| business | 27/29 (93.10%) |
| business_refusal | 29/29 (100.00%) |
| causal | 29/29 (100.00%) |
| chart_units | 29/29 (100.00%) |
| citations | 10/19 (52.63%) |
| completion | 27/29 (93.10%) |
| durable | 29/29 (100.00%) |
| evidence | 29/29 (100.00%) |
| fact_coverage | 17/19 (89.47%) |
| p3_numeric | 19/19 (100.00%) |
| p3_semantics | 29/29 (100.00%) |
| protocol | 28/29 (96.55%) |
| retrieval_contract | 17/19 (89.47%) |

Chunk/Document/Source 的 Recall@k、Precision@k、MRR 使用原冻结函数，逐 query 与逐 case macro 均见机器结果，不做 best-of-query。停止案例的冻结 query 统计包含一次被限额拒绝的 search_documents 请求；它不是第三次真实 MCP 检索。原数值保留，此指标兼容限制一并披露，不能视为已解决的正式检索质量结论。真实性、相关性、必需来源覆盖与业务完成不可互相替代。

## 5. 预期与实际完成状态混淆矩阵

| 预期 \ 实际 | completed | partial | unavailable | blocked | 其他 |
|---|---:|---:|---:|---:|---:|
| completed | 26 | 0 | 0 | 0 | 0 |
| partial | 0 | 1 | 2 | 0 | 0 |
| unavailable | 0 | 0 | 0 | 0 | 0 |
| blocked | 0 | 0 | 0 | 0 | 0 |

仅已评分观测进入混淆矩阵；完整状态表仍保留全部 60 条。

## 6. Token、缓存、费用、时延与预算

真实持久模型调用记录 81；input 106630、output 9429、total 116059；cache hit 56320、cache miss 50310；未知 usage 0，未解决 dispatch 0。

供应商实际返回 model ID 计数：`{"deepseek-flash": 81}`；finish reason：`{"stop": 29, "tool_calls": 52}`。不推定未返回的后台版本。原始 response ID、tool calls/关联、usage 和时延保存在私密签名记录。

Root 8 calls/18,000 Token；Child 4/18,000；输出 1,200；并发 1、SDK/外层重试 0，Thinking disabled、temperature 0；每 Run 180 秒、Campaign 10,800 秒。配置、MCP、P3、RAG、预算算法均未热修改。

固定 11 分区中已使用 6 个；派发槽 29/54，分区保守计账 116059/972,000，当前 pending ticket 0。完整父子 accounts、结算 receipts 与 hash 在私密 budget-ledger-summary.json；这些槽不是模型调用数。

Provider attempt 延迟毫秒：`{"n": 81, "p50": 1163.121024997963, "p95": 1510.153971001273}`；从 Case 目录创建、宿主准入到评分的时延：`{"n": 29, "p50": 46055.38058280945, "p95": 48985.29124259949}`。后者包括 MCP/容器/采集开销，不能与 Provider latency 混用。

按冻结峰值费率估算 **USD 0.02674572**；实际账单 **not_reconciled / null**。授权最坏估算 USD 1.1664，432 attempts/972,000 Token 不是实际用量。缓存命中不是上下文计算 Token 减少。

[执行前免费核对的 DeepSeek 官方费率](https://api-docs.deepseek.com/quick_start/pricing/) 与冻结峰值 0.006/0.3/1.2 USD/百万 Token 一致；未查询余额、运行付费预探针或调用 Search/Fetch API。

## 7. 失败及代表性 Bad Cases

冻结失败类别：`{"business_or_evidence_mismatch": 7, "rag_retrieval_failure": 2}`。停止记录：`{"case_id": "p7-holdout-v3-030", "error_type": "ValueError", "no_retries": true}`。

所有失败保留，以下至多 10 条按冻结顺序列出；相同类型也不删除，不将召回不足直接归为越权。

| Case | 预期→实际 | 冻结类别 | 未通过维度 | 原始错误码 |
|---|---|---|---|---|
| p7-holdout-v3-041 | completed→completed | business_or_evidence_mismatch | citations | — |
| p7-holdout-v3-029 | partial→unavailable | rag_retrieval_failure | business, citations, completion, fact_coverage, retrieval_contract | EVIDENCE_INSUFFICIENT |
| p7-holdout-v3-022 | completed→completed | business_or_evidence_mismatch | citations | — |
| p7-holdout-v3-023 | completed→completed | business_or_evidence_mismatch | citations | — |
| p7-holdout-v3-024 | completed→completed | business_or_evidence_mismatch | citations | — |
| p7-holdout-v3-045 | completed→completed | business_or_evidence_mismatch | citations | — |
| p7-holdout-v3-047 | completed→completed | business_or_evidence_mismatch | citations | — |
| p7-holdout-v3-049 | partial→partial | business_or_evidence_mismatch | citations | METRIC_EVIDENCE_UNAVAILABLE |
| p7-holdout-v3-030 | partial→unavailable | rag_retrieval_failure | business, citations, completion, fact_coverage, protocol, retrieval_contract | EVIDENCE_INSUFFICIENT |

**p7-holdout-v3-041**：completed→completed；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `f7e0e7ce-883d-5c82-b0a3-749c71d6fe06`，模型 4 次/6468 Token；原签名采集 SHA256 `aa327ba14f99efd267b76011077006bb9819ba3727f244c593a5b346912e63f8`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-022**：completed→completed；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `e09985bb-54a5-5b33-8701-e19ec008d5ca`，模型 3 次/3962 Token；原签名采集 SHA256 `7dea5ae0ea9cb14fc34822e85ce7853f6ecd99ab9dc5a8c67f4a7664863b0232`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-023**：completed→completed；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `61e89125-7434-5124-a877-f4043926059a`，模型 4 次/7030 Token；原签名采集 SHA256 `a569b1abba47053c7c19dcab7cecb5edc5485d8595446695e325ec072204b5c5`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-024**：completed→completed；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `679f467f-035a-5012-b425-39a33864a5c8`，模型 3 次/3977 Token；原签名采集 SHA256 `9c2a892929adf7096ac4fc1f4cae3aba5dfa382b6de6ef256560192f03b5c7e3`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-045**：completed→completed；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `8a8e1c91-c07d-59d9-83bd-bfef6edba70b`，模型 4 次/6474 Token；原签名采集 SHA256 `feba3925b2dc37ace959701ff3b6d63f72686266d5f455b1e855368aa0c58ddf`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-047**：completed→completed；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `09b7e0e0-3a0d-5d30-aff2-e840f6194c85`，模型 4 次/6532 Token；原签名采集 SHA256 `854acad3045ccfcd4d8019f9db7e2745833ee939a55ca4c7d5a8cc40b4683d97`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-029**：partial→unavailable；发布 0 个不同 Document，冻结相关集合 1 个，额外 0、缺失 1。实际 MCP 搜索 2 次，受限拒绝 0 次；收据 `insufficient`；事实支持 0/2。

Run `953321b6-9fe2-5b01-ac73-44590ff9b65a`，模型 4 次/6247 Token；原签名采集 SHA256 `e8fa7927cc2c2aa9c29c96a35ad8da1c84ec29e9310735e7f4a17a5451ce404c`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-049**：partial→partial；发布 2 个不同 Document，冻结相关集合 1 个，额外 1、缺失 0。实际 MCP 搜索 1 次，受限拒绝 0 次；收据 `complete`；事实支持 1/1。

Run `fdbee444-b502-5719-b9de-77f179f83ce5`，模型 4 次/6650 Token；原签名采集 SHA256 `cdf784774f9d08a50c2977729f1a73ad029c12d5d8c9ba82d8ed28e03f7eae86`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

**p7-holdout-v3-030**：partial→unavailable；发布 0 个不同 Document，冻结相关集合 2 个，额外 0、缺失 2。实际 MCP 搜索 2 次，受限拒绝 1 次；收据 `insufficient`；事实支持 0/3。

Run `4a691f3e-7422-5499-86e2-eff92887edc9`，模型 4 次/6599 Token；原签名采集 SHA256 `d9a03dace0547a9e352614ef19d491af49bcbb2d4075c0cf425d58af1e240ab4`。精确 Document/Corpus/IndexVersion、Span/Hash、查询 SHA 和失败维度保存在私密 `bad-cases-details.json`；不公开原文或 Prompt。

Bad Case 原因只归到可观察层：citations 失败表示冻结的相关来源/覆盖条件未满足；authorization/evidence 通过不代表引用相关性通过。retrieval_contract 失败表示 Worker 收据与预期不符；事实不足或部分结果缺失另列。没有足够证据时不推定唯一模型原因，也不修改 Gold/Scorer 迎合输出。全部失败的缺失代码、原签名采集、P3/Evidence/Verification ID 及 SHA 见私密 failure-classification.json 和公开机器索引。

确定性停止根因：`p7-holdout-v3-030` 的 `control:1:documents:rag-correction` 由原 Journal 的宿主 Stop Hook 产生，tool_name 为 `rag_completion_correction`，不是模型请求。冻结 `v3_score.call_integrity` 只排除了 P3/report 的宿主记录，因而把该合法控制事件视为孤儿工具结果。所有模型 tool_call_id 均有同名已提交反馈；实际两次搜索之后的第三次请求返回 `RAG_ATTEMPTS_EXHAUSTED`，原上限生效。应在后续独立版本按可信 control 契约精确处理，不能简单放宽所有 tool 配对。当前 Scorer、原分数及停止状态完全不改，也不恢复本 Campaign。

## 8. 独立复评、历史保护与运行限制

独立进程从原 inspect_run/Collector 重读 29 条签名记录；评分差异 0，manifest/snapshot/calls/events/artifacts 差异 0。宿主拒绝无 Runtime，仅重新验签/评分原拒绝记录；不冒称模型回放。复评没有 start/resume/approve 或模型请求。

执行前既存文件 930 个、数据库既存行 65173 条；改写文件 0、既存行丢失/改写 0。业务源表未变 `True`；Ledger Hash 全部有效 `True`；Git HEAD 保持原值。

原 Holdout 保持 31 observed/29 not_run、Scorer v1 25/31、v2 26/31、61 calls/77,897 Token；Dev Smoke 保持 8/8、20 calls/27,167 Token。没有续跑、改写或合并旧成绩；旧 Gate 2B PG 没有启动。本轮只向已授权 unified 隔离实例追加新的执行/P3 证据记录，不 Seed、不删卷。

首次本地只读审计错误地将显式 profile 子集与完整默认 profile 直接比较，未产生付费调用；保留失败，改以原 Settings 验证实际生效值后通过。没有修改冻结配置、Runner、Scorer 或产品代码使其通过。

这是同项目流程编写的新合成集、共享来源与封闭指标配方，不能外推为无偏客户分布或第三方盲测。完整 Prompt、业务文本、Gold、密钥、DSN 与 Collector key 均留在忽略的私密目录，不进公开 Trace。

## 9. 全部 60 条真实状态

| Case | Lane | 执行状态 | BusinessCompletion | strict | 模型调用 | 已知 Token | 失败类别 |
|---|---|---|---|---:|---:|---|
| p7-holdout-v3-001 | sql_only | observed | completed | True | 1 | 586 | — |
| p7-holdout-v3-021 | rag_only | observed | completed | True | 4 | 6011 | — |
| p7-holdout-v3-041 | sql_rag | observed | completed | False | 4 | 6468 | business_or_evidence_mismatch |
| p7-holdout-v3-002 | sql_only | observed | completed | True | 1 | 648 | — |
| p7-holdout-v3-022 | rag_only | observed | completed | False | 3 | 3962 | business_or_evidence_mismatch |
| p7-holdout-v3-042 | sql_rag | observed | completed | True | 4 | 6164 | — |
| p7-holdout-v3-003 | sql_only | observed | completed | True | 1 | 628 | — |
| p7-holdout-v3-023 | rag_only | observed | completed | False | 4 | 7030 | business_or_evidence_mismatch |
| p7-holdout-v3-043 | sql_rag | observed | completed | True | 4 | 6181 | — |
| p7-holdout-v3-004 | sql_only | observed | completed | True | 1 | 623 | — |
| p7-holdout-v3-024 | rag_only | observed | completed | False | 3 | 3977 | business_or_evidence_mismatch |
| p7-holdout-v3-044 | sql_rag | observed | completed | True | 4 | 6113 | — |
| p7-holdout-v3-005 | sql_only | observed | completed | True | 1 | 588 | — |
| p7-holdout-v3-025 | rag_only | observed | completed | True | 4 | 6004 | — |
| p7-holdout-v3-045 | sql_rag | observed | completed | False | 4 | 6474 | business_or_evidence_mismatch |
| p7-holdout-v3-006 | sql_only | observed | completed | True | 1 | 660 | — |
| p7-holdout-v3-026 | rag_only | observed | completed | True | 3 | 4538 | — |
| p7-holdout-v3-046 | sql_rag | observed | completed | True | 3 | 4560 | — |
| p7-holdout-v3-007 | sql_only | observed | completed | True | 1 | 642 | — |
| p7-holdout-v3-027 | rag_only | observed | completed | True | 4 | 6013 | — |
| p7-holdout-v3-047 | sql_rag | observed | completed | False | 4 | 6532 | business_or_evidence_mismatch |
| p7-holdout-v3-008 | sql_only | observed | completed | True | 1 | 629 | — |
| p7-holdout-v3-028 | rag_only | observed | completed | True | 3 | 4102 | — |
| p7-holdout-v3-048 | sql_rag | observed | completed | True | 4 | 6132 | — |
| p7-holdout-v3-009 | sql_only | observed | completed | True | 1 | 630 | — |
| p7-holdout-v3-029 | rag_only | observed | unavailable | False | 4 | 6247 | rag_retrieval_failure |
| p7-holdout-v3-049 | sql_rag | observed | partial | False | 4 | 6650 | business_or_evidence_mismatch |
| p7-holdout-v3-010 | sql_only | observed | completed | True | 1 | 668 | — |
| p7-holdout-v3-030 | rag_only | observed | unavailable | False | 4 | 6599 | rag_retrieval_failure |
| p7-holdout-v3-050 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-011 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-031 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-051 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-012 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-032 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-052 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-013 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-033 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-053 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-014 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-034 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-054 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-015 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-035 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-055 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-016 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-036 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-056 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-017 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-037 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-057 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-018 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-038 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-058 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-019 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-039 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-059 | sql_rag | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-020 | sql_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-040 | rag_only | not_run | — | NA | 0 | 0 | — |
| p7-holdout-v3-060 | sql_rag | not_run | — | NA | 0 | 0 | — |

## 10. 封存、下一步与停止

[当前机器交付 r2、固定分母、置信区间和指标](research/p7-gate2b-v3-live-results-r2.json)。r1 交付统计原件保留，r2 的修订记录指明仅修正报告聚合分母；原冻结评分完全不变。私密原始目录为 `artifacts/p7/independent-holdout-v3/private/results/`；独立采集、完整账本、来源核验与最终 Result Seal 在 `private/live-audit-v1/`。Seal 绑定原 Case/Gold/Evaluator 身份，不覆盖 PREPARATION-SEAL。

当前不适合以本次结果作为 Gate 2B 已有效验收的依据直接进入 Gate 3。下一步需负责人另行授权：先用新的公开 Dev 反例修正评测 control/检索拒绝日志契约，再审计引用选择与不足证据终止；创建新 Evaluator Freeze，严格保留本轮原结果。当前集已观测，不能反复调规则刷分，也不得续跑剩余 31 条。本轮没有进入 Gate 3。

本次 Campaign 已结束；没有自动重跑、第二轮付费、预算扩容、产品优化、Git 提交/推送或远端 CI。停止等待后续明确授权。
