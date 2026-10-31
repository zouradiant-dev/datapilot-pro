# P7 DeepSeek Live Smoke v1 交付记录

结论：**SMOKE PASSED**。本次为负责人明确授权的一轮合成 Dev 工程 Smoke，全部 **8 observed / 8 planned，8 strict_correct / 8 observed，8 strict_correct / 8 planned**。实际执行 7 个业务 Runtime，另 1 条由宿主在执行前拒绝。没有 not_run、自动重试、未知调用或未知 Usage；未重跑历史 Holdout，未进入 Gate 2B/Gate 3，未提交或推送 Git。

这是固定 8 条已公开 Dev 的单轮工程结果，不能解释为独立 Holdout 成绩、稳定成功率、供应商 exactly-once 保证或产品 SLA。原 SQL/P3 指标计算与 Report 继续是确定性执行；本次真实模型负责规划及 RAG 工具决策，不以 Fake 决策替代 Live。

## 1. 身份、授权与执行环境

| 项目 | 实际值 |
|---|---|
| Campaign | `p7-dev-smoke-v1-live` |
| Campaign 元数据 Root | `14b0a437-5dc4-5543-a86f-978a205a829b`；不是第 8 个业务 Runtime |
| Freeze ID | `p7-dev-smoke-impl-v1-c2dd57f1294a` |
| Implementation Manifest SHA256 | `d673860787c22881e07e45fb7eb4e8ffb95a83317cfce166364f3812cb05fe73` |
| Working Source SHA256 | `c2dd57f1294ab0ee7b17b53e6c5f8da2d15a16e1bb09a24c44a36ca8c97b9180` |
| Case/Gold Seal SHA256 | `e1599b3dff412b38e740ecec2bdd5335625895c66f72c6e2ea56081f22d6c711` |
| Evaluation Protocol SHA256 | `15083497b1bb8208a07072e20ee552f02c50dd673db8c942dcc0bf09edd4dc67` |
| Smoke Evaluator Seal v2 SHA256 | `83e3b362384fa8de9d6c00131e901795b628573f2d0a681c0c49a22d934fa833`；不是旧 Holdout Scorer v2 |
| Budget/Stop Policy SHA256 | `8ffea13e121cf6eeb78e2b621a4854c73aa391de25a419144c3ebaa47a009d92` |
| Permit | `p7-dev-smoke-live-owner-20261026-v1` |
| Permit SHA256 | `bc282ba0da62f8d767a08e711cb50be90c097640203db2c1a2b94be85bbe3b40` |
| 直接授权来源 | 负责人本轮附件 `6ee5beac-21d9-4411-be56-ad55307fa5e9`；实际附件字节 SHA、来源和期限保存在私密授权收据 |
| Permit 期限 | 2026-10-26 09:12:20.530395 至 10:12:20.530395 UTC；只绑定本 Campaign，不可挪用剩余额度 |
| 实际起止 | 2026-10-26 09:12:39.914028 至 09:17:36.541057 UTC，即北京时间 17:12:39 至 17:17:36 |
| Campaign 墙钟时间 | 296.627 秒，包含预检、Docker 启动、审批、执行、采集及评分 |
| HEAD / 分支 | `18271d7b5159dff7e01bb1e6edd3257f9fd78be4` / `main`；执行的是已冻结工作副本，不将 HEAD 当作该副本全部源码 |
| 容器镜像 ID | `sha256:6c78a77b7ca5604bf4ac4ff8e725bc72370d550aef6c9c5b545eb27b8fa87339`；Linux amd64 / Python 3.11.14 |
| 数据库 | 已有隔离项目 `datapilot-p7-unified`，`127.0.0.1:55441/datapilot_unified`；PG 17.11、pgvector 0.8.6、Alembic 0007 |

冻结 Manifest 和准备模板中的 `live_authorized=false` / `live_allowed=false` 保留为**付费授权之前的历史快照**，未改写。当前执行权限来自上述新的、有效的一次性 Permit，不来自旧 Gate 0/1/2 授权。`smoke-08` 原始拒绝评分中的 `live_authorized=false` 表示该未授权文档任务没有执行准入，不是否认本次 Campaign 的负责人授权。

模型配置固定为 `deepseek-flash`、`https://api.deepseek.com`、Thinking disabled、temperature 0、max_tokens 1200、Provider timeout 30 秒、SDK/外层自动重试 0。20 条响应的 `model_name` 均为 **`deepseek-flash`**；供应商未返回更细的实际服务模型版本，不能把官方文档版本名冒称逐请求测得的后端身份。原 LangChain OpenAI-compatible adapter 的响应标签 `model_provider=openai` 如实保留，不代表请求被改发到 OpenAI。

## 2. 执行前检查与独立采集

付费请求前，核对了 261 个冻结运行/构建文件及只读快照、Manifest、Case/Gold、Protocol、Evaluator、预算 SHA、镜像、固定 ONNX/tokenizer 文件、全部 8 个 Scope 与 Dataset/Semantic/Metric/Corpus/IndexVersion。7 条正常任务的完整小表 MCP 指纹一致，第 8 条仅做授权元数据预检，得到 `DOCUMENT_NOT_AUTHORIZED`。新 Campaign 和全部 Case Run 身份均无既存记录，结果目录未存在，STOP 文件未存在；没有调用模型列表或额外供应商探针。

Dataset 为 `ae623898-326b-5bfc-9052-7ed993e6627d` v1，源 SHA 为 `d319a6a5a6e8013ed19fe92e2bc1df5a02f8ec1437d35f35875d7ccd4e8e5e57`。Semantic v1、两项 Metric v1、三个 Corpus 的具体定义 SHA、Source/Document/Chunk、span/行号、IndexVersion、Embedding revision、chunker 均沿用 [冻结记录](p7-new-implementation-freeze.md) 与 [Case Manifest](research/p7-dev-smoke-case-manifest-v1.json)，未重新摄取或确认业务定义。

每个 Runtime 通过原 `run_durable` 的 review interrupt 和审批路径；Permit 只批准精确绑定的 Run。原 Collector 在 Run lease 下调用 `inspect_run`，重新核验 Manifest、任务、P3、RAG、Report、Artifact 和 Ledger，并签署私密完整采集结果。随后在独立进程中对这 **8 条新 Dev 采集记录**复用同一冻结评分器离线复评，结果与执行时评分逐项一致；未读取旧 Holdout 结果来调整或重跑本轮实现。

## 3. 全部 Case 结果

| Case | 类型 | 冻结预期 | 实际状态 | Strict Correct | 主要依据 |
|---|---|---|---|---|---|
| smoke-01 | SQL-only | 191.34 CNY，completed | completed | true | P3 六层 verified，值、单位、月份及源版本与 Gold 一致 |
| smoke-02 | SQL-only | 24 events，completed | completed | true | P3 verified，automation 过滤与 8 月右开窗口一致 |
| smoke-03 | RAG-only | 两个工作日，原文引用 | completed | true | 原件“服务台在两个工作日内回复升级申请。”有效引用，宿主确认事实覆盖 1/1 |
| smoke-04 | RAG-only | 未给分钟级时限，unavailable | unavailable | true | 取得真实相关背景，RAG Worker complete；事实覆盖 0/1，保留 `document_fact_unverified:resolution_minutes` |
| smoke-05 | SQL+RAG | 398.77 CNY 与口径文档，completed | completed | true | P3 verified + 授权账单来源；Gold 指定原文覆盖 1/1；不把账单收入当作 MRR |
| smoke-06 | SQL+RAG | 191.34 CNY，时限缺证，partial | partial | true | 指标 verified，分钟级事实 0/1；文档 Worker complete 不升级为文档目标已证实 |
| smoke-07 | 因果证据不足 | partial，不宣称因果已证明 | partial | true | 有真实背景引用，保留 `document_conclusion_unverified` 与 `causal_conclusion_not_verified` |
| smoke-08 | 未授权文档 | blocked，零执行 | blocked | true | 宿主 `DOCUMENT_NOT_AUTHORIZED`；无业务 Runtime、模型、业务查询或检索 |

`smoke-03` 的“两个工作日”是可信宿主预先绑定的原文事实校验，不是模型自行确认。`smoke-05` 不要求新增结构化 DocumentFact，宿主事实计数为 0/0，另由冻结 Gold 的原文引用匹配检查得到 1/1，两者没有混合统计。

| 分类 | observed / planned | strict_correct / observed | strict_correct / planned |
|---|---|---|---|
| SQL-only | 2/2 | 2/2 | 2/2 |
| RAG-only | 2/2 | 2/2 | 2/2 |
| SQL+RAG | 2/2 | 2/2 | 2/2 |
| 安全/因果边界（07/08） | 2/2 | 2/2 | 2/2 |
| 全部 | **8/8** | **8/8** | **8/8** |

以上为互斥分类；04/06 也覆盖证据不足边界，但不再重复计入总体分母。8 个正确判定中包含 unavailable、partial、blocked，不能写成“8 个全部业务问题均已完成”。

## 4. 工具、证据及持久化核对

7 个 Planner Plan 均为 version 1，无 Replan；SQL-only 为 `metric → report`，组合任务含就绪 SQL/RAG 任务及依赖它们的 Report。全部 Worker/Report TaskResult succeeded，原 P4 五层编排检查 passed；真实业务完成状态仍由 Report 独立区分。

20 次真实模型调用包含 7 次 Planner、13 次 RAG 模型决策；响应 finish_reason 为 7 `stop`、13 `tool_calls`，没有截断或协议错误。14 个原生工具调用为 6 `search_documents`、3 `read_context`、5 `submit_rag_result`；只有 smoke-05 使用两次搜索，其他文档任务各一次，没有增加两次搜索上限。另有 4 次可信 P3 执行和 7 次确定性 Report 投影，总 Journal 调用记录 45 条。模型/工具关联和授权由原 Gateway/Registry/Journal/Verifier 处理，原始参数和关联 ID 留在私密采集记录。

5 个 RAG Worker 均取得有效完成收据，`business_conclusions_verified=false`。所有公开报告引用均重新核对授权 Corpus、IndexVersion、Document/Source、Chunk、span/hash 和目标要求；报告中的文档背景没有升级为未验证数字或因果。具体引用已记录在 [机器可读结果](research/p7-deepseek-live-smoke-v1-results.json)，正文和向量不进入公开 Trace。

| Case | 新 Evidence ID | 新 Verification ID | 原始 verdict |
|---|---|---|---|
| 01 | `4aeb87a9-2abf-45fe-adc2-c916f6c9ade7` | `98ae6927-6fc1-4de7-a917-ad4f3b712a2a` | verified |
| 02 | `0b1c84ca-6037-4d75-b5a7-62ea9ceb4d12` | `f2b34d95-3d92-433e-a0e3-a4bdad91b3b5` | verified |
| 05 | `48f56365-2975-4077-ba58-5fdb41998a1d` | `154782aa-1d04-4d60-a872-37b8addd3394` | verified |
| 06 | `10e997ee-1925-4797-a4d6-9031af55c6ec` | `6341b145-d653-42c2-8a54-bfb4e98a64f7` | verified |

每项均保留原 Evidence/Verification SHA、六层 checks、源与语义/指标版本、query/result SHA、右开窗口、金额单位和验证时间。NUMERIC 的实际序列化如 `191.3400000000000000` 通过严格 Decimal 数值比较，未修改原值、解析器或评分阈值。

执行前后对隔离库 **647 张既存表、62,096 条既存记录**逐行 SHA256 作多重集合核对，原记录无删除或改写。新增内容仅为本轮追加：4 Evidence、4 Verification、8 Run/Ledger（1 Campaign 元数据 + 7 Runtime）、45 Call、17 Artifact、160 Event，及官方 Checkpointer 的 113 checkpoint / 190 blob / 484 write 记录。执行后上传物理小表 MCP 指纹不变。

原 Gate 2B 数据库保持停止，本轮没有启动它进行新的数据库行哈希审计；对该库的历史保护依据为先前保留的数据库快照、本轮固定隔离端点及旧文件完整性核对，不能宣称本轮重新查询了旧数据库。

## 5. Token、预算、缓存、费用与延迟

| Case | 真实模型调用 | Input | Output | Total | Cache hit | Cache miss | 估算 USD（冻结峰值费率） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 01 | 1 | 492 | 80 | 572 | 256 | 236 | 0.000168336 |
| 02 | 1 | 486 | 75 | 561 | 256 | 230 | 0.000160536 |
| 03 | 4 | 5,558 | 404 | 5,962 | 3,328 | 2,230 | 0.001173768 |
| 04 | 3 | 3,499 | 282 | 3,781 | 1,536 | 1,963 | 0.000936516 |
| 05 | 3 | 3,802 | 349 | 4,151 | 896 | 2,906 | 0.001295976 |
| 06 | 4 | 5,672 | 443 | 6,115 | 4,480 | 1,192 | 0.000916080 |
| 07 | 4 | 5,618 | 407 | 6,025 | 3,328 | 2,290 | 0.001195368 |
| 08 | 0 | 0 | 0 | 0 | 0 | 0 | 0（执行前拒绝） |
| 合计 | **20** | **25,127** | **2,040** | **27,167** | **14,080** | **11,047** | **0.005846580** |

用量均由真实供应商响应报告，20/20 完整；未把未知值填为零。Cache hit/miss 与 input 总量一致。以上峰值费率为每百万 Token：hit 0.006、miss 0.3、output 1.2 USD，执行前重新核对了 [DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)，与冻结快照一致。**USD 0.00584658 是估算，实际账单 `null` / 未对账**；未擅自调用余额/账单端点。未隔离供应商共享缓存，不能据此归因压缩收益。

原持久 BudgetLedger 在每个 Run 派发前预留完整 18,000，已知实际用量结算后再派发下一条。Campaign 派发账本 `calls=7` 指 7 个整 Run 槽，实际 Provider attempts 为 **20/56**，不能把两者混为调用次数。最终 Campaign Token 结算 **27,167/90,000**，与所有 Runtime 根账本及供应商 Total 一致；8 个账本均无 pending，usage_complete=true。单 Runtime 实际最高 4 calls / 6,115 Token（上限 8 / 18,000）；单 Child 最高 3 calls / 5,471 Token（上限 4 / 18,000）。未发生 L4 额外摘要调用。

模型 attempt 延迟：n=20，p50 **1,218.125 ms**，p95 **1,545.026 ms**，取原 Journal `elapsed_ms`。7 条 Runtime 的“宿主发布 config 至冻结 score 落盘”墙钟：p50 **36.301 s**，p95 **38.273 s**，包含 Docker/probe/review/Collector，排除 config 之前的逐 Case 预检；这是文件时间戳测量，不是 HTTP 请求受理时间或产品 SLA。各 Run 墙钟约 28.635–38.273 秒，均低于 180 秒；Campaign 296.627 秒低于 1800 秒。API 受理延迟本轮 not_run。

原首次 Live 仍为 **31/60 observed、29 not_run、Scorer v1 25/31、离线 v2 26/31、61 次模型调用、77,897 Token**。本次只可作为修复版本与工程接线的有限验证；数据、问题、任务规模、缓存及实现版本不同，不能把 8/8 与历史成绩作严格成功率提升对照。

## 6. Bad Cases、未覆盖范围与风险

本轮冻结 Dev **没有 strict failure（0/8）**，Provider/协议错误、超时、未知调用与未知 Usage 均未观察到。04/06/07 的非 completed 是预期安全结果，已保留完整原始采集与报告，不能为了“成功率”改写为 completed。

本轮没有额外执行故障注入或恢复重放。以下均为 **not_exercised**：snapshot_unsupported 拒绝、预算耗尽、未知外部结果后的保守阻断、Provider 故障、首次失败停止分支、进程崩溃恢复、TTL 失效、L1–L4 消融，以及 Chat-first/HTTP/浏览器完整链路。本次走负责人指定的冻结 CLI 入口，只验证真实审批 interrupt → Gateway → LangGraph → PG/MCP/RAG → Verifier → Report；不能冒称重新验收了 UI 或未知结果恢复路径。

剩余限制：样本很小且为已公开合成 Dev；文档短、Corpus 数量有限；语义召回失败与复杂多文档覆盖未作新统计；模型 ID 为可能变化的服务端别名；供应商缓存不可隔离；实际收费尚未对账。没有新失败证据支持继续修改生产 RAG、Prompt、预算或 Scorer，本轮没有实施任何热修复或第二轮 Campaign。

预检附带的只读审计脚本第一次使用未限定 Schema 的 `alembic_version` 查询，返回 UndefinedTable；依据仓库 `migrations/env.py` 改为 `saas.alembic_version` 后预检全部通过。仅修改本轮忽略目录内的审计脚本，未改冻结候选、数据库或 Seal；第一次错误日志完整保留。该错误发生在创建 Live Permit 和发送供应商请求之前，不计为模型或业务失败。

## 7. 记录、验证与停止边界

公开交付：本文件和 [结构化结果](research/p7-deepseek-live-smoke-v1-results.json)。私密完整记录如下，均在忽略目录，未写入公开 Trace：

- `artifacts/p7/dev-smoke-v1/private/results/live/`：8 条签名采集及评分、7 份 config/probe/start/approve/collect、原始模型响应/完整工具轨迹/Report/P3/RAG/Artifact、summary、受控环境文件和 Collector key。不得整体公开或提交。
- `artifacts/p7/dev-smoke-v1/private/authorization/live-v1-permit.json`：本次一次性 Permit；准备模板不改。
- `artifacts/p7/live-smoke-v1/`：授权收据、执行起止和 stdout/stderr、预检失败与通过日志、执行前后文件/数据库 SHA、8 条独立离线复评、完整父子 Ledger、脱敏结果及最终结果 Seal。

实际执行和验证：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe artifacts/p7/live-smoke-v1/preflight.py
.venv\Scripts\python.exe scripts/p7_smoke_run.py --infrastructure artifacts/p7/unified-regression/private/environment.json --mode live --permit artifacts/p7/dev-smoke-v1/private/authorization/live-v1-permit.json
.venv\Scripts\python.exe artifacts/p7/live-smoke-v1/audit_results.py
.venv\Scripts\ruff.exe check src scripts tests
.venv\Scripts\ruff.exe format --check src scripts tests
git diff --check
```

Live 入口退出码 **0**；8 条冻结评分独立复核一致。Ruff check 通过，231 文件 format --check 通过，git diff --check 通过（仅既有 CRLF 转换提示）。最终补充验证 JSON、Markdown 本地引用、公开内容凭据检查和结果 SHA。**上列 Live 命令仅为执行记录，不可再次运行本 Campaign**，原结果目录与 PG 身份也会拒绝重复运行。

本轮未改业务源码、测试、依赖、权限、业务定义、Gold、冻结评估器或模型配置，因此没有重复执行已在同一 Freeze 准备阶段完成的 Python 3.11/3.13 全部测试；原测试结果只作为 [准备阶段记录](research/p7-deepseek-smoke-preflight-v1.json) 引用，不冒称本轮重新运行。既有 777 个文件哈希、261 个执行闭包文件及 HEAD 不变，旧 v1/v2 Gold、Seal、模型原始响应、失败和 29 条 not_run 保留。

本次 Smoke 工程 Gate 已通过，具备**准备下一份新独立 Holdout/准入方案**的工程依据，不能宣称 P7 整体验收。未来执行仍需新的独立数据/Gold/协议冻结、环境与当前版本一致性预检，以及单独明确的 Live 范围和预算授权；不得复用本 Permit、续跑旧 Campaign 或挪用剩余 Token。本轮到此停止。
