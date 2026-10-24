# P7 Gate 0：真实 DeepSeek 产品链路准入

当前状态（2026-10-24，另获一次 SQL+RAG 重跑授权后）：**Gate 0 工程 Smoke 通过**。SQL-only、RAG-only 和 SQL+RAG 均有真实单次成功证据；原组合失败及全部历史实验指标保留。新增组合 Run `817e4cc8-483f-42f5-a567-2c27055d0cda` 已独立核验 300 CNY、P3 六层、真实文档完成收据及实际服务重启后的持久引用一致性。详见 [组合重跑交付](sql-rag-live-retry.md) 和 [结构化记录](research/sql-rag-live-retry-validation.json)。这不是正式业务效果评测，不进入 Gate 1。

## 范围与授权

基线 `ed7fc79efe9b308603ab45c22e85bacb76c6602d`。用户本轮仅授权 Gate 0；不执行 Gate 1 的语义增强、开发集或 Holdout，不推进 P8–P11，不自动提交/推送。保留用户已有 v2.4/v2.5 规划修改。

仅使用仓库合成 SaaS 样例与合成业务说明。**前次授权快照**：用户确认先跳过独立纯 RAG，收紧为最多 2 个 Run，每 Run 8 次模型调用、18,000 Token；总上限 16 次调用、36,000 Token。该阶段实际只用 4 次调用/4687 Token，未重跑失败任务。后续纯文档另获 1 个 Run 的明确授权，不能据此前次额度追加组合实验。未知调用仍按原 Journal 保守处理，全部模型调用复用原 Gateway/Ledger/Durable。

现有主网站保持 Fake 配置及原 owner。Live 验证使用独立可信本地 Host/owner 和回环端口，避免改变旧 Run 的宿主策略或覆盖旧 Manifest。只追加各自有明确授权的合成记录，不重新 Seed、清库或删除 Volume。

## 实际预检

以下为改动前预检的历史事实；metrics 至少一项的旧约束已在后续纯文档补全中由严格跨字段验证替代，不能再当成当前代码状态。

- 配置：provider=`deepseek`，model=`deepseek-flash`，base URL=`https://api.deepseek.com`；凭据存在，仅检查存在性，不输出密钥。
- 原 `llm/provider.py`：Chat Completions、temperature=0、Thinking disabled、SDK retry=0；输出上限 1,200 Token，调用超时 30 秒。未改变适配器或模型预算。
- 原 `CreateTask.metrics` 和 `ReportScope.metrics` 均要求至少一项；`CreateTask(question='检索业务文档', metrics=[])` 实际产生 `metrics / too_short` 校验错误。
- 当前 Rule-only 解析器无法为纯文档目标生成独立检索候选；这不是 DeepSeek 返回错误，也不计入正式业务成功率。
- SQL 报告及 SQL+RAG 报告入口已有实现。SQL 指标使用受审查 P3 配方，模型参与规划；不能把该路径描述成任意 NL-to-SQL 或独立 RAG 产品入口。

| 目标链路 | 当前状态 | 验收要求 |
|---|---|---|
| Chat → FastAPI → Gateway → LangGraph → P3 SQL → Verifier → Report | passed_single_smoke | 真实模型 1 次 / 560 Token；300 CNY，与独立 Decimal Gold 一致；原 Journal 与持久引用 |
| Chat → FastAPI → Gateway → LangGraph → RAG → Verifier → 文档结果 | passed_single_smoke_followup | 旧预检曾 blocked；后续真实 Web 单次成功，详见末节 |
| Chat → FastAPI → Gateway → LangGraph → SQL+RAG → Verifier → Report | failed_single_smoke | SQL 指标通过，真实检索产生候选；`read_context` 缺少 document_id，RAG Worker 失败，公开报告不可用 |

## 费用与结果记录规则

分别记录实际 provider input/output/cache Token、模型调用、工具轨迹、延迟和业务结果。金额估算用 Decimal；没有供应商账单时，`billed_cost` 必须为 null，不能把价格估算称为实际扣费。

2026-10-23 核对、2026-10-24 再核对 [DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing/)：Flash 每百万 Token，非高峰 cache-hit input / cache-miss input / output 为 USD 0.003 / 0.15 / 0.60；高峰分别为 0.006 / 0.30 / 1.20。两次请求均在非高峰时段，按实际返回 usage 估算；缺失 usage 明确未知。官方当前列示别名对应 DeepSeek-V4.1-Flash-1017；本次实际只返回 `deepseek-flash` 与 fingerprint `e72d3c7f663d3e1383b00b3884cb4501`，未独立核验服务端权重版本。

Gate 0 的一次小样本只验证接入能力；不能推导稳定成功率、RAG 总体质量或成本收益。三类要求未全部满足前，Gate 0 不判通过；后续阶段保持未执行。

## 已完成 SQL Smoke

2026-10-23 从独立 Live Chat-first 页面创建并审批 Run `4d4caa90-ae26-44fa-98ac-77d868219a57`。审批前原 Journal 模型/工具均为 0；批准后经原 LangGraph 规划、`p3_metric_execution` 与 `verified_report_projection` 完成。SQL 指标走封闭配方，模型没有任意 SQL 或 DDL 工具。

- provider 报告 input/output/total Token：479 / 81 / 560；cache-read=0；模型调用 1 次，耗时合计 2453 ms。
- 审批请求入账到 Worker 完成 ACK：17166.843 ms，包含派发和本地进程/MCP 启动，不等于模型延迟或用户思考时间。
- 精确结果：300.0000000000000000 CNY，窗口 `[2025-10-01, 2025-11-01)`；独立 openpyxl + Decimal 对提交的合成工作簿复算为 300 CNY。
- Evidence `0f63ad1c-31fd-4f6c-a18d-158ebc856de4`；Verification `66684fdd-fd14-48d3-9213-f0c061826791`；运行成功且业务 completed。
- USD 0.00012045 为实际 usage 乘官方时段价格的估算，实际账单金额为 null。

本地原始证据保存在忽略目录 `artifacts/p7-gate0/`：`sql-before.json`、`sql-result.json`、`gold.json`、`sql-approval.png`、`sql-report.png`。未导出原始 Prompt、业务明细行、文档正文或向量。SQL+RAG 需要显式选择授权 Corpus；这是受授权宿主操作，不应计为当前 Rule-only 自动理解文档范围。

初次本地临时部署因沙箱账号与 Windows 宿主账号不同，私密目录 ACL 导致进程无法读取配置；仅修正本轮新目录对宿主用户的权限，没有放开为所有用户可读。此失败发生在任何模型请求之前，不计入业务效果统计。续跑时先核对持久调用状态，不能因服务已停止而重跑成功 Smoke。

## SQL+RAG Smoke：已执行并保留失败

2026-10-24 10:35:23（Asia/Shanghai）批准 Run `30b093f9-127a-485d-a7c8-7a2993780a1c`。问题为“计算2025年10月已支付账单收入，并检索已授权文档说明已付款账单收入的定义，保留真实来源引用。”审批前 Journal 为零调用；数据集、指标、窗口、Corpus/index 均在原 Chat-first 表单中明确确认。

| 项目 | SQL | SQL+RAG |
|---|---:|---:|
| 真实模型调用 | 1 | 3（Planner 1、RAG 2） |
| Input / Output / Total Token | 479 / 81 / 560 | 3679 / 448 / 4127 |
| Provider cache-read Token | 0 | 768 |
| 模型耗时合计 | 2453 ms | 3781 ms |
| 审批入账到 Worker ACK | 17166.843 ms | 20507.180 ms |
| USD 费用估算，非账单 | 0.00012045 | 0.000707754 |
| 执行 / 业务状态 | succeeded / completed | failed / blocked |

合计 2 个 Run、4 次模型调用、4687 Token，估算 USD 0.000828204；实际扣费未知。cache-read 来自 provider usage，不能等同于 Journal 重放，也不是 Prefix Cache 成本收益实验。没有正式任务成功率、p50/p95 或稳定性结论。

实际链路为 Planner → 并发指标/文档任务 → Verifier → 受限报告工件 → blocked。工具包括 `p3_metric_execution`、两次真实 MCP `search_documents`、`read_context`、`verified_report_projection`。Journal 的 `complete` 表示调用收据已持久化，**不代表工具业务成功**；Trace 明确记录第一次文档读取 failed、同批第二次 not_executed。没有 `submit_rag_result` 接受收据，没有公开文档引用，API `report_available=false`。

失败根因定位在 [read_context 参数契约与实现](../src/datapilot/orchestration/tools.py)：`document_id` 在通用参数 Schema 中可选，但读取 `kind=documents` 工件时必须指定真实检索文档 ID。DeepSeek 对两个真实 artifact_id 均只传 `max_chars=2048`，省略了 document_id。第一个调用触发 `INPUT_INVALID: Choose an actual retrieved document ID`，第二个按现有失败收尾逻辑不执行。没有放宽校验、自动补 ID、自行提交完成或修改 Worker Loop。此为实际接入的负面案例，先于正式业务效果评测记录；61 项已有回归通过不能覆盖或消除这个 Live 失败。

SQL 分支仍获得 300 CNY 的原 P3 verified 指标：Evidence `bd9ddf12-16ca-4471-8b94-5dc92a03fd1d`，Verification `a45cfc79-848b-456c-9723-0987ff38617b`。Report 节点成功生成 blocked 工件，不意味着整次分析成功或报告已在网站发布。

## 独立核验与恢复边界

- 原 `inspect_run`（NoModel）与 scoped MCP 重新读取两次 Run 的 P3 Evidence/Verification，核对 ID、source/semantic/metric/query/result hash、时间窗口、CNY 单位、六层 passed 与原 verdict；均未改变。独立 openpyxl + Decimal Gold 为 300 CNY。
- 两次搜索返回同一真实 chunk，不是两份独立文档。重新核对授权 index/模型/切块配置及原合成文件：Unicode `[0,103)`，第 1–3 行，chunk/source hash `172ded94f285154b2b8fcfd78f1ac70a0c9e793ad5542434c457ff2b17f2eb43`，goal_score=0.7114380598068237。真实 ONNX Embedding + PG17/pgvector，`fixture=false`。候选正文与账单收入定义相关；**原件定位及相关性成立，不代表 RAG Worker 已完成，也不证明业务因果**。
- 2026-10-24 续跑前发现 Docker/临时进程停止，只恢复原容器及同一独立 Host；先核实只有旧 SQL Run、无 issued/uncertain，才创建 SQL+RAG Run。没有重新 Seed、迁移、删库或删 Volume。两个 Run 的所有调用均已结算，无 unknown-outcome；没有请求安全恢复或付费重跑。
- 原网站 `127.0.0.1:8501` 仍为原 Fake 配置；Live Smoke 使用单独的 `8502/8001`、owner 和私密配置，不改变历史 Run 的宿主策略。临时 Live 服务在证据收集后关闭；保存的截图是当时实际页面。

结构化记录：[p7-gate0-validation.json](research/p7-gate0-validation.json)。本地私密证据另含 `sql_rag-before.json`、`sql_rag-result.json`、`evidence-verification.json`、`sql-rag-approval.png`、`sql-rag-failed.png` 与两次启动日志。这里仅记录安全元数据、hash 和引用，不提交密钥、Prompt、明细或文档正文。

## 本轮验证与停止边界

在原最终源码上执行以下命令，两版本各 **61 passed**，均包含 1 项真实 PostgreSQL/MCP 只读查询，其余是 HTTP Mock/本地契约；这些回归不调用真实 DeepSeek：

```powershell
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest tests/test_deepseek_transport.py tests/test_chat_contracts.py tests/test_cross_source_report.py -q --junitxml=artifacts/p7-gate0/regression-py311.xml
.venv-313\Scripts\python.exe -m pytest tests/test_deepseek_transport.py tests/test_chat_contracts.py tests/test_cross_source_report.py -q --junitxml=artifacts/p7-gate0/regression-py313.xml
```

两次各有 pytest cache ACL warning，JUnit 和断言均完成。`ruff check .` 通过；`ruff format --check .` 发现用户原有、受保护的 v2.5 规划文档代码示例需要格式化，本轮不改它；排除该文件后 `ruff format --check --exclude docs/codex-prompts-v2.5.md .` 为 236 files already formatted。JSON 解析、Markdown 本地链接及 `git diff --check` 已检查。

192 个冻结产品/测试/迁移/依赖等文件 hash 与 `ed7fc79` 基线一致，v2.4/v2.5 规划 hash 未变。本轮未重跑耗时完整回归；此前两版本各 640 passed、1 skipped 属历史基线，不作为本轮新测试结果。只新增本交付文档、安全 JSON 记录及忽略目录中的 Smoke 证据/观察脚本，没有产品源码改动。

**前次交付快照**：当时尚未解决独立纯 RAG 产品契约、文档工件读取的条件参数表达与局部修复，以及修复后的获授权 Live。该阶段未补入口、调阈值或进入 Gate 1；后续显式授权的完成情况如下，旧失败及指标均保留。

## 后续明确授权：RAG-only Web 与一次 Live

用户随后明确授权工程补全与最多 1 个新的纯文档 Live Run，8 次调用/18,000 Token，不重跑 SQL-only/SQL+RAG。代码及测试见 [RAG-only 记录](rag-only-web.md)、[结构化验证](research/rag-only-web-validation.json)。当前 Scope 允许严格验证的 metrics=[] 文档任务，空任务/越权/替换原问题拒绝，沿用原审批、Outbox、Journal、预算和完成收据；原 P3 六层及 P5B uncertain 不改。

Run `1a29dac0-cbf1-4582-a541-1a89bae75dc5` 实际经 Chat-first 审批并执行成功：5 次真实 DeepSeek 调用，7453 input / 544 output / 7997 total，cache-read 3968；模型耗时合计 4704 ms，审批入账到 ACK 19097.828 ms。费用估算 USD 0.000861054，实际账单未知。模型实际提供正确 document_id，两次真实检索、一次原文读取、一次 submit_rag_result 后，报告仅引述 billing.md 第 1–3 行；没有 P3 指标或图表。scope/source/index/chunk/hash 及原问题要求独立核验，本次 execution=succeeded、business=completed。

实际 API/UI 重启后同一 Run/报告/引用/Manifest/账本不变，模型调用保持 5，新增 0。两版本非 PG 各 484 passed；相关真实 PG/恢复组为 3.11 的 23 passed + 2 项兼容复验、3.13 的 9 passed，均为非付费模型替身；不能与 Live 混写。未执行完整总套件或正式评测，Ruff 全目录格式仍保留用户 v2.5 的原有格式问题。

**纯文档阶段结束时的历史快照**：当时三路径为 SQL-only 真实单次通过、RAG-only 真实单次通过、SQL+RAG 仍只有原失败实测。**当时 Gate 0 未全通过**；离线修复与成功的纯文档读取不是原组合路径的 Live 复验。本轮停在此边界，无额外付费调用、自动提交或推送。


## 后续另获授权：SQL+RAG 单次重跑

用户明确授权原组合路径再执行一次，收紧为 1 个新 Run、8 次模型调用、18,000 Token，失败不自动重跑。重跑前核对 194 个冻结文件哈希均未变，现有测试适用于同一源码；原问题、数据/指标/文档版本、DeepSeek profile 与安全阈值不变。本次没有再修改产品代码，也未重跑 SQL-only 或 RAG-only。

2026-10-24 12:04:24（Asia/Shanghai）经 Chat-first 的范围确认、原人工审批、Outbox 和 Durable 执行 Run `817e4cc8-483f-42f5-a567-2c27055d0cda`。独立 Gold 与 scoped MCP 核对收入 300 CNY，六层 P3 全 passed；两次真实检索后模型正确指定 document_id，读取原件并通过 submit_rag_result。最终 execution=succeeded、business=completed，覆盖 metric_1 和 documents，公开报告有 1 项指标及 1 个原件引用。文档是描述性业务定义，不证明因果。

本次真实模型调用 4 次（Planner 1、RAG 3），5898 input / 516 output / 6414 total Token，provider cache-read 2816；模型耗时合计 3640 ms，审批入账至 ACK 20304.909 ms。按当天官方非高峰费率估算 USD 0.000780348，实际账单未知。原组合失败的 3 次调用/4127 Token 仍保留，不改写为成功。当前三路径各有单次成功，仅达到 Gate 0 工程接入门槛，不能据此宣称稳定性、成功率或成本优势。

续做只读核验时发现 Docker/临时 API/UI 均已停止，恢复原环境前先确认 4 个 Run 全部 ACK、无 issued/uncertain。本次没有人为制造故障或请求 resume。原 API/UI 重启后 11 项关键记录完全一致，4 次模型调用未增加，P3 ID/hash/verdict 及 RAG 引用不变。该观察不替代正式故障矩阵。

详细授权、版本/来源哈希、P3 ID、工具轨迹、费用与重启检查见 [组合重跑记录](sql-rag-live-retry.md)。原两次实验合计及纯文档实验指标不变，结构化文件分别以历史快照与后续记录区分。本轮不重复耗时完整 pytest；复用已核对源码一致的回归，新增实际 Live/NoModel/MCP/浏览器核验，并运行 Ruff 与格式/引用检查。没有自动提交、推送、Gate 1 或后续阶段。
