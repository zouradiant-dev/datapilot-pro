# P7 Fresh DeepSeek Web Smoke 准备计划

2026-11-02，分支 `p7-engineering-candidate-v1`，源码 Commit **`2f71dcb346cc527d0dd39bb5293029c2fe16ae92`**。本轮只做冻结、三案例设计、非付费预检和授权模板；**未调用任何付费模型，未创建 Live Run**。

机器计划：[p7-fresh-deepseek-web-smoke-plan.json](p7-fresh-deepseek-web-smoke-plan.json)  
完整私密证据：`artifacts/p7/fresh-web-smoke-v1/private/`（local-only）

## 1. 基线

| 项目 | 结果 |
|---|---|
| 本地 / 远端 HEAD | `2f71dcb346cc527d0dd39bb5293029c2fe16ae92`，一致 |
| CI #29 | [41383487439](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41383487439)，attempt 1，success |
| 3.11 / 3.13 | 各 1730 收集 = 1342 非集成 + 388 集成；各 1667 passed、63 skip、0 failed/errors |
| 原 60 项失败测试 | 60/60 存在且通过 |
| 当前工作区 | 无已跟踪源码修改；新增本报告/JSON 为未跟踪 |

CI 与源码身份匹配；本轮没有源码变化，因此完整 CI 不重跑。若后续增加 Web permit gate，必须重新跑完整 CI，不能用 CI #29 证明新源码。

## 2. 三条新案例

三条均为**新的合成工程 Smoke**，不是 Holdout，也不构成业务质量成功率。新 Dataset `ea9efaf0-854f-5287-8d42-cca8ca0efaf1` v1，新 Corpus `3fd3e8c1-1105-4c43-bc59-2913786a4f53`。

| Case | 类型 | 目标 | 独立预期 | 当前状态 |
|---|---|---|---|---|
| `fresh-web-01` | SQL-only | 2026-09 已支付 CNY 账单收入，右开窗口，排除 unpaid/USD/10 月 | **completed，803.35 CNY**，P3 verified，无文档引用要求 | 阻塞：新 Dataset 的语义/指标未确认 |
| `fresh-web-02` | RAG-only | 企业版退款审核时限，授权原文定位，不推断个人版 | **completed，7 个工作日**，Chunk/行/源版本匹配 | Goal 已生成但 `pending_confirmation`，未确认/未审批 |
| `fresh-web-03` | SQL+RAG | 同月收入 + 文档事实解释；不要求无依据因果 | **completed，803.35 CNY + 7 个工作日引用**，P3 verified；因果不升级 | 阻塞：定义未确认，且尚未生成 Goal |

### SQL-only Gold

独立 SQL 对原件计算，不是从 Agent/P3 输出反推：

```sql
SELECT COALESCE(SUM(amount_cents),0)
FROM uploads.u_ea9efaf0854f52878d42cca8ca0efaf1_v1_t1
WHERE payment_status='paid' AND currency='CNY'
  AND invoice_date >= DATE '2026-09-01'
  AND invoice_date < DATE '2026-10-01';
```

结果 **80,335 分 = 803.35 CNY**（Decimal）。排除：unpaid 50,000 分、USD 10,000 分、2026-10-01 的 99,999 分。源 CSV SHA256 `dd197a51b949a0e19f38eae9583215cc5c4a824c4a2963cd7e58d29b9f095c6a`。

### RAG-only Gold

合成原文：

> 企业版退款申请须在 7 个工作日内完成审核，退款金额按原支付币种原路退回。

文档还含干扰句“个人版退款申请须在 3 个工作日内完成审核。”，不得把 3 个工作日当作企业版答案。

| 定位 | 值 |
|---|---|
| Source | `2c794fb60592a71e5e6d7335e01327e77de933f2297e00750c189eaa227ef51c` |
| Document | `5d60eb04b8bf637c7b9a60b21533b8c90e9ded5bca92451ceaff10c972af4a33` |
| Chunk | `55469a84ebaa10725d40054188191836b62cc878f974f530fab24bac7f541b31` |
| 行 | 1–7；目标句在第 3 行 |
| IndexVersion | `223be2d08a0fd76803c4aabf61ad7a4548db411b466d4a7bb2b017f76459de88` |
| Source SHA256 | `b9fa3ebfef587454c116913e2956289caa86be3101aff5069e590140121858f0` |
| Embedding SHA256 | `882c137ae33ff7d60db2e8b1794b3161363c7072dfa84856dcbf306572ee8ae4` |

合法拒答/不足条件：

- 只引用个人版 3 个工作日 → 不正确；
- 没有授权原文或无法定位 → `unavailable/partial`，不得补写；
- 目标合同确认与执行审批任一缺失 → 不执行；
- 文档背景不得升级为收入因果证明。

### 完成判定

只有原 Host/Verifier/Report 的 `completed` 才计完成；模型自述、RAG Worker 收据或非空检索都不算。SQL-only 要求 P3 verified 数值/单位/窗口；RAG-only 要求事实覆盖和可核验引用；SQL+RAG 要求两者同时满足。任何失败保留原记录，不重跑。

## 3. Web 真实模型入口审计

| 检查 | 结果 |
|---|---|
| `datapilot-web launch --mode live` | 存在；设置 `DATAPILOT_LLM_MODE=live` |
| Live Settings 校验 | 通过：key 存在、model/base URL 合法 |
| 模型 transport | `NativeTransport`，无 Fake fallback |
| Gateway / 预算 | 每 Run `Gateway` + `BudgetLedger` + `DurableLedger` |
| 每 Run 上限 | 8 calls / 18,000 Token / 1200 output / 30s timeout |
| SDK 重试 | `max_retries=0` |
| Thinking / temperature | disabled / 0 |
| MCP 子进程凭据 | `server_environment` 不含 API Key；实测 keys 无 `DATAPILOT_API_KEY` |
| RAG Embedding | 新 Corpus 为真实本地 ONNX/BGE，`embedding_fixture=false` |
| SQL 数值 | 受控 P3 SQL/Decimal，不由 LLM 心算 |
| 审批前模型调用 | ChatService 仍是 Rule-only；无预审批模型调用 |
| 浏览器密钥 | 页面仅显示 mode，不接收 key |
| **Campaign Permit/全局上限** | **缺失**：Web 无 permit 检查，也不强制 3 Run/24 次/54k/1800s |
| **并发** | 当前 `max_parallel_workers=2`；拟议 concurrency=1 需显式 env override |

结论：**真实模型 Web 链路具备工程接线，但当前不具备安全执行一次性 Campaign 的技术闸门**。已用独立 host owner `smoke-livecheck` 在默认端口实际启动 Live Web 并读取 `/health`：`mode=live`、`durable=true`；启动过程未创建 Run、未发送模型请求，随后已恢复 Fake Demo Host。

## 4. 非付费预检实际结果

| 检查 | 结果 |
|---|---|
| Git / CI 基线 | PASS，匹配 |
| Web Live transport/config | PASS（未发送请求） |
| Web Live 实际启动 | PASS：独立 owner、默认端口，`/health mode=live`；0 Run/0 provider calls |
| 新 Dataset 导入 | PASS：6 行，`smoke-fresh-202609` v1 |
| 新 Corpus 摄取 | PASS：真实 BGE，`embedding_fixture=false` |
| SQL Gold | PASS：803.35 CNY（独立 SQL/Decimal） |
| RAG Gold | PASS：Chunk/行/源 hash 已固定 |
| RAG Goal 合同 | PASS 可生成；状态 `pending_confirmation`，`can_confirm=true`，未确认 |
| SQL/组合 Goal | **PENDING**：Dataset metrics=0，必须先确认语义/指标 |
| 新 Campaign Run | 0（未创建任何 Live/Fake Smoke Run） |
| 付费调用 | **0** |
| 历史 Holdout/STOP/Live | 未重跑、未恢复、未修改 |
| 日志/Inspector/Collector | 原 Web/Inspector 机制可用；未新增 Collector |

新数据只追加到隔离 Demo 实例，没有清理、迁移或 Seed 历史库；新 Dataset/Corpus 身份唯一。RAG 预检合同由 Fake Web 生成，仅用于验证合同字段，不冒充 Live 执行。

## 5. 预算与费用

| 项目 | 拟议 | 当前契约 | 兼容性 |
|---|---|---|---|
| 每 Run 调用 | 8 | `max_model_calls=8` | **MATCH** |
| 每 Run Token | 18,000 | `max_total_tokens=18000` | **MATCH** |
| 输出/attempt | 1200 | `max_output_tokens=1200` | **MATCH** |
| SDK/外层重试 | 0 | `max_retries=0`；无外层重试 | **MATCH** |
| 并发 | 1 | 默认 `max_parallel_workers=2` | **MISMATCH**；可用 env 覆盖为 1，但需冻结 |
| Campaign 3 Run/24 次/54k | 3/24/54,000 | Web 未强制 | **GAP** |
| 任务/整 Campaign 时限 | 180s / 1800s | Web 未强制 | **GAP** |
| 一次性 Permit | 必需 | Web 无 permit gate | **GAP** |

### 费用

官方页面：[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)（2026-11-02 读取）。

- 模型别名：`deepseek-flash`；官方页面报告版本 `DeepSeek-V4.1-Flash-1017`。
- 峰值 USD/百万 Token：cache hit input **0.006**、cache miss input **0.3**、output **1.2**；off-peak 为半价。
- 54,000 个“计账单位”按最高 output 费率保守估算：**≤ 0.0648 USD**。
- 这是预算上界，不是供应商账单、缓存状态或实际 Token 的保证；实际账单状态 **not_reconciled**。
- 执行前必须重新核对价格；若变化超过授权文本的范围，停止。

## 6. 业务确认与 Goal 状态

### 未确认定义（PENDING）

新 Dataset 当前 `metrics=0, semantics=0`。已准备但不登记为已确认：

- SemanticDraft SHA256 `087f8470a7767a63e02adcef3267d80c5676f9510101d346a4b10819dabde61e`
- MetricDraft SHA256 `e143653681bff867e8fb68f69a4370cf092348bc7dee00b4ac308f16e0dae7ed`
- 映射：`invoice_id→record_id`、`amount_cents→amount`、`invoice_date→invoice_date`、`payment_status→payment_status`、`currency→currency`；`amount_storage=minor`；`currency=CNY`；`paid=["paid"]`；coverage `[2026-09-01,2026-10-01)`。
- 精确审批清单在 `candidate-definitions.json` 的 `approval_required`，未调用 `/semantics/confirm` 或 `/metrics/confirm`。

### RAG Goal

- Conversation `d4d07c6f-7f5e-406c-b8b2-073ac203075a`
- Message `94c80f8e-7889-4313-b297-27c0bb8f79ec`
- Contract `ba277b5e2601e7163a90e3d4b2a94118968264b036d3fdfb0181e3058a703c84`
- 状态：`pending_confirmation`；三项用户确认、Goal 确认、独立执行审批均未完成。

SQL-only 与 SQL+RAG 在定义确认前无法生成目标合同；不能以“Corpus 已存在”代替目标范围确认。

## 7. 真正剩余阻断

1. **没有 Web 侧一次性 Permit/准入闸门**：无法硬性限制 3 个 Run、24 次调用、54,000 单位、1800 秒和费用上界；页面可以继续创建额外 Run。
2. **新 Dataset 的语义映射与 Metric v1 未确认**：SQL-only/SQL+RAG 无法生成或验证目标合同。
3. **RAG Goal 未确认、执行未审批**；SQL/组合 Goal 尚未生成。
4. **并发默认 2**：与拟议 concurrency=1 不一致；需 `DATAPILOT_MAX_PARALLEL_WORKERS=1` 并重新冻结 Host settings hash。
5. **费用/账单未对账**：0.0648 USD 只是按官方峰值费率的保守估算；执行前需重核。

最小方案（本轮不实施）：

- 在现有 Web `launch`/`approve` 路径前增加一个 host-bound one-shot permit 检查，绑定 Campaign/Freeze/Case/Dataset/Corpus hash、3 Run、24 calls、54k、1800s、有效期与 no-rerun；复用原 Store/Outbox，不新建 Scheduler/Runner/Ledger。
- 由负责人确认 SemanticDraft/MetricDraft 后，经原 `/semantics/confirm`、`/metrics/confirm` 登记；随后在页面生成 SQL/SQL+RAG Goal，逐条确认并独立审批。
- 使用 `DATAPILOT_MAX_PARALLEL_WORKERS=1` 启动并冻结 Host settings；执行前重核官方费率。

任何此类代码变更都需要新的完整 CI；本轮没有修改产品源码。

## 8. 下一步精确授权文本（模板，尚未生效）

> 授权 DataPilot Pro Campaign `p7-fresh-web-smoke-v1` / Freeze `p7-fresh-web-smoke-v1-6bf94e733bd7`，仅执行 `fresh-web-01`、`fresh-web-02`、`fresh-web-03` 各一次，使用隔离 Dataset `ea9efaf0-854f-5287-8d42-cca8ca0efaf1` v1 / Corpus `3fd3e8c1-1105-4c43-bc59-2913786a4f53`。
>
> Provider DeepSeek，端点 `https://api.deepseek.com`，模型 `deepseek-flash`，thinking disabled，temperature 0，max_output_tokens 1200/attempt，SDK 与外层自动重试 0，并发 1。
>
> 最多 3 个业务 Run；每 Run 最多 8 次模型调用尝试 / 18,000 Token 计账单位；Campaign 最多 24 次 / 54,000 单位；单任务 180 秒、Campaign 1800 秒；按 2026-11-02 官方峰值费率的估算费用上界 0.0648 USD，非实际账单保证。
>
> 有效期：负责人批准后 2 小时，一次性；不重跑、不续跑、不挪用剩余额度。
>
> 数据范围：仅上述合成 Dataset/Corpus、用户问题、授权文档片段、工具结果及审批/版本元数据；不发送其他 Dataset/Corpus、历史 Holdout/Gold、API Key、数据库凭据。
>
> 执行入口：真实 Web 页面；目标确认与执行审批分离，均由页面真实点击完成，不使用 API 审批兜底。
>
> 停止条件：权限/来源/版本/hash 异常、伪造引用、False Completion、身份漂移、预算/账本异常、Provider/网络未知结果、恢复冲突、超时或费率变化。unknown-outcome 保持保守预留，不自动重发。
>
> 该授权仅适用于本 Campaign/Freeze/上述三条案例；不适用于其他模型、数据、Prompt、Scorer、Holdout、Gate 3 或后续阶段。

模板文件：`artifacts/p7/fresh-web-smoke-v1/private/authorization-template.json`，`authorized=false`。**上述文本在 Permit 创建前不构成执行授权。**

## 9. 最终状态

| 项目 | 状态 |
|---|---|
| **Engineering Preflight** | **BLOCKED**（Web 接线/数据/Gold 检查通过，但缺少 Campaign permit/全局上限） |
| **Business Definitions / Goal Confirmation** | **PENDING** |
| **Ready for Live Authorization** | **NO** |
| **Paid Model Calls** | **0** |
| **Live Smoke** | **NOT_RUN** |
| Independent Business Quality | **PENDING** |
| DeepSeek Live Gate | **PENDING** |

## 10. 冻结与 Hash

| 项目 | 值 |
|---|---|
| Freeze ID | `p7-fresh-web-smoke-v1-6bf94e733bd7` |
| Freeze SHA256 | `6bf94e733bd7804123126d55eb34c3e856353ac3c363bf8cbe9dbc74d37af925` |
| `model.py` SHA256 | `5363ab5e31937d972432285fe6452fc5e42e3f6c842df2e019798b0a5764de40` |
| `test_fake_rag_decision.py` SHA256 | `a18b6b68e9c2ca9c8df4f7e1bc25f2bed5192db4e1246f0f5a8aef1ee17b48ad` |
| Source manifest | `1548da51310d09e4f9ac4af854e456a1209a8dc218908bcef2d0729d7b0116fc` |
| Cases SHA256 | `4ca243d70d5b90c5c07c00793efe2dc8e4eb0f0077279f3f263f656a3f27113d` |
| SQL/RAG Gold | `803.35 CNY` / `7 个工作日` |
| BGE model | `1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38` |
| BGE tokenizer | `48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26` |
| Public plan JSON | `c21cb3269d82120881989c892d4fbeef3cdd3edfdddd2a0304dc16791f58bfc5` |

未提交、未 Push、未创建 PR。8 份历史未跟踪研究文件保持原样；私密 artifacts 不进入公开文档。

## 11. 停止边界

本轮未进入 Live、Holdout、Gate 3、Qwen 或付费模型；未修改产品源码、Prompt、Verifier、Scorer、Embedding、预算算法、迁移或历史 Gold/Seal。等待负责人对以下两项分别作出明确决定后才能继续：

1. 确认新 Dataset 的语义映射/指标与 RAG Goal；
2. 批准最小 Web permit gate（或提供等价的硬性一次性执行控制）并授权本次 Campaign。
