# P7 三项策略 DeepSeek Live Smoke：评估器错误停止

2026-10-29，本次负责人直接授权“授权进入真实 DeepSeek Smoke”，对应前一轮 [非付费准备包](p7-three-policy-smoke-preparation.md) 的单次边界。实际通过原 Gateway、持久 Ledger、LangGraph、审批、真实 PG/MCP、RAG/P3 和 Report 执行；没有 Fake 回退。

**结论：SMOKE STOPPED — EVALUATOR，未通过完整 Smoke 验收。** 计划 8 条，7 个 Runtime 已产生终态签名记录；6 条冻结评分通过，第 7 条触发冻结 Scorer 的空收据异常，第 8 条保持 not_run。未修复当轮源码、未重试、未续跑、未提交/推送，未进入 Gate 3。

## 授权、冻结与执行

| 项目 | 实际记录 |
| --- | --- |
| 父 Git HEAD / 分支 | `f8b122438d2c67ab26e618ecded72ecc18454015` / `p7-ci-verification-20261028` |
| Freeze | `p7-three-policy-dev-v1-4e9651e1844f`，284 文件精确字节闭包；包含未提交的新适配器 |
| Implementation Manifest SHA256 | `c46f092849e2fdd98f1220244641a1b8a43942c8b36c34429913cd7b2d6a79ce` |
| Permit | `p7-three-policy-dev-live-20261029-once`；本次新授权，已由停止的 Campaign 消耗，不复用剩余额度 |
| 计划 | 同一 8 条公开、非盲 Dev；7 Runtime＋1 宿主拒绝；不是新独立 Holdout |
| 上限 | 7 Run、56 attempts、90,000 Token；root 8 calls/18k、child 4 calls/18k、输出 1,200、并发 1、重试 0 |
| 时限 | Run 180 秒、Campaign 1,800 秒；新 Permit 在首次准入覆盖完整窗口及缓冲 |
| Provider | `https://api.deepseek.com`，Chat Completions / Native Tools，`deepseek-flash`，Thinking disabled，temperature 0，timeout 30 秒 |
| 实际执行 | 293.234 秒，7 派发槽，25 次真实调用，37,320 已知结算 Token，无 pending/unknown |
| 本轮模式 | 原 Durable Runtime 直接入口；未重新验收 Chat-first/浏览器/API 性能 |

执行前核对了全部源码/资产/配置 Hash、Gold/协议/Scorer/预算、数据/指标/文档/Index Pin、本地 BGE、PG17/pgvector/0007、隔离角色、未使用的 Run/Pool/Journal/Checkpoint 身份及当前官方费率。没有付费探针或余额查询。原 `authorization-template.json` 保持 authorized=false，另建私密新 Permit 并绑定本条用户授权来源；没有虚构人工逐条审阅。

使用唯一已有入口一次：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe scripts/p7_policy_smoke_run.py `
  --pack artifacts/p7/three-policy-smoke-v1/pack-v2 `
  --infrastructure artifacts/p7/fixture-portability-v1/private/311/environment.json `
  --mode live `
  --permit artifacts/p7/three-policy-smoke-v1/live-20261029/permit.json
```

该身份已经执行，**不得重运行上述命令**。原入口因 Scorer 异常 exit 1，并持久保留停止原因、已结算账本和 not_run 状态。

## 全部案例及分母

| Case | 类型 | Gold | 实际业务状态 | 冻结严格评分 | Calls | Token |
| --- | --- | --- | --- | --- | --- | --- |
| tps-01 | SQL | completed | completed；收入 637.45 CNY | 通过 | 1 | 565 |
| tps-02 | RAG；Required＋Supplement | completed | completed | 通过 | 4 | 7,043 |
| tps-03 | RAG；缺离线承诺事实 | partial | partial | 通过 | 4 | 6,038 |
| tps-04 | SQL＋RAG；缺补寄保证 | partial | partial；收入仍 P3 verified | 通过 | 4 | 6,158 |
| tps-05 | RAG；排除无关来源 | completed | completed | 通过 | 3 | 3,784 |
| tps-06 | RAG；未证实因果 | partial | partial | 通过 | 4 | 6,046 |
| tps-07 | RAG；英文原始短问 | completed | **blocked**；WORKER_LIMIT | **评估器 TypeError，未生成严格分数** | 5 | 7,686 |
| tps-08 | RAG；其他 owner | blocked | **not_run** | not_run | 0 | 0 |

planned=8，terminal_observed=7，frozen_scored=6，strict_correct=6，scorer_error=1，not_run=1。6/6 已评分条目通过不等于完整任务集 100% 成功；计划分母仍是 8。第 7 条有明确可见的业务完成不匹配，但不伪造一个冻结 Scorer 从未产出的 failed 分数。第 8 条虽然在非付费预检中被正确拒绝，本次正式 Campaign 未运行它，不能补算一次宿主拒绝或模型成功。

| Lane | planned | observed | scored | strict_correct | scorer_error | not_run |
| --- | --- | --- | --- | --- | --- | --- |
| SQL-only | 1 | 1 | 1 | 1 | 0 | 0 |
| RAG-only | 6 | 5 | 4 | 4 | 1 | 1 |
| SQL＋RAG | 1 | 1 | 1 | 1 | 0 | 0 |

7 条已观测的状态混淆：Gold completed→completed 3、completed→blocked 1、partial→partial 3。业务完成实际为 completed 3、partial 3、blocked 1；未运行项不放进混淆矩阵凑分。

四层结果分开记录：

- **授权安全**：7 个实际 Runtime 未观察到越权或扩权；宿主拒绝专项在本 Campaign 中未运行，不给安全拒绝率。
- **Evidence/引用**：2 个适用指标均经原 P3 验证，金额/单位/来源/定义 Pin 与独立 CSV/Decimal Gold 一致。5 个发布文档引用的 Run 均经原 inspect_run 重查；第 7 条没有发布未获准的候选为业务证据。
- **RAG Worker**：6 个已执行的文档 Worker 中，5 个有真实 semantic_retrieval 收据，1 个失败且无收据；6/6 首次查询为宿主原问。检索到候选、Worker complete 和最终业务 completed 没有混为一个指标。
- **BusinessCompletion**：三条 partial 保留真实事实与缺口；因果未证实仍不发布因果结论。英文任务 blocked，没有被提升为 completed。

## 第 7 条的真实失败链

1. 宿主原问为 `How should API keys be rotated?`，首次按原问检索，返回空匹配。
2. 模型在原两次搜索预算内改写为 `API key rotation procedure secrets management`，召回授权文档并成功调用 read_context，document_id 正确且无扩权。
3. 候选片段相对**原宿主目标**的 `goal_score=0.5200636386871338`，小于冻结 `0.55`。改写后的查询能够召回，不代表满足宿主目标相关性门槛。原完成验证返回 `EVIDENCE_INSUFFICIENT`，要求 insufficient/unavailable；这不是来源 Hash 失败或任意业务因果要求前置。
4. 该次 complete 提交是第 4 个 Worker 模型回合。原 Stop Hook 已提交一次 correction，但剩余 Worker 回合不足，实际返回 `WORKER_LIMIT`，TaskResult.status=failed、rag_completion=null。Report 安全返回 blocked，未发布不充分事实。所有外部调用结果已知，不涉及 unknown-outcome。
5. [冻结 Scorer](../scripts/p7_policy_smoke.py) 第 237 行假设只要 rag_result 非空就有收据，直接读取 `rag["rag_completion"]["verdict"]`，导致 TypeError。失败 TaskResult 允许 null 收据，现适配器缺少该合法分支的处理。这是本次 Campaign 停止的**评估器缺陷**，与前述产品任务失败分别保留。

未降低阈值、增加回合、修改 Prompt、Source Pin、Gold、Scorer 或完成协议；也未用新一轮请求替换失败。真实模型的第二次改写和多一步 read_context，与 Fake 的脚本决策不同，故本轮不是把离线结果换个标签。

## Token、费用与性能

25 条不同 Provider response ID 全部返回 `deepseek-flash`；SDK 的 OpenAI 兼容 adapter 元数据标签为 openai，不代表调用了另一家供应商或发生路由切换。返回模型 ID 不支持虚构更细后端版本。

| 实际 Provider 数据 | 数量 |
| --- | --- |
| Input Token | 34,811 |
| Output Token | 2,509 |
| Total Token | 37,320 |
| Cache-hit input | 19,584 |
| Cache-miss input | 15,227 |
| 已知结算 / 未知预留 | 37,320 / 0 |
| Campaign Run 派发槽 | 7/7；不是模型调用次数 |

逐条核对原始 token_usage、规范化 usage 和原 ledger 回执一致；Root/Child 预算、Hash、调用状态均有效，pending=0。缓存命中仍包含在 input Token 中，没有声称减少上下文计算 Token。

执行前免费重查 [DeepSeek 官方费率](https://api-docs.deepseek.com/quick_start/pricing/)，峰值 USD/百万 Token：命中输入 0.006、未命中输入 0.3、输出 1.2。按实际分类 Token 和冻结峰值费率估算：

`(19584×0.006 + 15227×0.3 + 2509×1.2) / 1,000,000 = USD 0.007696404`。

低于授权费用上界估算 USD 0.108。**实际账单 not_reconciled**，未调用账单/余额 API，不将估算当作真实收费或声称供应商 exactly-once 计费。

Campaign 工程耗时 293.234 秒。25 个 Gateway 客户端观测的模型 attempt 时延 p50=1,062.78ms、p95=1,767.17ms；7 个 Case 从本机目录创建到原 collect 落盘，含前检、容器启动、审批、MCP、模型及采集的工程 wall time p50=39.393s、p95=53.870s。采用 nearest-rank，小样本、不同任务复杂度且缓存不可隔离；不能当作 API/Web/SLA 或供应商内部推理性能。

## 独立复核、历史保护与交付

停止后仅使用原 collect/inspect_run 重新读取 7 个已提交 Runtime，未调用 start/approve/resume/replay 或新增模型请求。6 个已有严格评分离线重算 **6/6 一致**；第 7 条独立再现同一个 TypeError，没有新造分数。7 个 Run 的 Manifest、报告、Evidence/Artifact、预算、调用行内容均一致。

第一次审计将未 ORDER BY 的 SQL 调用列表当作顺序契约，遇到相同三条记录的不同返回顺序而断言失败。日志保留；后续按原 Journal 主键 `(run_id, call_key)` 比对，证明 Key 集及每行完整 Hash 相同，无新增、改写或重复调用。冻结 Scorer 不变，新审计也未改变评分结果。这是审计比较器的过强顺序假设，不是恢复数据损坏；执行顺序仍以原有序 Trace/调用关联核验。

真实只读核对 **631 份开工前文件、27 张表中 8,188 条原记录** Hash 全部保持。没有新文档摄取、Seed、迁移、权限更改、删卷或清库；仅向指定 `datapilot_test_portable_311` 追加本轮运行/证据/账本。旧 Gold/Seal、原 31/29、v3 Benchmark、Dev Smoke、P3 Evidence/Journal/Checkpoint 均未重新执行或覆盖。

本轮仅新增执行/交付记录：[机器摘要](research/p7-three-policy-live-smoke.json) 与本文；原始新 Permit、25 次 Provider usage、7 条签名终态记录、原评分、停止日志、独立复核、账本与数据前后 Hash 留在本地忽略目录 `artifacts/p7/three-policy-smoke-v1/live-20261029/` 及原包的 `private/results/live/`。完整 Prompt、凭据、签名 Key、业务原文不进入公开记录。

验证执行了原入口、7 次只读持久状态复核、原预算/收据校验、源码和数据 Hash、JSON/Markdown 引用、Ruff 和 Diff 检查。源码未变，未重复完整 pytest、浏览器或远端 CI；前轮测试不冒充本轮新执行。原失败日志和缺分状态全部保留。

下一步建议**另行授权最小 Scorer null-receipt 契约修复及本批原件的离线复评**，单独封存新 Scorer，保留本次原结果。英文相关性、Stop Hook 与回合余量问题先记录为产品 Bad Case；不据此自动调阈值或放宽安全。当前不具备“完整 Smoke 已通过”或进入 Gate 3 的结论，任何下一轮付费请求须新的独立授权。本轮在此停止。
