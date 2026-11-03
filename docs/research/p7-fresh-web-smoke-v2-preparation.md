# Fresh Web Smoke repair-v2 准备包

Campaign `p7-fresh-web-smoke-repair-v2`。状态：**PREPARED / NOT EXECUTABLE**。本轮 0 次付费调用，未创建有效 Permit，未确认或执行任何 Run，未修改源码，未 Commit/Push。

## 1. 身份与 Freeze

| 项目 | 值 |
|---|---|
| 新 Campaign | `p7-fresh-web-smoke-repair-v2` |
| Cases | `repair-web-01` SQL-only；`repair-web-02` RAG-only；`repair-web-03` SQL+RAG |
| 源码 Commit | `434dc1870925b4740b51078804703f287f058dcd` |
| Workspace HEAD | `4cf867ee56b837a170a60b0d2abe2534394bb520` |
| Base Commit | `cccd829f7240b9ff56b7d3817c7b716c39616108` |
| 新 Freeze | **`p7-fresh-web-smoke-repair-v2-7b229020c7c2`** |
| Freeze SHA256 | **`7b229020c7c265866921b1685cb7ec2b2e598489345dd4073e258152b710d2f2`** |
| Source manifest SHA | `81f7badfc63b936bd5a51e3758e3efa4f6054b9e5a77a94a7e5a826ec67c0964` |
| Parent Freeze | `p7-fresh-web-smoke-admission-v1-483bc675998f` / `483bc675998fa4c2e6c2df4a9c95b972c2c05b064f9c2768cd5e52a7a858a841` |
| CI | **PENDING**：新 commit 未 Push，未运行新 CI；旧 #30 仅覆盖 `cccd829f7240b9ff56b7d3817c7b716c39616108` |
| Remote | `cccd829f7240b9ff56b7d3817c7b716c39616108`；ahead 2 |

Freeze 已固定源码/运行文件、`uv.lock`、BGE model/tokenizer、数据与定义、候选、Gold、Provider/预算和旧结果引用。**Host settings hash、正式 Goal contract hash、Permit、批准/到期时间均 pending，未伪造。**

## 2. 已登记数据与定义

- Dataset `ea9efaf0-854f-5287-8d42-cca8ca0efaf1` v1；Source SHA `dd197a51b949a0e19f38eae9583215cc5c4a824c4a2963cd7e58d29b9f095c6a`
- Semantic v1 definition SHA `2da3a80810a17f679aa9c67e8d32d01772866cd4927651187c3e1dbf019f1364`；Metric `paid_invoice_revenue` v1 definition SHA `f2178982580185dbd47994e8c6d9ff1e80656292c915efcb834be80f7ef6e9a1`
- Corpus `3fd3e8c1-1105-4c43-bc59-2913786a4f53`；IndexVersion `223be2d08a0fd76803c4aabf61ad7a4548db411b466d4a7bb2b017f76459de88`
- Document `5d60eb04b8bf637c7b9a60b21533b8c90e9ded5bca92451ceaff10c972af4a33`；Source ID `2c794fb60592a71e5e6d7335e01327e77de933f2297e00750c189eaa227ef51c`；Source SHA `b9fa3ebfef587454c116913e2956289caa86be3101aff5069e590140121858f0`；Chunk `55469a84ebaa10725d40054188191836b62cc878f974f530fab24bac7f541b31`
- BGE：`BAAI/bge-small-zh-v1.5/Qdrant-onnx`，512 维，revision `46fbe35...`，model/tokenizer SHA 与旧 Freeze 一致
- 窗口 `[2026-09-01,2026-10-01)`；paid/CNY；金额 minor；不计算 USD/MRR

## 3. 三条可审阅候选（全部未确认、未审批、run_id=null）

### repair-web-01 — SQL-only

- 路径：metric-only candidate，不生成文档 Goal v4 合同。
- 原问：`计算 2026 年 9 月已支付账单收入，按 CNY 元返回；仅统计 payment_status=paid 且 currency=CNY 的账单。`
- 窗口：`2026-09-01` 至 `2026-10-01`（不含）
- Metric：`paid_invoice_revenue` v1 / Semantic v1；单位 CNY
- 独立预期：**803.35 CNY**，仅经 P3 验证；Gold 不注入模型。
- 状态：`UNCONFIRMED_PREPARED`；`run_id=null`；`goal_contract_sha256=null`
- Candidate SHA：`517e2332f106f7e9a2b684f128af3f91717b7d5a4605cf0e83fa49814ba9f159`

### repair-web-02 — RAG-only

- 路径：Goal v4 待最终 Live Host 生成；当前无正式合同。
- 原问：`请依据授权文档说明企业版退款申请的审核时限，并给出原文定位；不要推断个人版。`
- Source：`5d60eb04b8bf637c7b9a60b21533b8c90e9ded5bca92451ceaff10c972af4a33`（refund-policy-2026.md）
- Required Fact：`企业版退款申请的审核时限`
- **用户审阅引述输入（非 proof）**：
  > 企业版退款申请须在 7 个工作日内完成审核，退款金额按原支付币种原路退回。
- 预期：`7 个工作日` + 对应授权原文引用；不得混用个人版 3 个工作日。
- `quotation` 是人工辅助输入，非已验证 proof；`citation`、`confirmation_ref` 必须由原 Host/MCP 在 Goal review 时解析生成。准备包不伪造。
- 状态：`UNCONFIRMED_PREPARED`；`run_id=null`；`goal_contract_sha256=null`
- Candidate SHA：`897840e987af918c163b25b7a23a4f9f39609140c627c8a8cd8287e452b557aa`

### repair-web-03 — SQL+RAG

- 原问：`计算 2026 年 9 月已支付账单收入（CNY），并依据授权退款政策原文说明企业版退款审核时限；不要把文档当作收入或因果证明。`
- 同窗口/metric，RAG 同 Source/Fact/引述
- 预期：**803.35 CNY** 且 **7 个工作日 + 原文引用**；文档不得作为收入数值或因果证明。
- 状态：`UNCONFIRMED_PREPARED`；`run_id=null`；`goal_contract_sha256=null`
- Candidate SHA：`6a6aaac65deabd5684b15836ff211cc03e13282e10fa95853b9ff6b784c39c32`

机器可审阅选择/ preview 见 `artifacts/p7/fresh-web-smoke-repair-v2/private/candidates.json`。

## 4. 旧结果保护

旧 Campaign `p7-fresh-web-smoke-v1` 保持：

- SQL `completed`；RAG `unavailable`；SQL+RAG `failed/blocked`
- 8 次调用 / 12,066 Token；旧 artifacts、STOP、Permit、Result 文档均不修改
- 旧 admission 三行保持；新 Campaign 当前 `0` 行
- 不续跑、不删除、不复用旧 Stop/Permit

## 5. 一次性付费授权草案（未生效，可复制文本见文件）

- `authorized=false`；`signature=""`；`approved_at=null`；`expires_at=null`
- Host settings hash、正式 Goal hash 均 pending
- 3 个 Run，每 Case 一次；`deepseek-flash`；Thinking disabled；temperature 0
- 每次输出 1,200；SDK/外层重试 0
- 每 Run 8 calls / 18,000 Token；总计 24 / 54,000
- 并发 1；`max_parallel_workers=1`；失败不自动重跑
- Campaign 同一 Permit 最早 admission 起 1,800 秒；单 Run 180 秒不是硬终止
- STOP/取消按现有机制；已发出 Provider 请求可能已执行/计费；unknown 保守保留不重发
- 官方价格页 `https://api-docs.deepseek.com/quick_start/pricing/`（2026-11-02）；峰值 cache hit `$0.006/M`、miss `$0.3/M`、output `$1.2/M`；最坏估算 `$0.0648`，不是账单
- 只发送三个合成问题、授权数据/文档片段、工具结果及必要版本元数据；不发送 Gold
- Agent 仅在额外授权后代为页面确认/审批，不声称负责人亲手点击

完整草案：[authorization-draft.md](artifacts/p7/fresh-web-smoke-repair-v2/private/authorization-draft.md)；未签名 Permit 模板：[permit-template.json](artifacts/p7/fresh-web-smoke-repair-v2/private/permit-template.json)（`authorized=false`, `signature=""`, `template_sha256=5ab7908df66435c3d87cad64421bc034e6d10adf21cfc6f9e37ef5d6244c4295`）。

## 6. 正式执行顺序

1. 核对冻结源码的完整 CI 结果；旧 CI #30 不能作为新源码证据。
2. 负责人批准最终案例、quotation 辅助条件及付费边界。
3. 固定最终 Host 配置，按原机制生成 host settings hash 并签署新 Permit。
4. 最终 Live Host 生成并核对候选/合同。
5. 页面完成 Goal 确认，再独立审批 Run。
6. 顺序执行三案例，保留真实失败，不现场优化。
7. 完成/停止条件后停止 Live Host。

完整步骤：[execution-order.md](artifacts/p7/fresh-web-smoke-repair-v2/private/execution-order.md)。

## 7. CI / Host / Goal 待核验

- 新源码：**未 Push、未运行新 CI**。旧 CI #30 仅覆盖 `cccd829`，不得用于新执行。
- 新 CI 预期：**1748 tests = 1344 non-integration + 404 PG**。
- `host_settings_hash`: **PENDING_FINAL_LIVE_HOST**
- 正式 Goal contracts/合同 SHA：**PENDING_FINAL_LIVE_HOST**
- Goal confirmation：**NOT_CONFIRMED**
- Execution approval：**NOT_REQUESTED**
- 新 Permit：**UNSIGNED_TEMPLATE_ONLY**
- 因此本准备包**不可执行**；CI 通过也不自动等于可执行，仍需负责人和 Permit。

## 8. 轻量验证

- Freeze SHA 重新计算一致；27 个源码/依赖文件 Hash 与源码 Commit 一致
- 引述逐字存在于授权原件；数值 Gold 与独立 SQL 结果一致
- 三候选 `CreateTask`/`ChatSelection` 离线结构校验通过；citation/confirmation 未填写
- 旧 admission 3 行不变；新 Campaign 0 行；旧 STOP/Result 未触碰
- 模板 `authorized=false`、签名为空、时间/主机 Hash 为空；无付费调用
- 仅做 JSON/Hash/Diff 轻量验证；未跑 pytest、未启动 Live Host、未 Commit/Push

## 9. 文件位置

- Freeze：`artifacts/p7/fresh-web-smoke-repair-v2/private/freeze.json`
- Candidates：`artifacts/p7/fresh-web-smoke-repair-v2/private/candidates.json`
- Gold：`artifacts/p7/fresh-web-smoke-repair-v2/private/gold.json`
- Definitions：`artifacts/p7/fresh-web-smoke-repair-v2/private/definitions.json`
- Budget：`artifacts/p7/fresh-web-smoke-repair-v2/private/budget.json`
- Permit template：`artifacts/p7/fresh-web-smoke-repair-v2/private/permit-template.json`
- Authorization draft：`artifacts/p7/fresh-web-smoke-repair-v2/private/authorization-draft.md`
- Execution order：`artifacts/p7/fresh-web-smoke-repair-v2/private/execution-order.md`
- Preflight：`artifacts/p7/fresh-web-smoke-repair-v2/private/preflight.json`
