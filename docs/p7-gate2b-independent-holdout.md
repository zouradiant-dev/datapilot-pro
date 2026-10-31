# P7 Gate 2B：新独立合成业务 Holdout v3

结论：**READY FOR SEPARATELY AUTHORIZED GATE 2B LIVE**。本轮只完成非付费准备。正式业务评测 **0 observed / 60 planned，60 not_run**；不报告零观测成功率，不启动 DeepSeek、余额检查、旧 Campaign、Gate 3 或远端 CI。

本集合由同一项目开发流程使用 Codex 编写和技术审阅，属于**相对既有评测内容新建的合成 Holdout**，不是第三方盲编、真实客户分布或无偏样本，也无法证明供应商训练数据与业务模式完全独立。没有虚构人工逐条阅读或第三方签名。

## 1. 已冻结的组成

| Lane | completed | partial | unavailable | blocked | 合计 |
|---|---:|---:|---:|---:|---:|
| SQL-only | 10 | 5 | 3 | 2 | 20 |
| RAG-only | 8 | 5 | 5 | 2 | 20 |
| SQL+RAG | 8 | 8 | 2 | 2 | 20 |
| 全部 | **26** | **18** | **10** | **6** | **60** |

编号为 `p7-holdout-v3-001` 至 `p7-holdout-v3-060`。执行顺序三 Lane 交错：001、021、041、002、022、042，依此类推；不采用先完成全部 SQL 才接触组合任务的排序。6 条预执行拒绝仍属于各自 Lane、保留在 60 分母内；它们不是 Agent 成功推理。其余 54 条具有 Runtime 配置。

| 范围 | 主要覆盖 | 边界与有限终止 |
|---|---|---|
| SQL-only | 发票粒度与分期收款、客户/合同双队列、换套餐、功能版本过滤、闰日与右开窗口、高精度金额、多实体指标 | MRR 未支持、EUR 不换汇、不完整历史、未确认金额单位、NULL、重复 ID、零分母、越权和不存在版本 |
| RAG-only | 单文档事实、同义表达、英文来源、至少两份独立来源、冲突资料、旧/新版、合法引述 | 部分事实无证明、相关背景不足、来源数量不足、未授权索引/Document、空授权来源、全量/共同快照未支持、因果未证明、攻击文本 |
| SQL+RAG | 已验证收入与核算政策、使用量与计量说明、合同指标与续订规则、多指标与多文档 | 保留合法数值与缺证部分、未验证指标不能被文档补证、未授权来源使宿主拒绝、因果/快照/来源数量不足 |

任务不是 60 个日期替换版本。各题独立指定原始问题、业务对象、预期状态、单位/窗口、权限与拒答条件；仍有共同的 P3 公式和安全原语，不能把“新问题”解释成“60 种全新算法”。资源耗尽/未知用量的故障契约由额外协议探针验收，不把故意故障探针混入这 60 条业务成绩。

## 2. 数据、文档与独立性

固定 Seed **730213**，新增澄岳合成 SaaS 数据，主要业务期为 2032 年闰年窗口；另有独立的 2033 年协议探针，不计正式分母。业务快照包含 customers、subscriptions、invoices、payments、refunds、plans、usage_events，多客户、多合同、分期、退款/部分退款、不同状态、币种、空值和数据质量变体。

通过原受限 Ingestion Service 与 Schema Confirm 物化 8 个 Dataset；使用既有 Registry 接口追加合成评测的映射/指标定义。`future` 采用显式 DATE 确认后的 v2，其余绑定 v1；旧版本保留。CSV 与 XLSX 均经真实解析和 PostgreSQL 导入。没有新增生产 Schema、迁移、权限、业务配方或指标类型。

| Dataset | ID | 冻结版本 |
|---|---|---:|
| master | `b3d7cd4a-9ea0-50ce-96fa-d17c02ded2d7` | 1 |
| duplicate | `5787d433-44ab-5582-a571-45aa9b08d4c0` | 1 |
| null_amount | `da5f8705-f975-5185-9eef-2e75e49854f6` | 1 |
| future | `75135051-a537-54a4-b834-f88786512bf4` | **2** |
| incomplete_history | `1a30d8aa-cf4d-5d71-ae86-a857708038c9` | 1 |
| unconfirmed_unit | `3270e3b4-fb20-5749-a7d5-60a2ea12fb09` | 1 |
| major | `9d1dae50-840a-5de7-ad78-c0f13416711a` | 1 |
| csv_payments | `6a41347d-1072-56c6-a87a-3b52661d35e4` | 1 |

字段、Source SHA、Semantic/Metric 版本与定义 SHA、各物理表 MCP 完整小表指纹，都在私密封存 `pins.json`，不靠当前版本指针或表名猜测。合成变体用于各自已声明口径；高精度账本不等同于整数分收款核销，现金流、净退款收入、任意分群/计划收入均未被本阶段实现或宣称验证。跨表关系与粒度的正向核对针对 master，不能外推成通用自然语言 JOIN 分析能力。

真实本地 BGE 摄取产生 **9 个 IndexVersion、14 个 Source/Document、14 个 Chunk**；保全规则甲/乙版共用一个 Corpus 并保留两个不可变索引版本，因此实际 Corpus 数为 8。其他主题包括凭据撤回、核算与赠送额度、事件计量与合同队列、事故与观察记录、相互冲突的保全条款、英文隔离文档及不可信攻击示例。

Embedding 仍为固定 `BAAI/bge-small-zh-v1.5/Qdrant-onnx`，revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`、512 维；本地 ONNX/tokenizer 的原 SHA、192/32 chunker、`pg-cosine-exact-1`、0.55 阈值、Top-k 默认 3/允许 1–5、每 Worker 最多两次搜索不变。没有接入远程 Embedding、Reranker 或原问优先优化。

独立性检查覆盖 **236 条既有输入**：50 业务 dev、59 意图 dev、59 已使用意图 Holdout、60 历史业务 Holdout、8 已观测 Smoke。精确问题、数字归一化、额外名称/日历归一化重合均为 **0**，三字符 shingle Jaccard ≥0.8 的近重复警告 **0**，来源文件字节 SHA 重合 **0**。只提取旧输入/来源做比较，没有利用旧答案或真实模型输出调候选。检查与剩余同源风险见机器 Manifest。

## 3. Gold、Oracle 与业务边界

数值先由独立源数据 Decimal 实现生成，再经真实 scoped MCP 的独立 PostgreSQL SQL 核对，**43 项可计算目标对照通过**。另以真实 JOIN 核验发票到客户、合同关联及支付/退款无孤儿引用，共 4 项。Oracle 不导入产品 P3 配方/复算代码，不从 Agent 结果反推答案。

先固定数值/拒答后，再执行 **34 项去重的原确定性 P3 兼容验证**，保存新增 Evidence/Verification 和精确原因。它们是准备检查，不是正式 Agent Runtime、DeepSeek 回答或 Holdout 得分。原六层业务 Verifier、SQL 配方、日期右开、Decimal、单位/空值/粒度规则未修改；源数据不足仍明确 unavailable，不能猜值或换汇。

文档 Gold 来自原件、固定版本与精确 literal/span/hash。已证明事实使用宿主 DocumentFact；无证明的必需事实保持空证明。相关 Source/Document/Chunk 标签区别于授权集合，多个同源片段不算多个来源。组合任务保留完整原始问题，并另写可信的文档子目标，不把 SQL 全局问题或缺失合同历史误当成文档检索需求；这是新输入契约设计，不是对生产 Prompt 的修改。

分别冻结并评分：

1. Retrieval Completion：30 个正常 complete 目标、5 个来源/能力不足目标、1 个无来源目标；其余不适用。
2. Required Fact Coverage：逐个必需事实及缺失代码，只有原件与宿主证明匹配才能通过。
3. BusinessCompletion：严格等于预先规定的 completed/partial/unavailable/blocked，并保留已验证部分。

因果问题均没有可识别因果效应的可靠资料，正确结果保留未证实结论。未知先后优先级、MRR、净现金流、未批准汇率、最新/共同快照均不暗自补定义。人工开放式裁决本包不作为自动得分捷径；若未来发现确定性契约不能裁决，应标记需裁决/评测异常并保留原记录，不能临场改 Gold。

## 4. Scorer、Runner 与统计协议

复用原签名 Collector、`inspect_run`、P3/RAG 验证、版本化 TaskResult/Artifact 引用、真实 PG lease、BudgetLedger/DurableLedger。新 `evaluation/p7_v3/` 只是本集合的 DTO、作者工具、启动/评分/协议适配及测试，未新增 Agent Scheduler、恢复引擎、账本或模型入口。放在旧 261 文件闭包之外，以保留已完成 Smoke Freeze；新适配器自身单独冻结。

10 类检查为业务正确、P3 数值、Evidence、Citation/Source、事实覆盖、授权、工具关联、完成状态、预算与 Durable 完整性。区分证据真实性与期望 verdict/业务正确性，避免把普通召回错误当越权；同时拒绝替换原 P3 Bridge、错误单位/版本/Verification ID、伪造 succeeded、缺收据、错误 SHA 和缺证 completed。原文事实支持是文档的精确摘取，不能要求其文本等于整个 Chunk。

Scorer 独立进程读取 Gold。候选容器只得到冻结产品源码、最小 worker/gate、原 Collector 和经宿主批准的任务配置；不挂载 Gold、作者数据/答案、Scorer、Oracle、签名 key、Git、`.env` 或 Docker socket。完整题目及预期标签也已从公开作者代码移入私密作者包。授权来自宿主，文档/摘要/模型输出不能扩权。

选择协议 **B**：已确认、无安全异常的普通业务失败保留并继续，以取得完整 Lane 观测；安全/权限/证据完整性、预算、Provider 严重错误、未知结果、身份/版本漂移、TTL、用户 STOP 或超时立即停止。相比首次 strict failure 即停，B 不让一个普通错误系统性遮蔽后续 SQL+RAG；它不允许重试失败案例、清零账本或继续未知调用。

始终报告 observed/planned、strict/observed、strict/planned 与全部 not_run；未运行不能移除。26 个 Gold completed、18 个 partial、16 个纯拒绝分别统计。适用性 NA 不进维度分母，零观测不输出百分比；RAG Chunk/Document/Source 的 per-query 排名与 per-case macro 分开，不能 best-of-query。共享数据/文档使独立同分布假设不成立，Wilson 95% 区间仅作描述。

沿用原目标：可回答任务正确率 ≥90%、纯拒答 ≥95%；本包 partial 正确保留结果目标 ≥90%；安全违规、无依据完成目标为 0，数值/引用准确目标 100%。阈值预注册，不按模型响应改动。故障类别明确分开，不能把 P3、权限、预算、检索、Provider、恢复冲突统一算模型推理。

## 5. Freeze 身份

| 对象 | SHA256 / ID |
|---|---|
| 新 Freeze | `p7-business-independent-v3-abc47cf7a250` |
| Implementation Manifest | `9924931288eb67a81310a7a9179c2f95d520f0526374e62f6ae571250bc4d202` |
| Case/Gold Seal | `a6c654385e5ce19dc01e161aea54c614dbf9608f61b8487fde846706003fb993` |
| Evaluation Protocol | `3bbb4340a8adbad1272adb375fc888d88e957a2935394b76620d8d9de3b02084` |
| Evaluator Seal | `a1c07b336f7acc265b77c3a62318deb04b0d935ae2ce655bdafd2aa7733a08f1` |
| Budget/Stop Policy | `d8e0ab6dc85285a4b37369bfebd97e8387be1d2a81fc4c3c8bfa30556016505a` |
| 复用产品 Source | `c2dd57f1294ab0ee7b17b53e6c5f8da2d15a16e1bb09a24c44a36ca8c97b9180` |
| Smoke 父 Manifest | `d673860787c22881e07e45fb7eb4e8ffb95a83317cfce166364f3812cb05fe73` |

层次为 Data Seal → Protocol/Budget → Evaluator → Implementation → Anchor，所有自对象哈希均排除自身。启动 config 的 base hash 排除后加的授权 binding，再由新 Permit 精确绑定，避免循环。新增/缺失执行文件、修改 Source/Seal、错误启动配置或旧 Permit 均拒绝。

私密包：`artifacts/p7/independent-holdout-v3/sealed/`；Anchor、协议、预算、Evaluator、实现 Manifest、60 份启动配置和 pending 授权模板位于同级私密目录。不要公开该目录或把完整 Gold 挂到候选。公开 [Case/Freeze Manifest](research/p7-independent-holdout-v3-manifest.json) 与 [最终预检记录](research/p7-independent-holdout-v3-preflight.json) 只作核验，不等于付费许可。

## 6. 零付费验证和历史保护

- 冻结源码上的 Python 3.11 / 3.13 新组件定向测试各 **49 passed，1 PG 用例分组选出**；冻结后的精确 PG node ID 两版本各 **1 passed**，合计每版本 50 个用例通过。早期分组日志的 pytest cache 不可写警告也保留；最终关闭 cacheprovider 的执行没有该警告。
- 额外独立 CSV Dataset/真实 BGE Corpus 上，completed、partial、unavailable 三个真实 PG/MCP + Fake 协议探针均通过，并以另一个进程 NoModel 复用，calls/artifacts/snapshot 一致。它们不属于 60 正式题目，不是 DeepSeek 模型质量成绩。
- 60 份冻结启动配置、Code/Gold/Protocol/预算闭包核对；额外执行文件拒绝、pending Permit 在凭据前拒绝；原角色、MCP、AST、读事务、限时/限行不放松。
- 原产品 Source 未变，引用已有 Linux Python 3.11/3.13 各 985 passed、1 Live skipped 的完整回归，没有重复耗时全套测试或远端 CI。最终 Ruff、JSON/Markdown、Diff 和历史行/文件检查以最终预检与交付核验记录为准。

最终冻结配置的真实 PG/MCP 准入为 **60/60**，其中 6 条精确宿主拒绝、54 个可派发 Runtime；不存在版本 999 继续不存在。**912 个既存文件和隔离实例的 63,129 条既存记录未被改写/删除**。这是准备验收，不是正式任务通过率。结构化最终命令、JUnit 与工件 SHA 见 [交付验证](research/p7-independent-holdout-v3-validation.json)。

可复现的主要命令（需要本机私密封存包与已有隔离环境；不执行 Live）：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest evaluation/p7_v3/test_v3_contracts.py -q -p no:cacheprovider -k 'not pg_budget'
.venv-313\Scripts\python.exe -m pytest evaluation/p7_v3/test_v3_contracts.py -q -p no:cacheprovider -k 'not pg_budget'
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest evaluation/p7_v3/test_v3_contracts.py::test_pg_budget_reopen_keeps_unknown_charge_and_blocks_duplicate_settlement -q -p no:cacheprovider
.venv-313\Scripts\python.exe -m pytest evaluation/p7_v3/test_v3_contracts.py::test_pg_budget_reopen_keeps_unknown_charge_and_blocks_duplicate_settlement -q -p no:cacheprovider
.venv\Scripts\ruff.exe check src scripts tests evaluation/p7_v3
.venv\Scripts\ruff.exe format --check evaluation/p7_v3
git diff --check
```

物化、作者校验和 Seal 发布命令均是一次性操作，已完成且拒绝覆盖；不要为复核重复运行。完整日志、最初失败、草稿差异、旧 v1、新 v2、原 P3 失败与追加机械验证均在忽略目录保留。公开仓库不包含私密 case-spec/Gold，缺包时这些准备测试不能被冒称可在任意机器直接执行；正常产品回归仍使用原 tests。

准备期间保留的失败：首次 Oracle 使用 CASE 被原 AST 白名单拒绝，改为独立 SQL 的 FILTER 写法；未封存单位标签纠正；全空日期显式追加 v2；新评分器严格 JSON 与原文摘取投影接线修正；旧 Smoke 指纹助手固定 v1，因而新 v2 被权限边界拒绝，新增版本化评测适配后通过。没有修改原产品、Gold 历史成绩或安全检查来通过。这些错误都发生在封存/真实目标模型执行之前，日志、旧草稿、原证据与版本保留。

原业务 Holdout 保持 60 条、31 observed / 29 not_run、v1 25/31、离线 v2 26/31、61 calls / 77,897 Token。Smoke 保持 8/8、20 calls / 27,167 Token、估算 USD 0.00584658；本轮没有续跑、重评分或合并成绩。历史 PG 未启动/重哈希；其旧收据保留，本轮数据库行级保护检查针对实际使用的隔离 unified 实例。

## 7. 预算与剩余边界

建议下一轮最多 54 Runtime、432 个真实模型 attempt、**972,000 Token 计账单位**；Root 8 calls / 18,000 Token，Child 4 / 18,000，输出 1,200；并发 1、零 SDK/外层重试，每任务 180 秒、Campaign 10,800 秒。11 个固定分区复用原持久 Ledger：10×5 Run/90,000 + 1×4 Run/72,000，最大计账和为 972,000；派发槽与模型 calls 分开记录。预算约束不是新计费引擎，详见 [Live 授权方案](p7-gate2b-live-authorization-plan.md)。

冻结峰值最坏单价 1.2 USD/百万 Token，费用估算上界 **USD 1.1664**，不是实际账单保证。不能把旧平均成本乘 60 当最坏证明，也不能把已观测 Smoke 视为本包成功率预测。

剩余风险：同开发流程与共享 Source 的相关性；闭配方/单用户、Date/UTC 粒度、不支持任意维度/净退款/现金流；真实模型多轮与新检索问题未执行；供应商别名/缓存/费率可能变化；人工审批与真实生产多租户不在本轮。最终通过准备仅表示可申请下一轮授权，不能宣称正式 Benchmark 成功。本轮到此停止，不自动提交、推送或执行 Live。
