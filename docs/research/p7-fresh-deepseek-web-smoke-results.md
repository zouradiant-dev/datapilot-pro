# Fresh DeepSeek Web Smoke 实际结果

日期：2026-11-02（Asia/Shanghai）。Campaign `p7-fresh-web-smoke-v1`，源码 Commit `cccd829f7240b9ff56b7d3817c7b716c39616108`，CI #30 PASS，Freeze `p7-fresh-web-smoke-admission-v1-483bc675998f`。

本轮实际执行 3 个正式 Run：**1 completed、1 unavailable、1 failed**。这是三条有界 Live Smoke 的实际结果，不是稳定成功率或独立业务质量结论。

## 1. 授权与执行边界

| 项目 | 实际 |
|---|---|
| 负责人授权 | 2026-11-02 18:08:56 +08:00，2 小时有效 |
| Permit 批准/到期 | 约 18:10:49 / 20:10:49 +08:00 |
| Campaign 起止 | 18:16:10 至 18:31:12 +08:00；共享截止 18:46:10，未触发 |
| 模型 | `deepseek-flash`，`https://api.deepseek.com`，Thinking disabled，temperature 0，max output 1200，重试 0 |
| 并发 | Host `max_workers=1`，`max_parallel_workers=1` |
| 准入 | 3 个 Permit Case 各一个 Run；无第 4 个、无未知调用、无重试 |
| 审批 | SQL/RAG/combined 均由页面点击创建/确认及执行审批；Agent 代为操作，不宣称负责人亲手点击 |
| Provider usage | 8 次模型调用，全部 `usage_complete=true`，无 unknown |
| 实际账单 | **not_reconciled** |

## 2. 三条结果

| Case | 类型 | Goal/候选 | Run | 状态 | BusinessCompletion | 模型调用/Token |
|---|---|---|---|---|---:|---:|
| `fresh-web-01` | SQL-only | metric-only candidate | `e3af5452…` | **completed** | **completed** | 1 / 615 |
| `fresh-web-02` | RAG-only | Goal `e38f2e25…` | `cc12be91…` | **unavailable** | **unavailable** | 3 / 4,332 |
| `fresh-web-03` | SQL+RAG | Goal `795ad4b5…` | `fc2201a1…` | **failed** | **blocked** | 4 / 7,119 |

### 2.1 SQL-only — completed

- Conversation `de28484d-09fd-41c1-9e2b-303f88769b57`；Message `cd0155d9-e626-4db5-a2ae-74b76a81a763`。
- 数值：**803.3500000000000000 CNY**，窗口 `[2026-09-01,2026-10-01)`。
- Evidence `3a90d2cc-8786-49fc-b406-2ff94a614086`；Verification `06fae87f-ecb2-481a-b323-e2255995dfc2`。
- SQL / Report tasks succeeded；无 citations（SQL-only）。
- Provider model `deepseek-flash`，finish_reason `stop`；1 call，615 tokens（input 506/output 109，cache hit 256）。

### 2.2 RAG-only — unavailable（Worker complete，但业务未完成）

- Conversation `e3d2a83f-64a1-4775-99af-db30da630f5c`；Message `506e7bc8-22ba-459f-8e22-ce76ae4c8ba0`。
- Goal `e38f2e25cd2a72eb01b6f632c3a7f5b81672e16766eb0f64de81fd6db6f304e1`；页面确认后独立审批。
- 实际执行：`search_documents` 返回 1 个文档（返回值里的 `document_id` 为 Chunk `55469a84…`，而 Goal 的 CitationPolicy 固定 Source Document `5d60eb04…`），模型 `submit_rag_result` 提交 complete；RAG task/Report task succeeded，但最终：
  - `business_completion=unavailable`
  - `missing_evidence`：`matching_document_or_metric_evidence_missing`、`required_document_source_missing`、`document_fact_unverified:fact_1`
  - Report `facts=[]`、`citations=[]`
- 3 次模型调用，4,332 tokens（input 4,054/output 278，cache 1,792）；finish reasons `tool_calls`, `tool_calls`, `stop`。
- 这是 **RAG Worker complete ≠ 业务 completed** 的实际反例；未重跑。

### 2.3 SQL+RAG — failed（BUDGET_EXCEEDED）

- Conversation `f29358d5-6c16-48b4-aca8-941e2a1b06b2`；Message `8898d9a1-5609-4f83-b652-425fda4a0aff`。
- Goal `795ad4b582719401d6f231cc707407ac53d3af9c0c643b7e99f899c5beffc008`；页面确认后独立审批。
- 实际：SQL task succeeded；RAG documents task **failed**；Report task succeeded 但 `report_available=false`，`business_completion=blocked`，最终 `status=failed`，错误 `BUDGET_EXCEEDED`。
- 事件显示：RAG 3 次调用后 context compression 估算 12,131 tokens；root 剩余 10,881（18,000−7,119），下一预留需要 12,131+1,200=13,331，超过剩余额度，**在派发下一次模型请求前拒绝**；没有发生额外调用，也没有 unknown usage。
- 4 次模型调用，7,119 tokens（input 6,654/output 465，cache 4,096）；finish reasons 三次 `tool_calls`、一次 `stop`。
- 未重跑；SQL/RAG/combined 都没有第二次执行。

## 3. 工程链路、业务与证据分层

| 维度 | 结果 |
|---|---|
| 工程链路 | **2/3 Run 执行链路成功**（SQL、RAG）；combined 在 RAG 子任务因预算预留失败 |
| 业务完成 | **1/3 completed**（SQL）；RAG unavailable；combined blocked |
| 证据有效 | **1/3**（SQL P3 evidence/verification）；RAG/combined 无有效最终引用/报告 |
| 严格正确 | **1/3** |
| not_run | 0 |
| unknown calls | 0 |
| 自动重试 | 0 |
| 第 4 个 Run | 无 |

## 4. 调用与费用

| Case | Calls | Input | Output | Total | Cache hit | Peak estimate USD |
|---|---:|---:|---:|---:|---:|---:|
| SQL | 1 | 506 | 109 | 615 | 256 | 0.000207336 |
| RAG | 3 | 4,054 | 278 | 4,332 | 1,792 | 0.001022952 |
| SQL+RAG | 4 | 6,654 | 465 | 7,119 | 4,096 | 0.001349976 |
| **合计** | **8** | **11,214** | **852** | **12,066** | **6,144** | **0.002580264** |

- 按 2026-11-02 官方峰值费率（cache hit 0.006、miss 0.3、output 1.2 USD/百万）计算；实际执行落在 off-peak 时段，off-peak 估算约为峰值一半。两者都不是账单。
- **actual bill = not_reconciled**；未取得供应商账单，不声称实际扣费金额。
- 总调用/Token 远低于授权 24/54,000；combined 的失败是**单 Run root 预算预留**，不是全局超支。

## 5. 准入与 durable 证据

- `execution.web_smoke_admissions` 只有 3 行，Case 分别绑定唯一 Run/message/permit：
  - SQL `e3af5452…`，RAG `cc12be91…`，combined `fc2201a1…`。
- 每 Case 一个 Run；没有第四 Run、没有相同请求新 Run、没有自动重跑。
- Provider 全部返回 `model_name=deepseek-flash`；`model_provider=openai` 仅为 LangChain adapter 标签，实际 provider_id 为 `deepseek`。
- 所有 usage 完整；无 unknown-outcome；没有重发。
- 原始 Prompt/工具原文/凭据保留在私密 artifacts；公开报告仅保留必要身份、Hash 和统计。

- Campaign 三个 Case 已全部占满；执行后已创建本地 STOP 文件，Live Host 已停止，不再派发。

## 6. 结论与剩余

**本轮不是 3/3 Live Smoke 通过**：1 completed、1 unavailable、1 failed；只能报告为三条有界实际验证中的 **1/3 业务完成**，不能外推稳定成功率、独立业务质量或整个 P7 Gate。

- SQL 803.35 CNY 与已批准独立预期一致，P3 Evidence/Verification 有效。
- RAG 的 Worker 提交 complete 未转化为业务完成；Report 拒绝了缺失的 required document source/fact。
- Combined 在 RAG 预算预留处停止；没有越权、伪造引用、False Completion 或 unknown 自动重发。
- 没有重跑、没有现场修产品、没有新增代码或新 Smoke。
- Live Host 已停止；未 Commit/Push；未进入 Holdout/Gate3；未触碰历史 Docker/Gold/Seal/STOP/Run。

### 后续建议（非本轮执行）

1. 由负责人决定是否接受当前 1/3 结果作为本轮 Smoke 结论；**不能称为通过**。
2. 若继续，应单独审查 RAG source identity/fact coverage 与 combined 的 root budget 预留，不改本轮结果。
3. 任何修复都需要新源码、新 Freeze、新完整 CI 和新付费授权；不得复用本轮 Permit。
4. 实际账单待下载/对账后更新，当前明确 `not_reconciled`。
