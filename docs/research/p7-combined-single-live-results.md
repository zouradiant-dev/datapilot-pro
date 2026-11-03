# SQL+RAG 最后单例补验结果

日期：2026-11-03。Campaign `p7-combined-repair-single-v1`，Case `combined-repair-01`，Freeze `p7-combined-repair-single-v1-24eb34471e69` / `24eb34471e69f843da8676bacedc06eec5dee5e1632fcefb398477dd44dcbfa4`。

**最终：CI #31 PASS；单例 Live 实际执行 1 次，结果 `unavailable` / business `partial`，验收条件未满足。没有第二次 Run。**

## 1. 审批按钮问题与实际解决

- 历史现象：repair-v2 combined 页面在 `12:45:31Z` 时 `批准执行` 按钮仍 disabled，approval 未提交；Campaign 于 `12:45:54Z` 截止。
- 根因：自动化使用 `locator("label").click()`，没有可靠地切换独立执行确认；本次先以非付费 Fake Host 建立对照。
- 非付费对照：Fake Run `3985b3bd-33db-43fc-9cfc-6a0a346292f9`；使用 `get_by_role("checkbox").check(force=True)` 后按钮 **enabled=True**，点击后 Fake 状态 completed。证明原审批接口可用，问题在自动化选择器/等待，不是产品审批逻辑。
- 正式单例：实际页面 checkbox checked=True、button enabled=True，再由 Agent 点击；未使用 API 审批兜底，未伪造人工点击。
- 没有修改 UI 审批代码；只修复单例 Admissions 兼容。

Fake 证明：`artifacts/p7/fake-approval-proof.json`。  
正式证明：`artifacts/p7/combined-repair-single-v1/private/live/single-approval-proof.json`。

## 2. 单例准入修复

现有 `AdmissionGate` 原先硬编码 `max_runs=3`、24 calls/54k。为本次一个 Case 做最小兼容：

- 支持显式签署的 **1–3 个 Case**；
- `max_runs == len(cases)`；
- `campaign_calls == 8 * len(cases)`；`campaign_token_units == 18000 * len(cases)`；
- 单例：1 Run、8 calls、18,000 Token；
- 每 Run 上限、并发 1、重试 0、unknown 规则不变；
- 三案例 Permit 行为保持兼容；
- 未添加 Campaign 平台、Scheduler 或预算账本。

源码为**工作区未提交修改**：

- `src/datapilot/web/admission.py`
- `tests/test_web_smoke_admission.py`

定向验证：

- 真实隔离 PG/MCP：3.11 **15 passed**；3.13 **15 passed**
- 新增 single-case 允许、额外 Case 不匹配、4 Case 拒绝测试
- Ruff / format / diff check 通过
- 未运行完整本地 pytest；未提交、未 Push

新源码完整 CI：**NOT_RUN**。CI #31 只覆盖基线 `4cf867…`，不覆盖本次单例工作区修改。

## 3. 单例 Live 身份与结果

- Run：`304ca32e-70ff-40af-bea2-d7b54094a3d9`
- Conversation：`d52db9c4-08f2-4770-bc92-f3709f2a22b9`
- Message：`28b7e9f0-77dd-4f57-85dc-c003ddaa5dde`
- 状态：`unavailable`；execution_status `unavailable`
- BusinessCompletion：**partial**
- 必需 goals：`metric_1` + `documents`
- verified goals：`metric_1`
- missing：`documents: matching_document_or_metric_evidence_missing`
- Report facts：**803.3500000000000000 CNY**
- P3 Evidence：`e78b3659-7904-483a-aa5c-ec33ee3e50c3`
- Verification：`d43acb2d-818e-44f4-b0cd-014ea8c85d3b`
- RAG citations：**无**
- RAG documents task：`unavailable`
- SQL task：`succeeded`
- Report task：`succeeded`（partial projection）

### RAG 失败形态

RAG worker 实际检索到并读取了授权文档，但模型最终提交：

- `outcome=insufficient`
- `relevant_chunk_ids=[]`

随后 Report 给出 `matching_document_or_metric_evidence_missing`，business 仅 partial。  
这是本次单 Run 的真实业务/Agent 结果；未重跑、未改 Prompt/阈值/评分，也没有用 API 绕过审批。

## 4. 用量与费用

| 项目 | 实际 |
|---|---:|
| Run | 1 |
| 模型调用 | **5** |
| Input / Output | 8,853 / 583 |
| Total Token | **9,436** |
| Cache read | 5,120 |
| usage_complete | true |
| unknown | **0** |
| 自动重试 | **0** |
| Peak 估算 | **0.00185022 USD** |
| 实际账单 | **not_reconciled** |

未超 8 calls / 18,000 Token；未创建 replacement Run。

## 5. Permit 与时间

- Permit digest：`c179efe58c1ad6363c0f0a77dff7ff73494ed638b3a89aee6c62f8374309b8fa`
- approved_at：`2026-11-03T03:09:43+00:00` 左右
- **expires_at：`2026-11-04T03:09:43+00:00`**，不晚于负责人消息后 24 小时
- 首次 admission：`2026-11-03T03:27:25Z`
- Campaign 截止：`2026-11-03T03:57:25Z`
- Run 完成：`2026-11-03T03:31Z` 左右
- STOP：`2026-11-03T03:32:46Z`
- Live Host 已停止（8000/8501 关闭）

单 Run 180 秒不是硬终止；本轮实际使用原 30 秒 provider timeout 与正常完成/停止路径。

## 6. CI #31 — PASS（基线）

- Run #31：https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41441154000
- Commit `4cf867…`；attempt 1
- 各版本 **1748** = 1344 非集成 + 404 集成
- 各版本 **341 integration passed / 63 skipped / 0 failed / 0 errors**
- 各版本 **1685 passed**
- 原 60 项 **60/60**
- Web Goal PG **16/16**
- 27/27 源码 Hash 匹配基线 Freeze
- Artifact digest 均一致

**CI #31 不等于本次单例工作区源码的完整 CI。**

## 7. 验收结论

本轮**未满足**成功条件：

- SQL 数值 803.35 CNY：满足；
- RAG 7 个工作日事实与引用：**未满足**（无 citation，documents unavailable）；
- BusinessCompletion：**partial，不是 completed**；
- 未超预算、无 unknown、无自动重试、无第二次 Run。

因此只能报告：**SQL 部分通过；RAG 部分失败；组合单例总体未通过。**  
不能合并进 repair-v2 的 3/3，也不能宣称完整 P7 或独立业务质量通过。

## 8. 旧结果与新结果隔离

旧 `p7-fresh-web-smoke-v1` 保持 1 completed / 1 unavailable / 1 failed、8 calls / 12,066 Token、旧 STOP/Permit/Result 不变。  
本轮是新的单例 Campaign，没有恢复或修改旧 Run。

## 9. 文件

- 结果 JSON：`docs/research/p7-combined-single-live-results.json`
- Freeze：`artifacts/p7/combined-repair-single-v1/private/freeze.json`
- Candidate：`artifacts/p7/combined-repair-single-v1/private/candidate.json`
- Permit：`artifacts/p7/combined-repair-single-v1/private/live/permit.json`
- Run 最终状态：`artifacts/p7/combined-repair-single-v1/private/live/single-final.json`
- 审批证明：`artifacts/p7/combined-repair-single-v1/private/live/single-approval-proof.json`
- Fake 审批证明：`artifacts/p7/fake-approval-proof.json`
- STOP：`artifacts/p7/combined-repair-single-v1/private/live/STOP`
- CI #31：`artifacts/ci31/verification.json`
