# P6C.1：对话优先的可信本地 Demo

本页保留原 P6C.1 冻结验收快照；后续五项审查修复与最终源码验证，以 [P6C.1 审查修复交付](p6c1-review-fixes.md) 为当前记录。原测试/实验指标未改写。

状态：已完成本地验收（2026-10-23），实际结果以本页及 [机器记录](research/p6c1-validation.json) 为准。基线 main/远端均为 `85e5652bbb57e6099021c88e8a09b8c6d6fa68c3`。本轮不提交/推送，不调用付费模型，不进入 P7 或主动 Agent。

## 已有能力与增量

原 P6C 已有上传/Schema 确认、P2 导入、P3 语义与指标审阅、授权文档、Outbox、审批/取消/恢复和可信 ReportView。原界面是三个标签页。本轮默认 Chat 工作台；左侧历史/数据/报告/管理/诊断，聊天内画像、补充条件、提交审批、执行状态、可信报告和柱图。原页面保留在数据管理，未重建业务服务。

新增 `chat_contracts.py` 为有界 DTO；`intent.py` 是不调用模型的有限规则；`chat.py` 使用现有 WebStore 事务/owner 锁；`chat_routes.py` 继承原 API 中间件。`ui.py` 是导航，`ui_chat.py` 组织交互，`ui_components.py` 只渲染 HTTP 结果，`ui_management.py` 保留原流程。WebStore.command 只增可选已有连接参数，使消息关联与原 Outbox 写入同事务，不改调度/恢复/预算。

| 修改文件组 | 必要性与复用边界 |
|---|---|
| `web/chat_contracts.py` | 会话/消息分页、候选 selection、确认、审批视图的严格版本化 DTO；客户端不能提交 assistant/owner/verdict/审批状态 |
| `web/chat.py`、`chat_routes.py` | 一个交互服务及原 API 的六个路由操作；只协调既有 ProductService 和 WebStore，不增加 Agent 工具或执行引擎 |
| `web/app.py`、`store.py` | 两行注册入口；command 复用调用方事务，原单独调用方式保留 |
| `web/intent.py` | 受支持 SaaS 目标和日期的有限适配，无法识别先澄清，不新增模型会话 |
| `web/ui.py`、`ui_chat.py`、`ui_components.py`、`ui_management.py` | 原单文件界面拆为导航/聊天/共享投影/原管理页；报告和错误渲染只有一份，指标中文标签只在 UI 维护；旧管理功能和有效测试保留 |
| `0007_chat_conversations.py` | owner/TTL 是可见性和保留边界；create/request key+hash 是幂等；sequence 是有界分页；payload/hash 是不可变候选校验；run_id 仅原子关联原执行。无重复状态、预算或 Checkpoint 字段 |
| `test_chat_contracts.py`、`test_chat_postgres.py`、`test_chat_ui.py`、`test_web_ui_retry.py` | 新反例与真实链路；原管理页 ACK 丢失用例仅改入口，不删除断言 |
| README、AGENTS、architecture、api-v1、OpenAPI、product-demo、ADR-015、本页及 validation JSON | 当前实现、历史边界和本轮真实验证分开记录 |

冗余检查确认：未复制 Planner/Worker/Registry/预算/恢复实现；`show_error`、报告和 Run 投影集中到共享 UI 组件，移除了未使用的意图标签常量。上传表单在聊天与管理各有展示入口，后端解析/确认/导入仍唯一，不为合并两个界面而重构原业务服务。P3/P4/P5B/P6A/P6B 核心、原 Web Worker、历史迁移、依赖与锁文件均无本轮修改。用户 v2.4/v2.5 规划文件已有改动单独保留，不属于本轮交付 Diff。

## 会话、候选与审批

Conversation ID 是交互容器；Message ID 是追加记录；Run ID 是一次 Durable 执行；Task ID 仍是原 DAG 内任务。一条 Message 最多关联一个 Run，一个 Conversation 可关联多个 Run。请求响应丢失、并发 launch、重启都使用固定 message 创建键；Run 引用和 Outbox 同提交。

历史只提供候选。新的提问/追问重查当前 grant、已确认指标和真实 MCP 源版本；候选另存 task_payload hash，启动时再次比较，不能从聊天文本、客户端 selection 或旧摘要扩大权限。历史读取逐项重核，失效内容只返回不可用占位；Hash 错误拒绝。GET 不自动执行节点、模型、恢复或结算。

支持 paid_invoice_revenue、客户/订阅流失、活跃订阅、使用量。MRR 无配方明确不可用。识别明确 YYYY年M月/年月、宿主 Asia/Shanghai 的上月/本月，或明确结束不含的 ISO 日期范围；只有月份/多窗口歧义要求补充。多个数据集/指标版本不擅选，缺字段/单位先走原管理确认。用户在卡片显式覆盖日期/指标后追加新候选，不改历史。

“那和九月份比呢？”只将上一 Run 的 Dataset/指标/年份作为候选，再独立形成两个窗口的 P3 请求；只展示并列指标，不计算未经审查的增长率/趋势。因果目标显式 causal_requested，不能由文档相关性证明因果。有限规则不等于理解所有自然语言目标，报告仅覆盖审批卡列出的目标。

聊天强制人工审核。候选提交只创建原 Run，待 awaiting_review 才显示原问题、目标、Dataset/Metric/时间/文档、模型模式、预算和费用提示。批准走原 tasks/approve、稳定幂等键及 Journal；返回修改先持久取消旧 Run，再创建新消息，不能改 Manifest。RECOVERY_UNCERTAIN 显示人工对账，禁止自动重发或替代 Run。

## 数据、展示与保留

CSV/XLSX 解析和确认仍是 P1/P2，聊天卡片不公开业务原始行。TXT/MD 授权上传仍走原文档接口（256 KiB、本地 Embedding）；后续请求显式选择 corpus，不默认自动关联全部文档。完整映射/单位确认仍在数据管理，不提供会猜字段的“自动配置”。

报告直接读取原 P6B ReportView；completed/partial/unavailable/blocked 分开展示。精确 Decimal 字符串和 P3 Evidence/Verification 引用权威，float 仅用于柱图。HTML 禁用，用户文本用 st.text；不展示私密 SQL/行/文档正文/Prompt/Checkpoint/凭据。Trace 默认折叠且脱敏。轮询需用户开启，每 5 秒一次最多 12 次，只有 GET；到审核或终态提示手动刷新原报告。

0007 新建两张私密元数据表，不修改 0001–0006。30 个有效 Conversation/owner，200 条 Message/会话；列表 30、历史分页 20、输入 2000 字符、数据库消息体 32 KiB。TTL 沿用 HostPolicy，不因读取延长；过期拒绝但本阶段不自动清理。无 Run 外键，原维护逻辑不受历史索引阻碍；引用的 Run 被合法保留流程移除后不可用，不能自动重建。Web 对会话只 SELECT/INSERT，对消息另只允许 UPDATE(run_id)，无 DDL/DELETE。

## 部署与验证命令

已有环境只增量迁移与重启，不重新 Seed：

```powershell
$env:DATAPILOT_LLM_MODE='fake'
uv run --locked datapilot migrate
# 原 API/UI 启动方式不变；Docker 只构建/更新 api ui，不能 down -v。
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_RUN_LIVE_TESTS='0'
$env:PYTHONUTF8='1'
# 两个版本串行，不能同时在同一 PG 运行锁故障注入。
.venv\Scripts\python.exe -m pytest -q -x --tb=short --junitxml=artifacts/p6c1/frozen-validation/full-py311.xml
.venv-313\Scripts\python.exe -m pytest -q -x --tb=short --junitxml=artifacts/p6c1/frozen-validation/full-py313.xml
uv run --locked ruff check .
uv run --locked ruff format --check . --exclude docs/codex-prompts-v2.5.md
git diff --check
```

上述为实际验收命令；重复执行时应改 JUnit 路径，保留原结果。格式检查仅排除用户已有、未改动的 v2.5 文档代码围栏，未为通过检查擅改该规划文件。

## 验证进度与限制

最终冻结双版本回归已完成；下列早期结果是历史快照，不替代本节最终验收。本轮新测试为 31 个意图/DTO/边界参数用例、3 个 Streamlit HTTP Mock 用例与 9 个真实 PG/MCP 用例。Fake 只替代模型决策，真实数据库、MCP、P3/P5B、ONNX Embedding 与 pgvector 实际执行。本轮没有付费 DeepSeek 调用，也没有新 GitHub CI。

### 最终冻结验收结果

全部真实执行，`DATAPILOT_RUN_DB_TESTS=1`、`DATAPILOT_LLM_MODE=fake`、`DATAPILOT_RUN_LIVE_TESTS=0`，两版本串行。源快照为 191 个文件，SHA256 清单在两次完整测试开始/结束均一致；完整路径、命令、时间、JUnit hash 见机器记录。

| Python | passed | failed / errors | skipped | 耗时 | 冻结源码一致 |
|---|---:|---|---:|---:|---|
| 3.11.16 | 632 | 0 / 0 | 1 | 1977.187 秒 | true |
| 3.13.15 | 632 | 0 / 0 | 1 | 2000.301 秒 | true |

两份最终 JUnit：`artifacts/p6c1/frozen-validation/full-py311.xml`、`full-py313.xml`；stdout 和 execution JSON 在同目录。唯一 skip 是未授权的真实付费模型测试，PG/MCP 集成并未跳过。原 RAG 跨进程恢复失败用例在两版最终串行回归均通过；保留旧失败及数据库锁日志，不改原 RAG 逻辑。

Ruff check 通过；format check 为 233 files already formatted，仅排除未改动的用户 v2.5 文档。OpenAPI 与运行实例完全相同、内部引用有效；交付 JSON 有效、92 个本地 Markdown 链接存在，git diff --check 通过。最终工作区未提交、未暂存、未推送，无本轮 GitHub CI。没有新增付费模型实验。上述本地结果不能替代未来推送后的 CI，也不代表真实模型稳定成功率。

### 实际发现与最小修复

| 问题 | 位置与处理 | 已执行证据（本地 artifacts，未提交） |
|---|---|---|
| 只读会话表不能 FOR UPDATE | `chat.py`：会话不更新，复用原 owner advisory lock；只在具备 UPDATE(run_id) 的消息行上加锁 | `chat-initial.xml`：1 failed，保留原日志 |
| 并发 launch 的 owner 锁等待超时 | `chat.py`：MCP/网络检查移到锁外；短事务重核消息/hash/唯一键，复用原 command 原子关联 | `chat-pg-round3.xml`：8 passed/1 failed → `concurrent-fix.xml`：1 passed |
| 中文邻接 MRR 漏匹配，选择器可能替代账单收入 | `intent.py`：使用 ASCII 字母边界，显式 MRR 优先拒绝，包括已有收入 selection；未新增配方 | `unit-ui-resume2.xml`：33 passed，含 MRR 覆盖与 Unicode 边界 |
| JSONB 不支持 NUL/孤立 surrogate | `chat_contracts.py`：DTO 先拒绝 NUL、严格 UTF-8；API 返回安全 422，不等数据库内部错误 | DTO 与真实 PG/HTTP 测试均保留两个反例 |
| 审批数据集显示取错 public_schema 层级 | `chat_routes.py`：传入完整原 payload，读取公开 schema.name；响应严格使用 MetricVersion/ReviewDocument | `review-contract-debug.xml`：1 failed → `review-contract-fixed.xml`：1 passed（136.527 秒） |
| UI 把 partial 当作 Runtime 执行状态 | `ui_components.py`：分别展示任务/审批、execution_status、business_completion；按钮仍遵循原 status | `partial-state-before.xml`：1 failed → `partial-state-after.xml`：3 passed（含原审批和 ACK 丢失用例） |

早期测试还修正了 Decimal 字符串精度及 window_days 的断言，均按原 P3 返回值验证，未改业务结果或验证口径。新增审批响应丢失的 HTTP Mock 证明两次明确重试使用同一 approve key，rerun 不隐式审批。

### 历史完整回归与来源一致性

2026-10-23 12:55 开始的旧双版本运行：3.11 为 **626 passed / 1 failed / 1 skipped**（2099.841 秒），3.13 为 **627 passed / 1 skipped**（2132.951 秒），对应 `artifacts/p6c1/full-py311.xml`、`full-py313.xml`。执行记录均为 `source_unchanged=false`：运行期间仍有修改，不能作为最终冻结源码的验收。

旧 3.11 失败在原真实 RAG 跨进程测试 `test_real_rag_persistent_artifacts_cross_process_and_replay[False]`，Run `3f3e95fd-ae54-4996-9370-d2b112533e3e` 记录 `RAG_DATABASE_ERROR`；PG 同时记录 `canceling statement due to lock timeout`（05:10:23.530 UTC）。两个版本并行共用数据库，与既有 ACCESS EXCLUSIVE 锁故障注入冲突是有日志支持的推断。未修改 RAG 超时、恢复或 Verifier 来掩盖此失败；最终双版本改为串行运行。

中途因后续实际修复和测试 Ruff 行宽而停止的 `final/`、`acceptance/`、`acceptance-final/` 目录保留日志及 interrupted 记录，均非验收成功。最终回归单独写入 `artifacts/p6c1/frozen-validation/`，对 src/tests/migrations/scripts、fixtures、pyproject/uv.lock 的逐文件 SHA256 在开始与结束比较；部署镜像另核对全部 19 个 Web 模块。只在两版本结束且源码一致后填写最终结论。

### 浏览器与兼容性记录

浏览器实际使用 `http://127.0.0.1:8501/?conversation=f60ad5fc-0968-4b07-8326-0e90f42bb0f6`，合成文件 `tests/fixtures/semantics/saas_metrics.xlsx`，显式 Schema 确认、受限导入、原管理页面确认 Semantic/Metric，再回对话提交/批准。首个 Run `3225d1a5-2dec-471c-9145-4da0029672f2` 的 2025-10 收入为 **300.0000000000000000 CNY**；追问“那和九月份比呢？”创建独立 Run `629cb330-3a67-429e-9441-923ae59ac233`，并列 10 月 300、9 月 400 CNY，不生成未经验证的环比。首个 Evidence/Verification 为 `dd13fbb4-79ca-4642-873d-cef3aad75bd1` / `4efdbd6f-d0d9-4ba5-b0f4-fd219f3fe392`。

同一浏览器已实际上传并明确授权 `tests/fixtures/reporting/billing.md`，本地 ONNX/pgvector 建立 corpus `ef74f239-4280-4ced-a3ad-95c764fc454b`；因果问题另建 Run `ef1515d2-5cb7-4ab1-858a-c6d2bfd77484`。实际为 SQL verified、RAG unavailable、业务 **partial**，展示 300 CNY 和 `matching_document_or_metric_evidence_missing`，`causal_conclusion_not_verified` 保留，未捏造文档引用；不能称为浏览器正向召回成功。真实检索正向回归由既有 PG/MCP 文档报告测试单独覆盖。附件和文档均为仓库合成 fixture，非生产数据。历史消息不保存文档正文，浏览器不返回业务原始行。

最终镜像已完成 1440×1000 桌面与 480×900 窄窗口检查，窄窗口 viewport/clientWidth/scrollWidth 均为 480；截图为 `artifacts/p6c1/browser-frozen-partial-{desktop,narrow}.png`，结束后已恢复原窗口尺寸。页面恢复同一会话并显示真实部分结果。可见重核延迟已列为限制，没有用动画或重复提交隐藏。

增量迁移为 0007，PG17.11 + pgvector0.8.6，宿主 `.venv\Scripts\datapilot.exe health` 实际返回 healthy、原 240 位客户未变；仅重建/重启 API/UI。最终 API/UI 重启前后，三个新 Run 的会话 digest、Report/Trace digest、payload hash、命令序号、3/4/7 条 Journal 调用记录及模型用量投影全部一致（`chat-proofs-before.json` / `chat-proofs-after.json`）。三次的模型调用投影分别 1/1/3，Fake Token=0，不是供应商费用测量。三个原 P6C 报告经真实 scoped MCP 重读，Evidence/Verification ID、hash、verdict 与上轮及重启前记录完全一致（`original-reports-before.json` / `original-reports-after.json`）。比较汇总为 `restart-comparison.json`，全部为 true。

镜像内 19 个 Web 模块 SHA256 与本地冻结版本逐一一致；经真实 HTTP 会话读取的 OpenAPI 与 `docs/api-v1-openapi.json` 完全相同（24 个路径）。API ready/fake/durable=true/telemetry=off。新旧 Run 保持原 Journal/Checkpoint/Ledger 权威，会话缺失不触发替代执行。

### 验收覆盖索引

| # | 独立场景 | 对应实际用例 / 方式 |
|---|---|---|
| 1 | 收入问题形成可信任务 | `test_chat_verified_report_followup_restart_and_read_only_history`；真实浏览器 |
| 2 | 追问新 Run、旧目标不变 | 同上 + `test_followup_is_new_request_not_mutation_or_invented_growth`；浏览器 300/400 |
| 3 | CSV/XLSX 确认与导入 | `test_csv_attachment_confirm_and_restricted_import_survive_history` + 浏览器多 Sheet XLSX |
| 4 | 未确认映射不可执行 | `test_missing_mapping_cannot_launch_and_fake_approval_is_rejected` |
| 5 | 人工审批及 P3 报告 | 真实 PG happy path + 浏览器；沿用原审批/Journal |
| 6 | 刷新/重连/持久历史 | API 重建后历史及报告 digest 不变；实际 API/UI 重启 |
| 7 | 并发/ACK 丢失/rerun | `test_committed_response_loss_and_concurrent_launch_only_one_run`；HTTP Mock 消息及审批重试 |
| 8 | 中断后的安全恢复 | 原 P5B 跨进程/故障完整回归；聊天只引用原 Run |
| 9 | unknown-outcome 保留预算 | `test_chat_unknown_outcome_never_relaunches_or_releases_budget`；非真实付费请求 |
| 10 | RAG/因果不足诚实 partial | `test_chat_causal_request_is_partial_and_does_not_invent_document_refs` + 浏览器真实文档案例 |
| 11 | owner/过期/撤权 | `test_message_integrity_owner_and_csrf_are_enforced`、`test_conversation_idempotency_ttl_quota_and_web_privileges`、撤权用例 |
| 12 | 伪造审批/消息/注入 | DTO extra=forbid、CSRF、消息 hash 篡改及原 P6A/P6B 对抗回归 |
| 13 | Fake 标识 | Streamlit AppTest + 浏览器明确显示；Live 本轮未调用 |
| 14 | 图表/报告/证据一致 | happy path 对比 ChartSpec/value/evidence；浏览器精确字符串与后端一致 |
| 15 | GET 只读 | 重建 API 后比较 execution.calls 数及报告 digest；原只读状态回归 |
| 16 | 文本/Markdown/Unicode 安全 | UI AST 禁止 unsafe HTML/基础设施导入、HTTP Mock 脚本文本、JSONB 422、原上传防护 |
| 17 | 日期/单位/指标歧义 | 有限意图 31 项参数用例 + 浏览器补充条件卡 |

## 未实现边界与风险

- 仍是可信本地单用户；Conversation ID 不是生产租户隔离，Web 角色的 payload hash 也不是防数据库管理员篡改的签名。
- 意图是有限确定性规则，不能声称理解任意复合问题。审批卡列出的目标为实际分析范围；跨币种、MRR、未审阅配方不猜测。比较仅并列窗口，不计算同比/环比。
- 澄清表单日期预填为合成样例窗口（2025-10-01 至 2025-11-01），不保证保留未形成完整候选前的全部已识别槽位；用户必须核对并显式确认绝对日期，之后还须审核冻结任务。自然语言原句不等于已批准的时间条件，不能把示例默认值当作自动理解结果。
- 历史读取逐条重核源与报告，经 MCP 可有可见延迟；无新增缓存或性能 SLA。需等当前请求结束，不能把页面旧快照误判为按钮无效后重复创建。
- HTTP 重连/rerun 保留当前 session 的消息意图；完整浏览器 session 丢失、且未取得 Conversation ID 的创建 ACK 时应先查历史，不承诺跨设备精确一次的用户意图识别。已持久消息 launch 使用固定 message 身份，重启仍不会创建第二个 Run。
- TTL 仅拒绝访问，不自动清理。现有维护 CLI 管理原执行记录；会话的未来清理/配额运维需独立设计。无新增长期记忆、主动提醒、通用 Scheduler/恢复引擎或后续阶段功能。
- 没有新增真实 LLM/付费模型验证；Fake/Mock 成功不能推断 Live 稳定成功率。最终 CI 尚未运行，因为本轮不提交/推送。
