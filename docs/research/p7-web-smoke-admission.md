# P7 Web Smoke 最小持久准入控制

2026-11-02，分支 `p7-engineering-candidate-v1`；此前已验证源码 Commit `2f71dcb346cc527d0dd39bb5293029c2fe16ae92`，CI #29 通过。本轮新增最小 Web Smoke admission，**未调用付费模型、未执行 Live Smoke**。源码内容由新 Freeze 绑定；本轮本地实现 Commit SHA 见交付回复（不写入自引用文档）。

机器记录：[p7-web-smoke-admission.json](p7-web-smoke-admission.json)

私密完整证据：`artifacts/p7/fresh-web-smoke-v1/private/`（local-only）

## 1. 最终状态

| 项目 | 结果 |
|---|---|
| **Minimal Admission Control** | **PASS** |
| **Persistent Idempotency / Budget** | **PASS** |
| **Business Definitions** | **PENDING** |
| **Goal / Execution Approval** | **PENDING** |
| **Final Source Full CI** | **NOT_RUN** |
| **Ready for Live Authorization** | **NO** |
| **Paid Model Calls** | **0** |

本轮不是“Live 已安全通过”；只是最小准入和定向验收完成。当前源码尚未经过完整 CI，业务定义和每 Run 页面审批也仍未完成。

## 2. 阻断重新分类

| 分类 | 状态 |
|---|---|
| 执行前技术阻断 | **已补齐最小准入**：3 Case、每 Case 一个 Run、4th/替换拒绝、持久幂等、预算上限、有效期、STOP、owner/scope/freeze/config 绑定、恢复重查 |
| 待用户业务确认 | **PENDING**：SemanticDraft、MetricDraft、各 Goal 合同 |
| 正式执行审批 | **PENDING**：每个 Run 仍需页面独立批准；预检没有提前批准 Live |
| 执行后对账 | **非执行前阻断**：尚无供应商账单；0.0648 USD 是执行前估算，执行后必须 `not_reconciled` 或对账 |

## 3. 复用的现有机制

- `HostPolicy` 私有 host 文件与 Host/Origin/Session/CSRF。
- 原 `WebStore`/Outbox、事务 owner 锁、`web_messages` Run 关联和幂等键。
- 原 `execute_one`/`run_durable`、DurableLedger、Journal、Manifest、恢复检查。
- 原 Goal launch 与 `/tasks/{id}/approve` 的“确认 ≠ 执行审批”分离。
- 原 Fake/普通 Web 路径；admission 只在显式 `smoke_admission_file` 存在时生效。

## 4. 实际修改

| 文件 | 改动 |
|---|---|
| `migrations/versions/0009_web_smoke_admission.py` | 新增 `execution.web_smoke_admissions` 与 `datapilot_web` 权限 |
| `src/datapilot/web/admission.py` | Permit HMAC 校验、Case 匹配、预留/绑定/执行前复查 |
| `src/datapilot/web/config.py` | `HostPolicy.smoke_admission_file` / key env；普通 host 默认关闭 |
| `src/datapilot/web/service.py` | `AdmissionGate` 构造与 settings 更新 |
| `src/datapilot/web/chat.py` | 原 launch 事务内 reserve/attach；重试返回原 Run |
| `src/datapilot/web/app.py` | 启动校验 permit；直接 `/tasks` 创建拒绝；approve/resume 复查 |
| `src/datapilot/web/worker.py` | 模型执行前复查；cancel 仍允许 |
| `.github/workflows/test.yml` | 仅数量元数据 `1744/402/1342` |
| `tests/test_web_smoke_admission.py` | 14 个真实 PG admission 测试 |

源码 Diff：6 个已有文件修改；3 个新代码/迁移/测试文件。未改 Goal v4、P3、Citation、Report、Verifier、Embedding、预算算法或恢复核心。

### 新增状态的必要性

`execution.web_smoke_admissions` 只增加一个持久事实：**某 owner 的某 Case 已占用哪个 Run**。

- `PRIMARY KEY(owner,case_id)`：防止失败后换 key/新消息重跑同一 Case。
- `UNIQUE(run_id)`：一个 Run 只能绑定一个 Case。
- `request_sha256/message_id`：同一请求重试返回原 Run；不同消息拒绝。
- `permit_sha256/freeze_sha256`：permit 替换/撤销/漂移后旧 Run 不得继续执行。
- `goal_contract_sha256`：审计 Goal 绑定。
- `binding`：保存精确 Dataset/Corpus/指标/事实范围。
- `admitted_at/expires_at`：持久时间边界。

**没有新预算账本**：3 个 Run × 原每 Run 8 calls/18,000 units = **24/54,000** 全局上界；父子、失败预留与未知 usage 继续由原 root DurableLedger 计账。

## 5. 信任与授权模型

- Permit 只能由可信运维在 Web 进程外创建；`smoke_admission_file` 由私有 HostPolicy 指定，浏览器、模型和任意 HTTP 参数不能设置路径。
- Permit 必须由 `DATAPILOT_SMOKE_ADMISSION_KEY`（≥32 字符，环境变量）做 HMAC-SHA256 签名；key 不在 host JSON、浏览器、模型上下文或 MCP 子进程中。
- 签名体包含：project-owner 角色、负责人授权引用、owner、host settings hash、freeze、provider/model、3 个 Case、预算、有效期和停止策略。
- `authorized=true` 或一个未签名 JSON **本身不构成授权**；签名错误、key 缺失、过期、未来批准、stop 文件、错误 owner、config 漂移全部失败关闭。
- 本轮模板 `admission-template.json` 为 `authorized=false`、空签名；不创建 Permit。

## 6. 准入语义

| 约束 | 实现 |
|---|---|
| 每个 Case 最多一个 Run | PK(owner,case)；新消息同 Case → `SMOKE_CASE_CONSUMED` |
| 相同请求重试 | 同 request SHA + 同 message → 返回原 run_id，不新增 command |
| 第 4 个/替换 Case | 只允许 permit 中恰好 3 个 Case；不匹配 → `SMOKE_NOT_ADMITTED` |
| 错误输入/版本/Corpus | `match_case` 核对 question SHA、metrics/window、dataset/version、semantic/metric、report/rag policy、corpus/index/document IDs、required facts |
| 错误 owner | Permit/owner 绑定不符 → 拒绝 |
| 失败不得换 key 重跑 | Case 行已绑定原 message/run；新消息/新 key 拒绝 |
| Goal 确认不等于执行批准 | `/messages/{id}/launch` 只创建 `awaiting_review`；`/tasks/{id}/approve` 另行检查 admission |
| 过期/撤销/STOP | 每次 gate 重新读 permit；permit hash 变化、过期、revoked、stop file → 拒绝新执行 |
| 进程重启 | admission 行随原事务提交；重启后原 Run 只有原请求可返回，额度不重置 |
| issued/unknown | 原 run/ledger unknown 逻辑不变；admission 不创建 replacement Run |
| 普通 Fake Web | `smoke_admission_file` 缺失时 gate 完全 disabled；15 项普通 Web 测试通过 |
| 并发 | Case 级事务 advisory lock + PK，跨连接/进程只产生一个 Run |
| 服务端旁路 | admission 模式下直接 `POST /api/v1/tasks` 也拒绝，必须走确认后的 Web Goal |

### 并发控制区分

- `HostPolicy.max_workers`：跨 Run 后台派发并发。
- `Settings.max_parallel_workers`：Run 内 Worker 并发。

Permit 要求两者均为 **1**；当前 `.env` 的 `max_parallel_workers=2`，因此 **permit 校验会拒绝**，必须在启动 Live Host 前显式设置 `DATAPILOT_MAX_PARALLEL_WORKERS=1` 并重新冻结 host settings hash。不能把这两个控制混为一个。

### 时间与停止

- Permit `expires_at` 强制；Campaign 1800 秒从同一 Permit 下最早的 `admitted_at` 起在 approve/worker 复查；三个 Run 共用一个 Campaign 截止时间。
- 单 Run 180 秒目前是授权/停止条件，**不是硬进程 kill 时钟**；原 30 秒 provider timeout、step/SQL 限制和取消机制保留。此项仍列为剩余限制。
- 停止/过期只阻止后续 gate；不能证明已经发出的 Provider 请求未执行或未计费。

## 7. 非付费定向验收

真实隔离 PG + 原 Outbox/Worker/Durable/HTTP；Provider 为 Fake/Mock，未请求 DeepSeek。

| 测试 | 3.11 | 3.13 |
|---|---:|---:|
| `tests/test_web_smoke_admission.py`（真实 PG） | **14 passed** | **14 passed** |
| 普通 Web 聚焦（Goal/Chat/Review） | 15 passed, 18 skipped | 15 passed, 18 skipped |
| 普通 Web PG 正常路径 | 1 passed | — |
| Unknown-outcome 保守结算/不重发 | 1 passed | 1 passed |
| Ruff / format / diff-check | 通过 | 通过 |

覆盖：未签名/过期/未来批准/错误 owner/STOP；三个合法 Case；第四个/替换/错误 scope；同请求重试；并发争用；失败后新消息拒绝；重启持久化；permit 替换；config 漂移；campaign 超时；直接 API 创建旁路；HTTP approve 旁路；普通 Fake 路径。

初始失败记录保留在 `private/failures/admission-initial.txt`：最早 3 个测试因固定 message_id 冲突；并发测试 1 个唯一键冲突（已用 Case advisory lock 修复）；并发配置测试 9 个因测试 fixture 仍为 `max_parallel_workers=2` 被产品正确拒绝（fixture 修正）。这些不是 Provider/业务失败，未调用付费模型。

## 8. 业务定义精确批准清单

新 Dataset：`ea9efaf0-854f-5287-8d42-cca8ca0efaf1` v1，6 行，source SHA `dd197a51b949a0e19f38eae9583215cc5c4a824c4a2963cd7e58d29b9f095c6a`。
Corpus：`3fd3e8c1-1105-4c43-bc59-2913786a4f53`，IndexVersion `223be2d08a0fd76803c4aabf61ad7a4548db411b466d4a7bb2b017f76459de88`。

只读核对：

- `invoice_id` 6/6 唯一；grain=`invoice_id`。
- `amount_cents` 为整数分；`amount_storage=minor`；80335 分 → 803.35 CNY。
- 币种 CNY/USD；只按 `currency='CNY'` 计算。
- 状态 paid/unpaid；`paid_values=['paid']`。
- 窗口 `[2026-09-01, 2026-10-01)`；10 月 1 日行被排除。
- `history_complete=false`；不声明全量历史。
- SemanticDraft SHA **`087f8470a7767a63e02adcef3267d80c5676f9510101d346a4b10819dabde61e`**
- MetricDraft SHA **`e143653681bff867e8fb68f69a4370cf092348bc7dee00b4ac308f16e0dae7ed`**
- 当前 `definitions_confirmed=false`；**未调用** `/semantics/confirm` 或 `/metrics/confirm`。

需负责人逐项批准：

1. `invoices` 映射：`record_id←invoice_id`、`amount←amount_cents`、`invoice_date←invoice_date`、`payment_status←payment_status`、`currency←currency`；
2. `amount_cents` 是 CNY 分，除以 100 得元；不自动猜汇率；
3. `paid_values=['paid']` 且 `currency='CNY'`；
4. coverage `[2026-09-01,2026-10-01)` 与 `history_complete=false` 与实际数据一致；
5. Metric `paid_invoice_revenue` v1 在新 Dataset/Semantic v1 下登记；
6. RAG Goal 的 `facts` 目的与 required fact `企业版退款申请的审核时限`；
7. 三条 Goal 合同的原始问题、来源、用途及完成条件；
8. 每个 Run 的独立执行批准。

SQL-only 与 SQL+RAG 在批准前无法生成；RAG-only 预检合同仍 `pending_confirmation`（Conversation `d4d07c6f…`，Message `94c80f8e…`，contract SHA `ba277b5e…`），且该 Fake 预检合同不能冒充 Live 合同。

## 9. 新旧 Freeze 与 CI

- 旧准备 Freeze `p7-fresh-web-smoke-v1-6bf94e733bd7` 保留，不覆盖。
- 新实现 Freeze：**`p7-fresh-web-smoke-admission-v1-483bc675998f`**，SHA256 `483bc675998fa4c2e6c2df4a9c95b972c2c05b064f9c2768cd5e52a7a858a841`，parent 为旧 Freeze。
- Source manifest SHA256：`e8c8a20526572a0ff82d7c14759862ed92bcc6211a95d34ae7b1b7fdd87b9ba2`。
- Permit 模板 SHA256：`d3008a6a34408717dcb94cfeb10a2c28a89afbbb194ea184ed0e7b1f29a34ba6`（`authorized=false`）。
- 旧 CI #29 **不覆盖新源码**；Final Source Full CI = **NOT_RUN**。

实际收集（双版本相同）：

```text
1744 collected
1342 non-integration
402 integration
```

新增 14 个 integration 测试；原 1730 → 1744，388 → 402。全量 CI 预期：1342 非集成 + 339 集成通过 + 63 合法 skip = 1744；0 failed/errors。工作流数量元数据已更新，未引入白名单或测试删除。

定向命令（3.11/3.13 各一次）：

```powershell
pytest -q tests/test_web_smoke_admission.py
pytest -q tests/test_web_goal_confirmation.py tests/test_chat_ui.py tests/test_web_review_fixes.py
```

真实 PG 用隔离测试库执行；Demo 库已应用迁移 0009（仅新增准入表，未清理/Seed 历史）。

## 10. 待审查提交白名单

```text
M .github/workflows/test.yml
A migrations/versions/0009_web_smoke_admission.py
A src/datapilot/web/admission.py
M src/datapilot/web/config.py
M src/datapilot/web/service.py
M src/datapilot/web/chat.py
M src/datapilot/web/app.py
M src/datapilot/web/worker.py
A tests/test_web_smoke_admission.py
A docs/research/p7-web-smoke-admission.md
A docs/research/p7-web-smoke-admission.json
```

不提交 artifacts、host JSON、密钥、数据库、历史未跟踪报告或其他私密工件。本轮已创建一个独立本地 Commit（SHA 见交付回复，避免自引用），**未 Push**。

完整 CI 计划（提交后、推出前/后由负责人选择）：

1. 新建/迁移隔离测试库到 `0009`；
2. Python 3.11/3.13 全量：每版 1744 收集、1342 非集成、402 集成、339 pass + 63 skip，0 failed/errors；
3. 重点观察 migration 0009、admission 12 项、普通 Web 与 unknown-outcome；
4. 通过后才可把 `Final Source Full CI` 标为 PASS；当前仍 NOT_RUN。

## 11. 完成后的付费执行步骤（尚未授权）

1. 负责人批准第 8 节映射/Metric 并登记；确认 RAG/SQL/SQL+RAG Goal。
2. 用 `max_parallel_workers=1` 启动 Live Web，HostPolicy 指定私有 admission 文件；设置独立 admission key。
3. 负责人签署一次性授权文本；运维用 `seal_admission.py` 生成签名 Permit（`authorized=true`、有效期、Freeze、3 Cases、预算、STOP）。
4. 页面逐条确认 Goal、逐 Run 独立批准；不使用 API approve 兜底。
5. 只执行 3 个 Run；停止/过期后不再派发；unknown 保守保留。
6. 执行后按 Provider 实际 usage 对账；0.0648 USD 仍只是估算上界，不是账单保证。

付费授权文本应沿用 [Fresh Web Smoke 计划](p7-fresh-deepseek-web-smoke-plan.md) 的 §8，但必须把 Freeze 替换为 `p7-fresh-web-smoke-admission-v1-483bc675998f` / `483bc675998fa4c2e6c2df4a9c95b972c2c05b064f9c2768cd5e52a7a858a841`，并明确 serial Worker、admission key 与 admission file；旧 Freeze 的授权不得复用。

实际可执行边界必须写入最终授权：Campaign 截止时间为同一 Permit 下最早 admission 起 1800 秒；到期/STOP 后不再受理或派发新执行，正在进行的本地任务只能走原取消；**不保证 Provider 已收到请求未执行/未计费**；单 Run 180 秒不是硬终止，只有原 30 秒 provider timeout、step/SQL 限制与取消。不能把“停止新派发”写成“远端硬终止”。

## 12. 剩余事项

- 业务定义、Goal 确认、每 Run 执行审批仍 PENDING。
- 新源码完整 CI NOT_RUN；Ready NO。
- 单 Run 180 秒硬 wall-clock 未实现；campaign 1800 秒与 permit expiry 已检查。
- Permit 的 project-owner 批准引用由运维签名绑定，不是产品内审批工作流；产品内仍有独立 Goal/Execution 审批。
- 未调用任何付费模型；未进入 Live/Holdout/Gate 3。


## 13. 追加记录（2026-11-02）：业务定义登记、Goal 准备与 CI #30

> 本节是推送后追加记录。第 1–12 节保留推送前 Freeze/报告快照；其中 `Business Definitions: PENDING`、`Final Source Full CI: NOT_RUN` 是当时的真实快照，不是当前状态。以下追加不修改代码、不重跑 CI、不 Commit/Push。

### 13.1 业务定义登记（已获本次有限授权）

数据集 `ea9efaf0-854f-5287-8d42-cca8ca0efaf1` v1，来源 SHA `dd197a51b949a0e19f38eae9583215cc5c4a824c4a2963cd7e58d29b9f095c6a`。

通过原 `/api/v1/semantics/confirm` 与 `/api/v1/metrics/confirm` 接口登记；未直接修改 `reviewed` 状态：

| 项目 | 值 |
|---|---|
| Semantic version | **1** |
| Semantic registry definition SHA | `2da3a80810a17f679aa9c67e8d32d01772866cd4927651187c3e1dbf019f1364` |
| Metric version | **1** |
| Metric registry definition SHA | `f2178982580185dbd47994e8c6d9ff1e80656292c915efcb834be80f7ef6e9a1` |
| Metric semantic SHA | `2da3a808…` |

说明：`087f8470…` / `e1436536…` 是批准时使用的 **Draft SHA**；Registry 的 `definition_sha256` 是服务端 canonical digest，数值不同但登记后的 `definition` 内容与批准的 SemanticDraft/MetricDraft **逐字段相等**（已核对）。

- 相同确认重复提交返回同一版本 1，没有重复登记。
- 未声明 USD 换算、MRR、未批准指标；`history_complete=false`。
- 803.35 CNY 仍只是独立预期，不用于反推或改口径。

### 13.2 三条 Goal/候选合同准备（未确认、未启动 Run）

| Case | Conversation | Message | 状态 |
|---|---|---|---|
| fresh-web-01 SQL-only | `6441c9ad-8247-459e-babc-184304ee7451` | `5943ab03-fc1b-44e3-a6ed-6f899cb94e4c` | 仅有 metric-only candidate draft；`run_id=null`，`missing=[]` |
| fresh-web-02 RAG-only | `94a2c266-e00c-4afa-b6eb-df5836782044` | `f05694cb-1e77-4a62-b1e6-d6138ff5a192` | Goal `pending_confirmation`，`can_confirm=true`，`run_id=null` |
| fresh-web-03 SQL+RAG | `2df8270b-e38e-4f33-80c2-00e77521e11e` | `d5d39f24-13a9-4a3d-a6e8-d85c273d70e1` | Goal `pending_confirmation`，`can_confirm=true`，`run_id=null` |

- SQL-only 的现有产品路径不生成 document Goal v4 合同，只有 metric-only 候选；这是既有 Web 设计，不是本轮新增限制。其候选请求为 P3 指标 + 窗口，确认后仍需独立执行审批。
- RAG-only contract SHA `880cccb5c6415311fcd4e3f32d2541a1e6e5fccb0f71f0ffabece4c60f872a53`；来源 `refund-policy-2026.md`，Corpus/Index/Source/Document 见 Goal JSON。
- SQL+RAG contract SHA `eedd353f943253534a1a6671aa037e0a10ce21a73faa99a266ee5128eb505472`；指标与文档事实同时待确认。
- 三条均未启动 Run；未批准 Goal；未批准执行；未调用模型。
- 这些准备合同创建于当前 Fake Host 配置。最终 Live Host 将改为 `llm_mode=live` 且 `max_parallel_workers=1`，Host settings hash 会变化；**最终确认前需在最终 Live Host 下重新生成/审阅合同**，不能把当前 Fake 准备合同直接当作 Live 合同。

完成条件（不变）：

- SQL-only：803.35 CNY，P3 verified，窗口/单位/来源正确；
- RAG-only：7 个工作日，指定原文/Chunk/行/版本可核验；
- SQL+RAG：803.35 CNY + 7 个工作日原文，两者均由原 Host/Verifier/Report 判定，文档不证明收入因果。

### 13.3 CI #30 实际 PASS（追加）

| 项目 | 实际 |
|---|---|
| Actions | https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41416548492（#30） |
| 触发 | Push，attempt 1；无额外 dispatch/rerun |
| Commit | `cccd829f7240b9ff56b7d3817c7b716c39616108` |
| 3.11 / 3.13 收集 | 各 **1744** = 1342 非集成 + 402 集成 |
| 3.11 / 3.13 通过 | 各 **1681 passed**（1342 非集成 + 339 集成） |
| 跳过 | 各 **63**（62 Qwen/CUDA + 1 Live opt-in） |
| failed / errors | **0 / 0** |
| 原 60 项 | **60/60 passed** |
| 新增 admission 14 项 | **14/14 passed** |
| 迁移 0009 | CI 日志确认 revision 0009 |
| Artifact digest | 3.11 `45fe7572…`、3.13 `b8d84510…`，下载 ZIP SHA256 均一致 |
| 源码对比 | 21 个 Freeze 文件对 CI `source-sha256` **21/21 匹配，0 mismatch** |

验收记录：`artifacts/ci30/verification.json`（local-only）。

原推送前 `Final Source Full CI: NOT_RUN` 快照保留；以上追加是当前实际 CI 结果。未新增提交、未重新推送、未修改 CI。

### 13.4 最终确认与付费授权边界

- SQL-only：在最终 Live Host 页面审阅候选请求，点击提交并等待人工审批；不预先批准。
- RAG-only/SQL+RAG：在页面完成三项显式确认，生成 `awaiting_review`，再独立点击执行审批；不得用 API 审批兜底。
- 一次性付费授权只能使用新 Freeze `p7-fresh-web-smoke-admission-v1-483bc675998f`，3 案例各一次；模型 `deepseek-flash`、Thinking disabled、无自动重试、每 Run 8/18,000、全局 24/54,000、并发 1。
- 时间边界：Permit `expires_at` + 同一 Permit 最早 admission 起 **1800 秒 Campaign 截止**；到期/STOP 后不再派发，正在执行的本地任务只能原取消；**不保证 Provider 未收到/未计费**。
- **单 Run 180 秒不是硬终止**；只有原 30 秒 provider timeout、step/SQL 限制与取消。最终授权必须明确接受此边界，或另行批准最小硬超时实现。
- 本轮未创建有效 Permit，未调用 DeepSeek，未执行 Smoke、Holdout 或 Gate3。


### 13.5 一次性 Live 授权草案（未生效）

以下文本仅供负责人审批时使用；当前 `authorized=false`，不构成 Permit，也不授权任何付费调用。

> 授权 DataPilot Pro Campaign `p7-fresh-web-smoke-v1` / Freeze `p7-fresh-web-smoke-admission-v1-483bc675998f`（SHA256 `483bc675998fa4c2e6c2df4a9c95b972c2c05b064f9c2768cd5e52a7a858a841`），仅执行 `fresh-web-01`、`fresh-web-02`、`fresh-web-03` 各一次。Dataset `ea9efaf0-854f-5287-8d42-cca8ca0efaf1` v1；Semantic v1 `2da3a808…`；Metric `paid_invoice_revenue` v1 `f2178982…`。
>
> Provider DeepSeek；端点 `https://api.deepseek.com`；模型 `deepseek-flash`；Thinking disabled；temperature 0；max_output_tokens 1200/attempt；SDK 与外层自动重试 0；并发 1（Host `max_workers=1` 且 `max_parallel_workers=1`）。
>
> 最多 3 个业务 Run；每 Run 8 次调用尝试 / 18,000 Token 计账单位；Campaign 24 次 / 54,000；实际费用上界按执行前官方费率重核，2026-11-02 峰值估算为 0.0648 USD，不是账单保证。
>
> 时间边界：Permit `expires_at` 生效；Campaign 从同一 Permit 下最早 admission 起 1800 秒截止。到期/STOP 后不再受理或派发新执行；正在执行的本地任务只能通过原取消路径处理；**不保证供应商已收到的请求未执行/未计费**。单 Run 180 秒不是硬终止，只有原 30 秒 provider timeout、step/SQL 限制与取消；负责人必须明确接受此边界或另行批准最小硬超时实现。
>
> 执行入口为真实 Web 页面；每条 Goal 由用户确认，每个 Run 另行执行审批，不使用 API 审批兜底。普通明确业务失败保留并停止后续派发；权限/来源/版本/预算/身份/unknown/恢复冲突/超时/费率变化立即停止。
>
> 本授权仅限上述 Campaign、Freeze、案例、模型、数据和预算；不适用其他 Campaign/模型/Prompt/Scorer/Holdout/Gate3，不重跑、不续跑、不挪用剩余额度。

在最终 Live Host 下重新生成并审阅三份 Goal 后，才可签署 Permit。SQL-only 是 metric-only candidate（现有产品不生成 document Goal v4）；RAG-only/SQL+RAG 是真正的 document Goal 合同。
