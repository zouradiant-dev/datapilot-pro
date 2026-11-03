# Combined 独立文档事实：再申请 Live 就绪清单

日期：2026-11-03。本文件**不是**执行许可。

## 已具备

- 产品路径：`document_facts_independent` / `DocumentGoal.independent_facts`；Report 在标志为 true 时跳过 `metric_topics_match`，仍校验 Required Fact citation/quotation。
- UI：确认页可显式选择“文档事实独立于指标”。
- 定向测试：Admission、独立合同、Fake 全路径、缺引述/篡改负例（见诊断文档）。
- 历史单例 `304ca32e…`：unavailable/partial，保留。
- 另一次有界 Live `17f5dc8a…`：业务 completed；Freeze 原始字节治理 FAIL；完整 CI NOT_RUN。

## 仍缺（全部满足前不得再跑）

1. 工作区候选源码（含 independent facts + admission + Formal 宿主确认）**完整 CI** 3.11/3.13 PASS。
2. 单一 Freeze：授权 SHA 与工作区**原始字节**一致（不能仅 LF 规范化一致后另造 Live Freeze）。
3. 新 Permit：1 Case / 1 Run / 8 calls / 18,000 Token / 并发 1 / 重试 0；不复用旧 Permit。
4. 页面显式勾选 `document_facts_independent=true`，文档子问题为 fact-scoped。
5. 负责人明确授权窗口；失败不重跑；账单保持 not_reconciled 直至对账。

## 明确不计入

- 不把 `17f5dc8a…` 并入旧 fresh-web-smoke 3/3。
- 不进入 Gate 3 / Formal 50 续跑。
- 不切换 Embedding，不改 P3/Gold/Scorer。
