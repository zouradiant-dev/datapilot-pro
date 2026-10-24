# SQL+RAG 单次 DeepSeek Live 重跑

状态：2026-10-24 通过一次有界真实组合 Smoke；与既有 SQL-only、RAG-only 成功记录共同满足 Gate 0 工程接入门槛。正式评测、Gate 1、P8–P11 未执行。原失败保留，不据此估计稳定成功率。

## 授权与冻结条件

用户在 SQL+RAG 注释下明确给予重跑授权，并在服务中断后要求继续。限 1 个新 Run、8 次模型调用、18,000 Token，失败不自动重跑。只用现有合成 XLSX 和 billing.md；没有重新导入、Seed、迁移、清库、删卷或变更授权。主 Docker 网站 8501 仍为原 Fake profile；独立 Live 宿主/API/UI 为 8001/8502，凭据不入仓库或报告。

HEAD 基线 `ed7fc79efe9b308603ab45c22e85bacb76c6602d`，包含此前尚未提交的参数契约/RAG-only 修复；不能将该 SHA 单独当作本次完整源码版本。`artifacts/rag-only-web/source-frozen-live.json` 的 194 个运行、测试、迁移与依赖文件哈希重核无变化。本次仅增加验证记录和文档，产品源码、Prompt、阈值和预算未再调整，用户 v2.4/v2.5 原文件保持不变。

原失败 Run `30b093f9-127a-485d-a7c8-7a2993780a1c` 不恢复、不覆盖。新 Conversation `e1aa2bce-baa7-46be-bcb9-d9101cb02ce5`，新 Run `817e4cc8-483f-42f5-a567-2c27055d0cda`。

使用相同原问题：“计算2025年10月已支付账单收入，并检索已授权文档说明已付款账单收入的定义，保留真实来源引用。”通过 Chat-first 调整候选范围，人工确认原 Dataset/metric/窗口/Corpus 后提交原审批；没有启动最初的仅指标候选。审批前 0 次模型/工具调用；审批请求仅 1 次、同一 Run 完成原 Outbox ACK。

## 实际链路与结果

Chat-first → FastAPI → 原 Gateway/Ledger → LangGraph → 已审查 P3 指标任务 + 有 scope 的 RAG Worker → Verifier → deterministic Report。计划版本 1、5 步，指标、文档、报告任务均 succeeded；execution=succeeded、business=completed，覆盖 metric_1 与 documents，没有缺失证据或未确认 claim。

- 模型是 deepseek-flash，Thinking disabled、temperature=0、SDK retries=0、原生 max_tokens=1200、timeout=30 秒；实际响应名 deepseek-flash，fingerprint `e72d3c7f663d3e1383b00b3884cb4501`。可变别名的具体权重未独立固定。
- 实际 4 次模型调用：Planner 1、RAG 3；指标由 P3 封闭配方确定性执行，Report 为可信投影，没有额外付费解释器。
- 工具轨迹为 p3_metric_execution，以及 RAG 两次 search_documents（同一批模型决策）、一次 read_context、一次 submit_rag_result，最后 verified_report_projection。两次检索返回同一原件，不当作两份独立文档。
- 本次模型直接传入实际检索的 document_id，读取成功，未由宿主猜测/补 ID，未触发 Stop Hook 纠正。原条件校验、授权和共享纠正额度不变；本次成功不等于真实验证了所有纠正分支。
- 最终 300 CNY 的已支付账单收入，窗口 `[2025-10-01,2025-11-01)`。不是 MRR，也未计算因果。

## 独立业务与来源核验

原 NoModel inspect_run 重新构建 Manifest、校验完整 Artifact 与预算，并由真实 scoped MCP 重新读取证据；只读验证不执行模型或 resume。

| 维度 | 实际结果 |
|---|---|
| Dataset/version | a3c64b99-d463-54eb-8a0e-55eebc725d53 / 1 |
| Semantic/Metric | semantic v1；paid_invoice_revenue v1 |
| 金额 Gold | 原 openpyxl + Decimal 独立 Gold 为 300 CNY；i1/i2/i6 |
| P3 Evidence | c002f686-b5b6-48d4-819b-564bb229056c |
| P3 Verification | 17648117-039a-4068-b284-51007d498c35；verdict=verified |
| 六层业务规则 | safety/shape/semantics/recomputation/references/coverage 全 passed |
| RAG 来源 | billing.md；既有 Corpus cc196ad2-2b8d-4b24-8b0a-926f78c0b07f |
| 原件位置 | Unicode `[0,103)`；第 1–3 行 |
| 原件/chunk hash | 172ded94f285154b2b8fcfd78f1ac70a0c9e793ad5542434c457ff2b17f2eb43 |
| Chunk | 3ed7b7048d8df89584b581d199049083f3d35ad5ae751bd765e90f813d29733e |
| 完成收据 | rag-submit-v1，outcome=complete，verdict=semantic_retrieval |
| 业务因果 | business_conclusions_verified=false；没有因果 claim |

核对 source/index/embedding revision/chunker/跨度/hash/原问题及 metric_1 关联，真实 ONNX 512 维 Embedding（fixture=false）和 PG17/pgvector。goal_score=0.7114380598068237，阈值仍为 0.55；分数只是相关性，来源授权、完成收据、原件与 Report 独立验证共同成立才发布引用。内部引述逐字等于原件片段；组合报告公开投影继续仅显示来源引用，不新增正文泄露。图表单位/时间/数据绑定同一已验证指标。

具体 source/semantic/metric/query/result hash 与证据 hash 见 [结构化验证记录](research/sql-rag-live-retry-validation.json)，不导出原始业务行、Prompt、文档正文或向量。

## 用量、延迟与费用

审批于 2026-10-24 12:04:24（Asia/Shanghai）入账。5898 input / 516 output / 6414 total Token，其中 provider cache-read 2816；模型耗时合计 3640 ms，审批入账至 Worker ACK 20304.909 ms。该时延不包括人工确认或随后较慢的只读 UI/证据轮询，不是完整用户交互延迟。

根据 [当天核对的官方定价](https://api-docs.deepseek.com/quick_start/pricing/)，周六为非高峰；按每百万 input cache-miss USD 0.15、cache-read 0.003、output 0.60，以 Decimal 和实际 usage 估算 USD **0.000780348**，实际扣费/账单未知。cache-read 不等于 Journal 重放；没有声称缓存节约率。未统计正式成功率、p50/p95 或成本优势。

## 服务恢复与持久一致性

后续继续只读核验时发现原 Docker 与临时 API/UI 已停止。恢复前确认该 owner 4 个 Run 全 ACK，本次 Run 无 issued/uncertain；只恢复原容器和原 profile 的 API/UI，没有恢复执行或追加付费调用。这是实际服务停止后的历史读取观察，未人为注入故障，不替代 P7 故障矩阵。

重启后同一 Conversation/Run 正常展示完成报告。11 项关键比较全相同：run_id、payload/Manifest/Ledger/calls/RagScope/report hash、Artifact 引用、Token、模型和工具收据；state/report 也完全一致。模型调用 **4 → 4**，新增 **0**；P3 ID/hash/verdict 及 RAG 引用保持。私密本地记录在 artifacts/sql-rag-retry/，包括 before/result/after-restart、source-verification、restart-verification、截图与日志。

## 测试复用与本次检查

本轮没有改产品或测试源码，冻结 194 个哈希一致，因此不重复耗时 pytest。读取并核对同源码的真实 JUnit：Python 3.11/3.13 非 PG 各 484 passed；相关真实 PG/恢复组为 3.11 的 23 passed + 2 项兼容复验、3.13 的 9 passed。这些组使用非付费模型替身，不能算作 DeepSeek 实验，也不是完整总套件新回归。

本次新执行的是 1 次真实 DeepSeek Smoke、真实 PG/MCP/NoModel 独立复核、原服务重启后的只读一致性和浏览器历史报告核验。Ruff check 通过；排除受保护的用户 docs/codex-prompts-v2.5.md 后 format check 为 最终为 240 files already formatted。全目录格式检查的该文件原有问题未改。3 份 JSON 格式有效，12 个本地 Markdown 引用均存在，git diff --check 通过；公开记录经密钥/原文扫描，暂存区为空。

## 当前门槛与停止边界

SQL-only 原成功、RAG-only 原成功、本次 SQL+RAG 成功，Gate 0 仅在工程接入 Smoke 层面通过。原组合失败及费用/耗时/Token 记录保持；本次成功不能覆写它或形成稳定效果结论。主 8501 未切换 Live，没有正式意图基线、开发集/Holdout、Gate 1 或 P8–P11，也没有自动提交/推送。
