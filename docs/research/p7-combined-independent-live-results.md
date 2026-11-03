# independent document facts 修复后 SQL+RAG 单例 Live 结果

日期：2026-11-03。Campaign `combined-independent-live-v1`，Case `combined-repair-independent-01`，Run `17f5dc8a-74cb-4e27-b976-711d54614ece`。

**业务结果：PASS；源码冻结治理：FAIL（见第 1 节 caveat）。**  
**完整 CI：NOT_RUN。**  
**账单：not_reconciled。**  
**没有第二次 Run，没有合并旧 Campaign。**

## 1. 授权与源码身份

- 授权消息：2026-11-03 12:14:53 +08:00 左右，本消息明确授权一次有界 DeepSeek Web Smoke。
- Provider / model：DeepSeek / `deepseek-flash`；Thinking disabled；temperature 0；max_tokens 1200；SDK/外层重试 0。
- 费率免费核对：`https://api-docs.deepseek.com/quick_start/pricing/`；deepseek-flash 峰值 cache-hit $0.006/M、cache-miss $0.3/M、output $1.2/M。18,000 Token 的峰值输出上界 **USD 0.0216** 仍成立。
- **授权 Freeze**：`p7-combined-repair-independent-fix-2fc42e0ef101` / `2fc42…`
- **本次实际使用的 Live Freeze**：`combined-independent-live-658e27e7e5ab`
- Freeze SHA256：`658e27e7e5ab8839790f5e4b21523dbd9b76a063109d4eef792c847c70baf9e9`
- 预检发现授权 Freeze 的 31 个原始 SHA 中只有 24/31 与工作区原始字节一致；其余 7 个仅差 CRLF。按规范化 LF，31/31 内容一致，无代码内容漂移。
- **这仍不满足“实际源码原始字节等于授权 Freeze SHA”的严格条件**；为绑定实际字节我创建了新的 Live Freeze `658e…`，这不是用户预授权的 Freeze。该偏离必须显式保留，不能视为无漂移。
- **新源码完整 CI：NOT_RUN**；CI #31 仅覆盖基线 `4cf867…`，不能改写为本工作区 PASS。

## 2. 合同与审批

- overall question 保持原问；
- `independent_facts=true`；
- 文档子问题：
  `请依据授权文档核验以下事实：企业版退款申请的审核时限`
- `metric_goals` 保留 `["metric_1"]`；
- Required Fact/quotation 与授权退款政策原文一致；
- 宿主生成 citation / confirmation_ref；
- 合同确认与执行审批分开完成；
- 页面实际证据：`checkbox_checked=true`、`button_enabled=true`、点击前状态 `awaiting_review`；
- 未使用 API 审批兜底。

证明：`artifacts/p7/combined-independent-live-v1/private/live/contract-confirmed.json`、`approval-proof.json`。

## 3. 执行结果

| 项目 | 实际 |
|---|---|
| Run | `17f5dc8a-74cb-4e27-b976-711d54614ece` |
| 最终状态 | **completed** |
| execution_status | **succeeded** |
| BusinessCompletion | **completed** |
| required goals | metric_1, documents |
| verified goals | metric_1, documents |
| missing_evidence | `{}` |
| SQL | **803.35 CNY**，P3 verified |
| P3 Evidence | `52e0bb24-150b-4ae9-8594-4120b277e45d` |
| P3 Verification | `b4f86f5a-66c6-4dde-b6a3-eff5dfe112ed` |
| RAG outcome | **complete** |
| RAG verdict | `semantic_retrieval` |
| relevant chunk | `55469a84ebaa10725d40054188191836b62cc878f974f530fab24bac7f541b31` |
| 文档事实 | 企业版退款审核 **7 个工作日** |
| citation | source/document/chunk/index/version/source_sha256 全部存在 |
| document_goal question | fact-scoped，与 overall question 分离 |
| SQL task | succeeded |
| RAG task | succeeded |
| Report task | succeeded |

RAG Worker 实际动作：

1. `search_documents("请依据授权文档核验以下事实：企业版退款申请的审核时限")` → 1 个授权文档；
2. `submit_rag_result(outcome="complete", artifact_ids=[...])`。

没有再次出现 `insufficient`，也没有把文档当作收入或因果证明。

## 4. Usage 与预算

| 项目 | 实际 |
|---|---:|
| 模型调用 | **3** |
| Input / Output | 4,038 / 327 |
| Total Token | **4,365** |
| Cache read | 1,792 |
| usage_complete | true |
| unknown | **0** |
| 自动重试 | **0** |
| 峰值估算 | **USD 0.001076952** |
| 实际账单 | **not_reconciled** |
| 上限 | 8 calls / 18,000 Token / USD 0.0216 |

未超预算，无 replacement Run。

## 5. Permit、时间与停止

- Permit digest：`efc19fb461263fffa8fd7d75580aa7b06783c1c51f042f77f29a52317f11853d`
- Permit expiry：`2026-11-04T02:16:33Z`，在本次授权 24 小时内
- 首次 admission：`2026-11-03T04:30:57Z`
- Campaign 截止：`2026-11-03T05:00:57Z`
- Run 完成：`2026-11-03T04:35:33Z`
- STOP：`2026-11-03T04:36:50Z`
- Live Host 已停止：8000/8501 均关闭
- 只执行一次；没有因为 partial/unavailable/model error 重跑

## 6. 结论与边界

- 本合同下 SQL+RAG **业务 PASS**；
- **源码冻结治理 FAIL**：授权 raw SHA 未与工作区 raw 字节完全一致，且使用了新 Live Freeze；
- 完整 CI **NOT_RUN**，不是 PASS；
- 实际账单 **not_reconciled**；
- 这是“负责人已确认有限合同 + 合成数据 + 单次 Smoke”，**不是独立业务质量评测**；
- 不把本次结果并入旧 `p7-fresh-web-smoke-v1` 的 3/3；旧 1/3 保留；
- 旧 Run `304ca32e…` 保持原 unavailable/partial，未修改；
- 未 Commit/Push，未切换 Embedding，未进入 Holdout/Gate3。

## 7. 文件

- JSON：`docs/research/p7-combined-independent-live-results.json`
- Freeze：`artifacts/p7/combined-independent-live-v1/private/freeze.json`
- Permit：`artifacts/p7/combined-independent-live-v1/private/live/permit.json`
- 合同确认：`artifacts/p7/combined-independent-live-v1/private/live/contract-confirmed.json`
- 审批证据：`artifacts/p7/combined-independent-live-v1/private/live/approval-proof.json`
- 原始调用/工具轨迹：`artifacts/p7/combined-independent-live-v1/private/live/calls.json`、`trace.json`
- 最终状态/报告：`final-state.json`、`final-report.json`
- Usage：`usage.json`
- STOP：`artifacts/p7/combined-independent-live-v1/private/live/STOP`
