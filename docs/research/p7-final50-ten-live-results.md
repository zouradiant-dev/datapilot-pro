# Final 50 修复后十题 Live 结果

日期：2026-11-04，Asia/Singapore。负责人明确授权不等待完整 CI，使用 `deepseek-flash` 请求 `https://api.deepseek.com`，十题各执行一次，串行，无自动重试。

**十题全部执行并结算，严格正确 9/10；053 严格失败。** 业务终态为 **2 completed / 7 partial / 1 unavailable**；没有 not_run、unknown 或安全违规。没有将终态正确等同于全部证据与事实正确。

## 逐题实际结果

| Case 后缀 | 新 Run ID | 业务终态 | 严格结果 | 调用 | Token |
|---|---|---|---|---:|---:|
| 031 | `91862b23-9f6e-5ab0-986a-0510aad0c7b2` | partial | PASS | 3 | 4,378 |
| 032 | `51bfb3cb-faec-5130-83a8-a8791b8a72fe` | partial | PASS | 4 | 6,543 |
| 033 | `528ae8ea-5e7a-5626-9279-5f32fc7218b8` | unavailable | PASS | 4 | 6,526 |
| 035 | `921f3173-fd2f-5ad0-b942-0d5b21521558` | partial | PASS | 4 | 6,558 |
| 051 | `9870f907-be1d-5adc-81bf-9b6d9eb2686a` | partial | PASS | 4 | 6,652 |
| 052 | `b26477ba-f6fe-55e4-9ae1-203c0657ee2e` | partial | PASS | 4 | 7,099 |
| 053 | `125d1d6b-fb5e-5015-b6b1-8e7afb375d4b` | partial | **FAIL** | 4 | 7,588 |
| 054 | `00aceb76-fc17-5016-a479-fc9858ca3155` | partial | PASS | 4 | 6,967 |
| 068 | `81c533cb-1a01-57ff-ba81-9311224b1049` | completed | PASS | 3 | 4,242 |
| 069 | `21ee44d0-d35d-584b-ab6e-d10437bb010b` | completed | PASS | 4 | 6,380 |

完整 Case 前缀为 `p7-holdout-v3-`。原问题、指标请求、事实与原 Gold 保留；051、052 使用前轮已验证的独立政策事实合同，其余八题沿用准备合同。十题均重新绑定本批可信范围确认，不复用旧 Run 或旧 Permit。

## 051、052 的真实业务证据

051：使用量 **205 events** 经 P3 verified，政策事实与引用验证通过；收入仍为 `amount_unit_unconfirmed`，未补猜金额单位。

- Evidence：`d902cd96-c5b8-4d54-a31b-b63098c9176f`
- Verification：`c022e32c-e78d-4c84-88a4-ab919ad745ac`

052：收入 **744.33 CNY** 经 P3 verified，发票政策事实与引用验证通过；客户流失仍为 `history_unconfirmed`，未把政策当作完整合同历史。

- Evidence：`7809d563-0e96-44b7-8bb7-ad070c370eea`
- Verification：`2c1e10ac-6841-4d73-aab3-67986ade9851`

## 053 的实际失败链

合同要求分别核验“赠送额度用途”和未承诺的事故赔偿比例。fact_1 有宿主确认的原文与引用，fact_2 没有证明，必须保持未验证。

实际模型检索到了授权文档并读取原文，最后提交 `submit_rag_result(outcome="insufficient")`，收据与 RAG 任务均为不足；没有 complete 提交、供应商错误或 unknown。当前冻结合同的 `partial_evidence_policy` 为默认 `legacy`，Report 没有保留已知的 fact_1，最终只展示 P3 收入 **744.33 CNY**。

因此虽然终态仍为 Gold 要求的 partial，报告没有 Gold 要求的文档事实与引用，且冻结 Gold 的 `retrieval_expected` 为 complete，严格维度 `business`、`citations`、`fact_coverage`、`retrieval_contract` 均未通过。失败分类为 `rag_retrieval_failure`。这是部分证据可用性与检索完成契约的实际缺口，不是此次额外授权引用规则导致的失败，也没有错误宣布整体 completed。

本轮不修改合同、Gold、Prompt 或评分以修正该成绩，不重试 053。后续可单独审计已有 `partial-facts-v1` 的适用性及检索收据与业务部分完成的边界；需分别保留缺失事实和可验证事实，不能强制模型提交 complete。

## 调用与授权核验

| 项目 | 授权上限 | 实际 |
|---|---:|---:|
| Run | 10，各一次 | 10 个唯一 Run |
| Provider 调用 | 80 | **38** |
| Token 单位 | 180,000 | **62,933** |
| 单 Run 调用 | 8 | 最大 4 |
| 单 Run Token | 18,000 | 最大 7,588 |
| 并发 | 1 | 1 |
| SDK / 外层重试 | 0 / 0 | 0 / 0 |

Input **58,569**，Output **4,364**，Cache read **32,768**。38 个模型调用都有完整 usage、唯一供应商响应 ID，Journal 调用状态均 complete；总用量与原 Ledger、Collector 和逐题汇总一致。另有 48 条工具调用记录。实际账单状态为 **not_reconciled**，Token 不是账单金额。

Provider 响应均记录 `model_name=deepseek-flash`；`model_provider=openai` 是 LangChain adapter 标签，实际宿主配置为 `model_provider=deepseek` 和本次授权端点。继续使用原 Gateway、DurableLedger 与 NativeTransport，没有 Fake 决策介入本批执行。

每题先由原 Host 创建 `awaiting_review`，此时模型调用为 0，再经原独立执行审批运行；本批是原 Host/Coordinator 的 CLI 路径，不宣称页面点击验收。所有异步调用共享一个事件循环，未重新派发任何题目。

执行窗口为 **14:18:08–14:22:38 +08:00**。普通业务失败 053 被保留，其余未执行任务继续。批次结束已创建 STOP 和独占派发 Claim，不再使用剩余额度。

## 源码、评分和采集身份

- Campaign：`p7-final50-repaired-ten-live-v1-20261104`
- Scorer：`p7-current-authorized-citations-v2`
- Binding SHA256：`01334a7e4d54a60dfec081a10f2812b0791b974a8ba0e519580683cb1f030923`
- 当前源码 Manifest SHA256：`dd4096ab40133022873c9bfdab20466ddc03e65a7cdc6daecf9afc5516b13e6c`
- 生产 Python 文件：112 个；另绑定评测入口、原评分依赖、pyproject/uv.lock、原输入/Gold/pins 和准备合同。
- Git HEAD：`2628b612a8977a0d21695e18b14f06ad4c82e0c5`，有此前保留的工作区修复；本批源码身份以新工作区内容 Hash 为准，不冒称该 HEAD 的旧 CI 覆盖当前源码。

执行前和逐题派发前检查绑定，结束后再次核验，漂移 0。10 份新签名采集的 HMAC、全部调用 payload Hash、报告合同 Hash、完整 usage 与预算均核验通过。采集复用原 Inspector 和 Run lease，评分保留 P3、授权、事实、因果及调用完整性判断。

新版评分允许真实授权的额外引用，精确率单列；它在本批付费执行前已冻结。旧评分、Gold、Seal、STOP 与历史结果未被覆写。本批是已暴露案例的修复后回归，不是新的独立 Holdout，也没有合并或重写原 Final 50 成绩。

## 交付与停止状态

- [机器结果、逐题维度、P3 引用和 Artifact SHA256](p7-final50-ten-live-results.json)
- 本地完整证据：`artifacts/p7/final50-ten-live-20261104/`
- `binding.json`、`permit.json`：本批身份与负责人授权。
- 各 Case 目录：新配置、审批前状态、审批返回、签名采集、score 和 result。
- `execution.log`、`summary.json`、`verification.log`、`STOP`：真实执行与核验记录。

**严格结果 9/10，十题执行已收官。Full CI：NOT_RUN（负责人明确接受不等待）；账单未对账；独立业务质量和整个 P7 的最终验收不由这批回归自动推定。** 本轮没有修改产品源码、合同、Prompt 或评分规则，没有追加 Run、重试、Commit/Push、进入 Gate 3 或开展其他实验。
