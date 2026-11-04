# Combined 独立文档事实：CI 绑定 Live 结果（2628b61）

日期：2026-11-03。Campaign `combined-independent-ci2628b61-v1`，Case `combined-ci2628b61-independent-01`，Run `c1946d22-1b70-4ae3-8d16-bb72a710490e`。

**业务结果：PASS。源码冻结治理：PASS（raw 字节对齐 commit 2628b61）。完整 CI：PASS #41629097042。**
**账单：not_reconciled。**
**没有第二次 Run；不并入旧 fresh-web-smoke 3/3；不进入 Gate 3 / Formal 50。**

## 1. 授权与源码身份

- 负责人授权：本对话明确授权按就绪清单执行有界 Combined Live。
- Provider / model：DeepSeek / `deepseek-flash`；Thinking disabled；max_tokens 1200；自动重试 0；并发 1。
- Freeze ID：`p7-combined-independent-candidate-2628b612a897`
- Freeze SHA256：`f09f62363f9e2456c7bc79a5a8111826bb8898a0087d5b5db4dba9d914f47bc7`
- Git commit：`2628b612a8977a0d21695e18b14f06ad4c82e0c5`
- 工作区：对 Freeze 内 29 个文件写入 `git show` 原始 LF 字节后，`workdir raw SHA == freeze` 为 **29/29**（Windows autocrlf 检出曾为 CRLF，已纠正后再开 Host）。
- 完整 CI：[Actions #41629097042](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41629097042) Python 3.11 / 3.13 success。
- Case ID 说明：同库 `local-user` 上 `combined-repair-independent-01` 已由历史 Live 消费；本轮使用 `combined-ci2628b61-independent-01`，合同内容与草稿一致。

## 2. 合同与审批

- overall question 保持原问；
- `document_facts_independent=true` / `independent_facts=true`；
- 文档子问题：`请依据授权文档核验以下事实：企业版退款申请的审核时限`；
- `metric_goals` 保留 `["metric_1"]`；
- Required Fact / quotation 与授权退款政策原文一致；
- 合同确认与执行审批均经页面完成；`approval-proof.json` 记录 checkbox/按钮启用与点击前 `awaiting_review`。

证明：`artifacts/p7/combined-independent-ci2628b61-v1/private/live/contract-confirmed.json`、`approval-proof.json`。

## 3. 执行结果

| 项目 | 实际 |
|---|---|
| Run | `c1946d22-1b70-4ae3-8d16-bb72a710490e` |
| 最终状态 | **completed** |
| execution_status | **succeeded** |
| BusinessCompletion | **completed** |
| required / verified goals | metric_1, documents |
| SQL | **803.35 CNY**，P3 verified |
| P3 Evidence | `a914d0c1-595f-496d-aa2c-38e7e4f406ae` |
| P3 Verification | `f8e764b0-5fd7-4e8c-bf0d-a5b2219a5b00` |
| RAG outcome | **complete** |
| RAG verdict | `semantic_retrieval` |
| relevant chunk | `55469a84ebaa10725d40054188191836b62cc878f974f530fab24bac7f541b31` |
| 文档事实 | 企业版退款审核 **7 个工作日** |
| SQL / RAG / Report task | 均 succeeded |

## 4. Usage 与预算

| 项目 | 实际 |
|---|---:|
| 模型调用 | **3** |
| Input / Output | 4,033 / 319 |
| Total Token | **4,352** |
| Cache read | 2,048 |
| usage_complete | true |
| 自动重试 | **0** |
| 峰值估算 | **USD 0.000990588** |
| 实际账单 | **not_reconciled** |
| 预算上限 | 8 calls / 18,000 Token |

## 5. STOP 与范围

- STOP 文件已写入；本 Campaign 不重跑。
- 旧 `combined-independent-live-v1`（`17f5dc8a…`）结果保留不变。
- Formal 50 / Gate 3 不在本授权范围。

## 6. 证据路径

- JSON：`docs/research/p7-combined-independent-ci2628b61-live-results.json`
- Freeze：`artifacts/p7/combined-independent-ci2628b61-v1/private/freeze.json`
- Permit：`artifacts/p7/combined-independent-ci2628b61-v1/private/live/permit.json`
- 合同 / 审批：`…/contract-confirmed.json`、`approval-proof.json`
- 调用 / 轨迹：`…/calls.json`、`trace.json`
- STOP：`…/STOP`
