# Gate 0：RAG-only Web 与文档读取修复

本轮只补齐独立文档问答及 SQL+RAG 实测暴露的读取参数问题，不进入正式 P7 Benchmark 或后续阶段，不自动提交/推送。基线 `ed7fc79efe9b308603ab45c22e85bacb76c6602d`；原 SQL 成功和 SQL+RAG 失败记录保留，见 [Gate 0](p7-gate0.md)。本轮 Live 授权仅 1 个新 RAG-only Run、8 次模型调用、18,000 Token，失败不重开 Run，不重跑 SQL/SQL+RAG。

## Trace 定位与最小修复

原 Run `30b093f9-127a-485d-a7c8-7a2993780a1c` 的持久 AI tool_calls 两次读取均只有 artifact_id、max_chars，未带 document_id。原通用 Schema 将此参数标为可选，因为 context/schema 读取不能带文档选择；documents 分支却必须用真实文档 ID。原循环只允许提交参数错误使用一次纠正，读取参数错误直接终止。

原始 HTTP wire 响应没有保留，不能独立断言供应商还是 SDK 在该层产生了省略。新增原生 HTTP Mock 证明：供应商响应提供 document_id 时，当前 DeepSeek 适配器会保留它。修复工具 Schema 描述和 RAG 静态约束，明确两个 ID 的区别；仅将 RAG `read_context` 的 INPUT_INVALID 纳入原共享一次纠正额度。实际读取仍严格拒绝缺参、错误 ID、其他任务/Run/版本工件；不自动猜 ID、不放宽授权、不增加纠正计数器或协议。

最初四项反例真实执行为 4 failed；修复后包含在后续通过的测试中。伪造 artifact_id 仍立即 TOOL_FORBIDDEN，不触发纠正。反复缺参在原一次额度后明确失败，assistant/tool 配对完整。原阈值 0.55、两次检索上限、submit_rag_result、Journal 和 unknown-outcome 语义不改。

## 三种契约与身份

| 类型 | 必要目标 | 文档与指标关联 | 审批 |
|---|---|---|---|
| SQL-only | 已确认 MetricRequest | 无文档 | 保留原规则；Chat 强制审批 |
| SQL+RAG | 已确认指标和 DocumentGoal/Corpus | 必须指向实际指标目标 | 保留原规则；Chat 强制审批 |
| RAG-only | 完整原始文档问题、授权 Corpus | metrics=[]、metric_goals=[]，禁止虚构指标 | 强制审批，require_review=false 拒绝 |

空任务、重复/不存在的目标、空 Corpus、替换原始问题均拒绝。有限规则只将明确文档问题送到文档候选；计算/统计等目标不能静默变成文档回答，不增加意图模型入口。问题上限 512 字符，不截断。Corpus 必须由用户选定，文件名及聊天历史不是授权。

`ProductService.task_payload` 从可信 Web grant 推导 CorpusPin 与其 Dataset/version，重新通过原 MCP 验证 source hash；即使没有 Metric，也不会省略 Dataset 授权。候选 hash、Host Policy、原 Outbox、审批、Run Manifest、Budget、Journal、官方 Saver 均复用。撤权、版本/hash 变化、过期 Run 仍拒绝。零指标的上一 Run 不再被当作 metrics[0] 使用。

没有迁移、新持久状态、第二套调度器或 RAG Agent。持久 ReportScope/Artifact 不新增字段；旧 SQL/SQL+RAG 的原字段和值保持，旧 P3 Evidence/Verification 不变。新增公开 `CitationView.quotation` 仅为独立文档回答提供有界原文；组合分析仍为空，不公开其正文。ReviewDocument 的 Dataset/version/source hash 只供审批展示，不是客户端授权。

## 回答与完成验证

继续原 Planner → RAG Worker → MCP → submit_rag_result → Verifier → deterministic Report。纯文档没有 SQL Worker，也不构造 P3 Metric、Evidence 或财务图表。Report 重新核验源/index/chunk/hash/跨度、原始问题相关性和来源数量；明确指定的普通 TXT/MD 文件名还须与可信 manifest 名称一致。Worker 检索成功不自动意味着回答 completed；不足、错误来源或未被接受的完成收据不能升级。

首版回答为保守原文引述和对应引用。引述由已核验 chunk 直接投影，用 st.text 展示，禁止 HTML/脚本执行；不额外调用模型改写事实。它仅说明文档写了什么，不证明因果或业务数字。原 completed/partial/unavailable/blocked 与 execution_status 分开；纯文档的 business_metrics_required=false，不标记 P3 数值已验证。没有调优语义阈值或实现一般自然语言蕴含证明。

文档正文、向量、Prompt 不进入公开 Trace；私密 Artifact/Checkpoint 保留原工件，授权浏览器只展示所选的有界引述。Review 仍展示原问题、来源版本、模型模式、预算和费用提示。

## 验证记录

非付费工程 Gate 已通过；Live 记录见下一节及 [结构化记录](research/rag-only-web-validation.json)。本地失败/回归证据位于忽略目录 `artifacts/rag-only-web/`，不会用 Fake/Mock 成功替代 Live。

| 验证组 | Python | 真实结果 |
|---|---|---|
| 全部非 integration / 非 live 用例 | 3.11 / 3.13 | 各 484 passed、178 deselected |
| 实际 PG/pgvector/MCP、RAG 收据、API/进程故障、旧报告 | 3.11 | 23 passed |
| 最后序列化兼容保护后的纯文档和组合报告复验 | 3.11 | 2 passed（相关用例复验，不计成新增独立任务） |
| 最终纯文档、撤权/版本/不足/错误来源、旧报告及 unknown-outcome | 3.13 | 9 passed |

执行命令以本地对应 JUnit 为准：`nonpg-py311-livegate.xml`、`nonpg-py313-livegate.xml`、`pg-py311-final.xml`、`pg-py311-compat.xml`、`pg-py313-final.xml`。所有 pytest 设置 `DATAPILOT_RUN_LIVE_TESTS=0`，PG 组另设 `DATAPILOT_RUN_DB_TESTS=1`，仅使用新建隔离 owner/Run/资源；不同 Python 的 PG 故障组串行。没有执行完整 662 项总套件，不能把上述相加当成完整回归或独立业务任务数量。

194 个源码/测试/迁移/依赖等文件记录 SHA。最早冻结后只有文档字符串空白行（精确旧 hash/AST 等价已验证）、公开引用兼容 serializer 及测试增强；对应单元与实际 PG 报告均已复验。最后新增同批两个缺参读取的测试后，两版本非 PG 再跑为各 484 passed，运行时代码未变。所有原始冻结记录及阶段 JUnit 保留，不改写为同一快照。

`ruff check .` 通过；排除用户受保护 v2.5 规划后 `ruff format --check --exclude docs/codex-prompts-v2.5.md .` 为 239 files already formatted。OpenAPI 由实际本地 API 导出核对，24 个路径未新增接口，只扩展既有契约。旧两组 P3 ID/hash/verdict 经 scoped MCP 再核对不变。工程 Gate 凭据为 `live-gate-preflight.json`；本节的 Fake/Mock/脚本用量不列入真实 DeepSeek 统计。

已保留的工程失败：初轮 PG 测试被系统 Temp ACL 阻断；改用仓库内新的隔离临时目录。撤权测试初稿误用不存在的 expires_at，使用现有 enabled/授权身份字段后重新验证；没有为测试修改 Schema。原失败日志/JUnit 保留，不覆盖成通过。

Gold 在任何新 Live 输出前冻结：`tests/fixtures/reporting/billing.md` SHA `172ded94f285154b2b8fcfd78f1ac70a0c9e793ad5542434c457ff2b17f2eb43`，Unicode [0,103)、行 1–3。应引述付款状态/账单日期/人民币单位、非 MRR、退款及未支付不能猜测纳入、快照/窗口/确认定义的规则；不计算新业务金额。原始问题固定使用用户指定全文。

## 真实 Live 及实际重启结果

2026-10-24 11:39:08（Asia/Shanghai）批准唯一新 Run `1a29dac0-cbf1-4582-a541-1a89bae75dc5`，Conversation `52ec1210-56c3-402b-ab14-c3d042e206c4`。真实 Chat-first 创建、人工审批、FastAPI → 原 Gateway → 原 Durable/LangGraph → RAG Worker → MCP/PG17/pgvector → 原完成协议 → 确定性文档回答均经过实际执行。审批前模型/工具为 0；最终 execution=succeeded、business_completion=completed、错误为空。

| 项目 | 实际结果 |
|---|---|
| 模型 | deepseek / deepseek-flash；返回同名，fingerprint=e72d3c7f663d3e1383b00b3884cb4501 |
| 适配配置 | 原生 DeepSeek Chat Completions；Thinking disabled、SDK retry=0、输出上限 1200、超时 30s |
| 调用 | 5 次，Planner 1、RAG 4；无付费重跑 |
| Input / Output / Total Token | 7453 / 544 / 7997；provider usage_complete=true |
| Cache-read Token | 3968，供应商 usage；不是 Journal 重放，也不是缓存消融收益 |
| 模型耗时合计 | 4704 ms |
| 审批入账到 Worker ACK | 19097.828 ms；含派发/MCP/持久化，不含用户思考及 UI 轮询 |
| 费用 | 估算 USD 0.000861054；未读取账单，billed_amount=null |

价格于 2026-10-24 再核对 [官方定价](https://api-docs.deepseek.com/quick_start/pricing/)；本次为周六非高峰，用实际 cache-hit/cache-miss/output Token 分别乘每百万 USD 0.003/0.15/0.60。只核验了服务返回的别名/fingerprint，不宣称永久固定模型权重或稳定成本收益。

实际工具为两次 search_documents、一次 read_context、一次 submit_rag_result，以及确定性 verified_report_projection。两次搜索命中同一 chunk；不算两份独立来源。本次模型自己提供了实际 documents[].document_id，读取反馈没有 error，原件跨度/hash 对齐，宿主没有猜填。完成收据为 semantic_retrieval，业务因果仍未验证。最终没有 P3 Metric、Evidence 或图表，回答只引用 billing.md 全部 103 字符和原行号。

独立读回的引用是 Chunk `3ed7b7048d8df89584b581d199049083f3d35ad5ae751bd765e90f813d29733e`，行 1–3、[0,103)，source/chunk SHA 与上述 Gold 一致；goal_score=0.5906627774238586，原阈值仍为 0.55。绑定原授权 Corpus `cc196ad2-2b8d-4b24-8b0a-926f78c0b07f`、index `45dba19f4ae81e168a5e64a642f8a7df8057e19470ec202f1f71608c76df2dae`，真实本地 Embedding，fixture=false。得分不是回答真实性依据；原件、manifest、收据、引用式回答逐项复核后才判定本次通过。

随后实际停止并重启专用 API/UI 进程，按原 URL 读取同一历史对话/Run，重新校验授权和完整工件。payload/Manifest/Ledger/calls/RagScope/report SHA、Artifact 列表、Token、模型/工具记录、状态和报告均一致；模型调用 5 → 5，新增 0。原两组 P3 Evidence/Verification 的 ID/hash/verified 另经原 MCP 重读不变。没有请求 Run resume、清账、重写旧证据或启动替代 Run。

浏览器实际呈现完成状态、完整授权原文及来源引用；截图为 `live-answer.png`、`after-restart-answer.png`、`verified-quotation.png`。保留临时回环 [8502 对话](http://127.0.0.1:8502/?conversation=52ec1210-56c3-402b-ab14-c3d042e206c4) 供查看；原 8501 网站仍为原 Fake 部署，未切换旧宿主策略。新增文档回答需本地新代码部署，本轮没有自动改变主站模型模式。

| Gate 0 路径 | 结果 |
|---|---|
| SQL-only | 复用原真实单次成功，不重跑 |
| SQL+RAG | 原真实失败保留；本轮参数修复及离线回归通过，没有获授权的新组合 Live |
| RAG-only | 本轮真实单次通过，并通过 API/UI 实际重启后只读一致性检查 |

**纯文档交付时的历史快照：当时 Gate 0 整体仍未通过**，缺少成功的 SQL+RAG Live 证据；不能以当前纯文档成功替换原组合失败。后续正式效果评测、Holdout、Gate 1 及 P8–P11 未执行。完成本轮后停止，不追加付费重试，不自动 commit/push。

## 修改范围与限制

- orchestration/tools.py、loop.py：条件参数说明及原一次纠正；无新工具、权限或状态。
- web/contracts.py、reporting/contracts.py：严格跨字段允许纯文档，公开引述 DTO，禁止空任务/伪造指标和图表。
- web/intent.py、chat.py、service.py：有限文档候选、零指标历史保护、可信 Corpus→Dataset/source 授权与原审批创建链。
- reporting/service.py、adapter.py：独立文档引用/问题要求检查及纯文档完成标志；原 P3 六层未改。
- web/chat_contracts.py、chat_routes.py、ui_chat.py、ui_components.py：审批来源展示、选择无指标、纯文本引述，继续 HTTP-only。
- 新测试与既有 DeepSeek/UI 测试：失败反例、非付费协议、真实 PG/MCP、授权/不足/幂等/重启；依赖、历史迁移与锁文件不改。

长问题、一般语义蕴含、任意来源文件名表达和完整文档覆盖仍非通用能力；不能根据一次 Smoke 宣称稳定成功率。SQL+RAG 的历史失败不因本轮离线修复或 RAG-only 成功而变为 Live 通过。用户 v2.4/v2.5 原文件不改。

当前有限意图入口要求明确文档/TXT/MD 表述，不能当成 Gate 1 语义增强。已完成旧 Run/P3 读取及本版本进程重启已验证；任意旧在途 Worker 跨代码版本继续执行不作通用承诺，仍须原 Manifest、上下文和 Journal 校验，不能通过跳过校验强行恢复。新增原文展示是本地可信宿主授权的有限引述，不是公开 Trace 或生产多租户文档服务。


## 后续独立实验的状态同步

2026-10-24 用户另行明确授权 1 次 SQL+RAG 重跑，Run `817e4cc8-483f-42f5-a567-2c27055d0cda` 实际成功并独立核验。三条路径由此达到 Gate 0 工程 Smoke 门槛；本文件的纯文档实验、当时未全通过的快照及旧组合失败均保留，不改写历史指标。后续实验详见 [SQL+RAG 重跑记录](sql-rag-live-retry.md) 与 [结构化记录](research/sql-rag-live-retry-validation.json)。这不是正式评测或稳定成功率结论；未进入 Gate 1。
