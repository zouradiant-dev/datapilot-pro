# P7 纯浏览器 SQL+RAG 审批闭环

2026-11-02，分支 `p7-engineering-candidate-v1`，源码 Commit **`2f71dcb346cc527d0dd39bb5293029c2fe16ae92`**。本轮只定位并验收“SQL+RAG 执行审批曾需 API 兜底”的问题；**未修改产品源码**，未调用付费模型，未进入 Holdout/Gate 3。

机器证据：`artifacts/showcase-browser/20261101-demo/evidence/browser-approval-closure.json`（local-only）。

## 1. 基线核实

| 项目 | 结果 |
|---|---|
| 本地 / 远端 HEAD | `2f71dcb346cc527d0dd39bb5293029c2fe16ae92`，一致 |
| CI #29 | [41383487439](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41383487439)，attempt 1，success |
| 3.11 / 3.13 | 各 1730 收集 = 1342 非集成 + 388 集成；各 1667 通过、63 skip、0 failed/errors |
| 当前工作区 | 无已跟踪修改；仅 8 份历史未跟踪研究文件 |
| 模型 / Embedding | Fake；默认 BGE 未切换 |
| 数据 / 服务 | 既有隔离合成 Demo，真实 FastAPI/Streamlit/PG/MCP |

## 2. 原 API 兜底定位

历史 Run `f3cb2227-8ac6-416f-b0b7-44dbe3a223cb` 的记录：

```json
{"run_id":"f3cb2227-8ac6-416f-b0b7-44dbe3a223cb",
 "method":"api-fallback-after-browser-control","status":"completed"}
```

具体步骤与判定：

1. `approve_hybrid.py` 在页面勾选审批框后，使用 `approve.focus()` + `keyboard.press("Enter")`，**没有实际 `click()` 按钮**。
2. 随后仅轮询 **12 秒**（6 次 × 2 秒）；若仍为 `awaiting_review`，脚本直接调用 `/tasks/{id}/approve`，并标记 `api-fallback-after-browser-control`。
3. 本轮用真实浏览器点击同一按钮：`awaiting_review` 约 3/6/9 秒，**约 12 秒后 completed**；浏览器点击后 Streamlit 重跑、Outbox 派发与 Runtime 取消都需要等待；12 秒窗口过窄，撤回实测约 75 秒。
4. 因此这不是产品审批接口、页面状态、会话或 CSRF 缺陷；是**自动化按键方式 + 过短等待**导致的兜底，属于浏览器自动化限制。
5. 页面按钮确实调用原正式接口，不是 UI 侧直接改状态：

```text
src/datapilot/web/ui_components.py:176
api.post(f"/tasks/{run_id}/approve", {"confirmed": True}, key="approve-" + run_id)

src/datapilot/web/app.py:341-396
POST /api/v1/tasks/{id_}/approve
→ 校验 awaiting_review + confirmed=true + Idempotency-Key
→ 原 store.command / Durable Outbox / Runtime
```

目标合同确认与执行审批仍是两个独立步骤：`/messages/{id}/launch` 只创建 `awaiting_review` Run；`/tasks/{id}/approve` 才批准执行。

## 3. 修复前后

**无需代码修复。** 当前页面在真实点击、足够等待下可独立完成审批。本轮未修改 UI、HTTP、Runtime、审批接口或任何安全守卫；仅新增公开报告和 local-only 证据。

| 项目 | 修复前（历史） | 本轮 |
|---|---|---|
| 触发方式 | focus + Enter，12 秒后 API 兜底 | 浏览器真实 click |
| 审批 HTTP | 兜底调用 `/tasks/{id}/approve` | 页面调用同一 `/tasks/{id}/approve` |
| 结果 | completed（混合路径） | completed（纯浏览器） |
| 产品代码 | 不改 | 不改 |

## 4. 纯浏览器路径

Conversation：`c03fa92b-1cc3-45ef-b52c-9a22fe5e6b4d`
Goal Message：`8e2369e3-29bd-4df4-bf2e-ab944432715a`
Run：**`ef24ae7b-939c-418d-8e35-ae38d0621c87`**

步骤：

1. 在页面新建对话，通过聊天输入提交 SQL+RAG 问题；
2. 页面提示“原问题包含文档目标”，在补充表单中选择：
   - Dataset `showcase-june-2026` v1；
   - Metric `已支付账单收入（非 MRR）` v1；
   - 窗口 2026-06-01 至 2026-07-01（结束不含）；
   - Corpus `a53942ba-8c63-4d45-ac67-b63edf7752b3`；
   - 文档用途 `summary`；
3. 勾选快照/指标/时间/文档范围确认，点击“补充条件并重新确认”；
4. 生成有限目标合同（version 2，pending_confirmation）；
5. 页面完成三项显式确认，点击“确认范围并创建待审批任务”；
6. Run 创建为 `awaiting_review`；**目标确认没有自动批准执行**；
7. 页面独立勾选“我已核对……批准执行”，点击“批准执行”；
8. 浏览器路径调用原 `/tasks/{run_id}/approve`，约 12 秒后 `completed`；
9. 刷新/重新进入，报告与 Run 身份保持一致。

截图（local-only）：

```text
screens/closure-01-form.png                 表单：数据/指标/日期/Corpus/用途/确认
screens/closure-02-contract.png             有限目标合同
screens/closure-approval-real.png           独立执行审批门
screens/closure-05-report.png               最终报告
screens/closure-06-sources.png              来源、口径、验证依据
```

审批门截图取自专用负例合同的同一 UI 路径；主 Run 的批准由浏览器状态转换与轮询日志证明。

本轮审批**没有调用** `/tasks/{id}/approve` 的 API 兜底；自动化只使用 GET 读取状态/报告用于核验。

## 5. Verified Report 展示

| 项目 | 值 |
|---|---|
| 指标 | `paid_invoice_revenue` v1 |
| 数值 | **1432.2500000000000000 CNY** |
| 窗口 | 2026-06-01 至 2026-07-01（结束不含） |
| Business completion | **completed**（metric_1 + documents） |
| SQL / RAG / Report | succeeded / succeeded / succeeded |
| Evidence | `2f68d5e5-88fc-4788-8343-d2bd17244c1e` |
| Verification | `c95deaab-9557-4e52-95eb-045e29d1e812` |
| 文档引用 | Chunk `02ed72c0…`，行 **1–1**（描述性背景） |
| Source | `billing-guide.md`，source_id `4b2fb48f…`，source SHA/version `7071a8c5…` |
| IndexVersion | `bd80b8c2…` |

报告明确说明：文档背景不证明因果，数值以 P3 Evidence 为准；没有把 Fake Worker 成功写成真实 DeepSeek 业务质量。

## 6. 刷新与幂等

- 刷新/重新进入同一 Conversation 后，仍只有 **1 个** Run 关联：`ef24ae7b…`。
- 多次 GET `/tasks/{id}` 与 `/tasks/{id}/report` 返回相同 status、facts、Evidence/Verification 和 citation。
- 完整 CI #29 中真实 PG 测试 `tests/test_web_postgres.py::test_api_preview_confirm_metric_durable_report` 验证：
  - 同一审批请求重复提交返回同一 ack；
  - 完成后再次审批不改变报告；
  - 不存在重复 Run/重复派发。
- 本轮浏览器只点击一次批准；没有观察到重复 Run、重复派发或重复结算。浏览器重复点击的独立自动化未单独执行，幂等由上述真实 PG/HTTP 测试覆盖。

## 7. 撤回确认与报告不可发布

为避免影响主验收合同，另建专用负例：

- Conversation：`18ecece7-79f7-4a83-a126-030e45334408`
- Run：`b9c0a320-b4e9-42fc-9c16-58679dcc07d6`
- 候选由可信宿主预置；**合同确认、执行审批、撤回均在页面完成**。
- 撤回前报告已生成并截图；页面点击“取消或撤回本次合同”后，约 75 秒完成 Runtime 取消。
- 结果：
  - Goal 状态：`rejected`；
  - UI：显示“有限目标合同 · rejected”，报告不再展示；
  - `GET /api/v1/tasks/{id}`：**403 `GOAL_REVOKED`**；
  - `GET /api/v1/tasks/{id}/report`：**403 `GOAL_REVOKED`**。
- UI 与 HTTP 拒绝一致；未修改/撤回历史演示合同。

## 8. 会话与 CSRF

审批仍经过原 FastAPI Host/Origin/Session/CSRF 校验；页面没有直接调用 Runtime、Registry 或数据库。

完整 CI #29 已通过：

```text
tests/test_web_postgres.py::test_session_host_origin_csrf_validation
tests/test_chat_postgres.py::test_message_integrity_owner_and_csrf_are_enforced
```

实际过期浏览器会话未重新构造（**NOT_RUN**）；该项由真实 PG/HTTP 测试覆盖，没有自动批准或静默绕过路径。

## 9. 测试与证据

本轮**无源码变化**，因此不重复运行完整 CI；直接复用当前 Commit 的 CI #29：

| 项目 | 3.11 | 3.13 |
|---|---:|---:|
| 收集 | 1730 | 1730 |
| 非集成 | 1342 passed | 1342 passed |
| 集成 | 325 passed + 63 skipped | 325 passed + 63 skipped |
| failed / errors | 0 / 0 | 0 / 0 |
| 原 60 项失败测试 | 60/60 passed | 60/60 passed |

CI #29 的 Ruff、format、JUnit、Artifact digest、source SHA 均已核验。浏览器 Smoke 为本轮新增实际验收；未用 Mock 前端测试替代。

证据 JSON：`browser-approval-closure.json` SHA256 `8222712c7bcb3f9a62df1966a1eb4c5a380e87164edb4fe6a1ca0c0d1e5d3de3`。

源码 Hash：

```text
model.py       5363ab5e31937d972432285fe6452fc5e42e3f6c842df2e019798b0a5764de40
test file      a18b6b68e9c2ca9c8df4f7e1bc25f2bed5192db4e1246f0f5a8aef1ee17b48ad
```

## 10. 截图 Hash（local-only）

```text
closure-01-form.png          17877582e621745d1c058a59940cca0ffd56b9e2a4732cb0accb3d19b3225ae9
closure-02-contract.png      65dfd38d62426c465f3112c0e8e7900a1a897ca6ebc1d12f3b442c6b9426766b
closure-approval-real.png    c714a7005646fcbd95fdb0d87904a8c4dba441fa27fe374de899254b11468d61
closure-05-report.png        2bca19fc96f3563e14042f35bcab30994ca4627b827fad1473aacd847a173407
closure-06-sources.png       2cc9f676af2c39b836bf9cbbf67184eba90a1367dc5dc7b4d55572149114231d
closure-revocable-report.png 9da2a2582e021dc6601b5fab939826dc278bc825c18ed09b83ba3f252093a4a0
closure-revoked-final.png    3eb6992c9f2b06e38997549b33c3cc47296c1c25e588611cbc2dbe59633affb8
```

## 11. Gate

| Gate | 结果 |
|---|---|
| **Browser-only SQL+RAG Approval** | **PASS** |
| **Verified Report Display** | **PASS** |
| **Idempotency / Revocation** | **PASS** |
| Independent Business Quality | **PENDING** |
| DeepSeek Live Gate | **PENDING** |
| New Source Full CI | **NOT_REQUIRED**（无源码变化，当前 Commit 已由 CI #29 双版本验证） |

## 12. 剩余限制与风险

- 模型仍是 Fake；本轮只证明工程闭环，不证明真实模型业务质量或 DeepSeek Live 自主分析。
- 审批约 12 秒、撤回约 75 秒是同步 Runtime/Outbox 操作的真实时延；自动化必须以状态轮询为准，不能以短超时判定 UI 失败或改用 API 兜底。
- 仅一个合成 SQL+RAG 正向用例；不是独立业务集、不是 Holdout、不是质量评测。
- 实际过期浏览器会话未重放；由真实 PG/HTTP 测试覆盖。
- 纯浏览器证据只覆盖本机演示环境；多租户、生产认证和 RLS 仍不在本轮范围。

## 13. Git 状态

- 无已跟踪源码修改；未 Commit、未 Push、未创建 PR。
- 8 份历史未跟踪研究文件保持不变。
- 公开报告为本文件；截图、JUnit、日志、Host JSON、数据库配置均在忽略目录，不进入提交。
- 若未来需要修改 UI/HTTP 代码，必须重新走完整双版本 CI，不能用本报告替代。
