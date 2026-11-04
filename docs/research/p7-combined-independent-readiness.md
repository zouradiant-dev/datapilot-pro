# Combined 独立文档事实：再申请 Live 就绪清单

日期：2026-11-03。本文件曾为**非执行许可**清单；同日负责人授权后已完成一次有界 Live。

## 已完成 Live（本轮）

- Campaign：`combined-independent-ci2628b61-v1`
- Case：`combined-ci2628b61-independent-01`
- Run：`c1946d22-1b70-4ae3-8d16-bb72a710490e`
- 结果：**业务 PASS + Freeze raw 对齐 + 完整 CI PASS**
- 公开记录：[p7-combined-independent-ci2628b61-live-results.md](p7-combined-independent-ci2628b61-live-results.md)

## 已具备（历史）

- 产品路径：`document_facts_independent` / `DocumentGoal.independent_facts`；Report 在标志为 true 时跳过 `metric_topics_match`，仍校验 Required Fact citation/quotation。
- UI：确认页可显式选择“文档事实独立于指标”。
- 定向测试：Admission、独立合同、Fake 全路径、缺引述/篡改负例（见诊断文档）。
- 历史单例 `304ca32e…`：unavailable/partial，保留。
- 另一次有界 Live `17f5dc8a…`：业务 completed；当时 Freeze 原始字节治理 FAIL，完整 CI 当时 NOT_RUN。
- **完整 CI PASS**：提交 `2628b612a8977a0d21695e18b14f06ad4c82e0c5`，[Actions #41629097042](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41629097042)，Python 3.11 / 3.13 均 success。

## 候选草稿状态

绑定 CI PASS 提交 `2628b61` 的草稿已签署并消费：

- Freeze ID：`p7-combined-independent-candidate-2628b612a897`
- Freeze SHA256：`f09f62363f9e2456c7bc79a5a8111826bb8898a0087d5b5db4dba9d914f47bc7`
- Permit：HMAC 签名，`authorized=true`，已消费 1/1 Run；STOP 已写入。

## 明确不计入

- 不把本轮或 `17f5dc8a…` 并入旧 fresh-web-smoke 3/3。
- 不进入 Gate 3 / Formal 50 续跑。
- 不切换 Embedding，不改 P3/Gold/Scorer。
- 本 Campaign **不得自动重跑**；新 Live 须新 Freeze/Permit/授权。
