# P6C 六项 Review 修复记录

审查与开发基线：`e25adfcea94aa79d53e0e888da26c85592230fe6`。仅修复 A–F 及复审发现的两个相关 P2，不进入 P6C.1/P7。本记录为提交前验收快照；2026-10-23 用户另行授权本次本地 Git 提交，未授权推送。本轮验证独立于历史 GitHub CI；没有付费模型调用。数据库、MCP、PG Saver 和文档 Embedding 使用真实实现，模型决策使用 Fake，UI 协议另有明确 Mock 测试。

## 最终复审核验（2026-10-23，Asia/Shanghai）

已读取两份最终回归 JUnit，Python 3.11.16 **68 passed / 0 failed / 0 skipped，902.261s**，Python 3.13.15 **68 passed / 0 failed / 0 skipped，917.191s**。路径分别为 `artifacts/p6c-rereview/regression-py311.xml`、`regression-py313.xml`；两份均覆盖原六反例、两个复审 P2 及其负面断言。当前没有已知仍失败的修复验收项。之前交接时“仍在运行”的状态已由完成的 JUnit 替代，不再作为当前状态。

这 68 项是专项回归，不是完整 pytest。下文每版本 587 passed / 1 skipped 和手动浏览器证明属于**两个 P2 补丁之前的完整验证快照**，保留原数据与失败历史，不冒充最终补丁后的全量或浏览器重测。最终专项包含真实 PG/MCP、文档上传检索报告、API 崩溃重启、Evidence/Verification ID/hash/verdict 不变、unknown-outcome 预算保留以及 Streamlit Mock 重试。

| 复审新增 P2 | 根因及最小修复 | 实际证据 |
|---|---|---|
| 旧创建请求升级后无法幂等重试 | 新增 host_policy_sha256 使旧 web_requests 的 body_hash 不匹配；store.command 仅兼容原载荷缺少该新增 pin、其余内容及旧 hash 完全相同的 create 重试，返回原 ACK，不改写旧载荷或授予执行权限 | test_upgrade_retry_preserves_legacy_creation_key；原请求复用同一 Run，问题/宿主策略变化返回 409，撤回来源返回 403；两个版本均通过 |
| 健康孤儿 Worker 占满槽时，排队 Run 被误隔离 | 原 Dispatcher 只探测 Run 锁，反复启动子进程并耗尽三次 busy 配额；现在派发前同时探测原 owner 槽锁 6156，满槽时等待、不消耗派发次数，释放后正常执行 | test_healthy_orphan_capacity_does_not_quarantine_waiting_run；真实 PG advisory lock 与真实子进程，满槽四次 poll 零启动，释放后 awaiting_review；两个版本均通过 |

独立复现文件 `artifacts/p6c-rereview/test_rereview.py` 保留：修复前 **2 failed / 0 errors，35.161s**（`before.xml`），修复后 **2 passed，40.889s**（`after.xml`）。非忽略的 `tests/test_web_review_fixes.py` 保留这两个反例并增加权限/策略负面断言。两个修复仅修改现有 Store、Dispatcher 与该测试文件；没有新字段、类、状态机、账本、迁移或框架。旧未注册 Run 的 RECOVERY_POLICY_UNBOUND 和已注册 Run 的 Manifest 校验继续生效。

最终源码一致性检查：此前 16 个受验源码指纹中，13 个不变，仅 store.py、worker.py 和 test_web_review_fixes.py 对应上述补丁；所有 Python 源文件修改时间均早于两次专项启动。没有在专项启动前额外生成 SHA 清单，因此修改时间只作为连续性核查依据，不能冒称当时已留存哈希证明。最终审计冻结 157 个代码/依赖文件的 SHA，保存在 `artifacts/p6c-rereview/final-source-check.json`，提交前再次比对；结构化记录保存其 hash。原反例、11 份历史 JUnit 和两份用户 Prompt 的 SHA 均保持不变。

Ruff check、format（220 files；排除未改动的用户 v2.5 Markdown）、git diff --check 通过。当前路由/DTO 生成的 OpenAPI 与 docs/api-v1-openapi.json 完全一致；该纯 Schema 检查 Mock 元数据 Store，不冒称 PG 测试。JSON 与文档引用在提交前再检查。未重新部署 Docker 镜像、未重复手动浏览器演示、未重跑完整 pytest、未调用付费模型、未运行新 GitHub CI；当前镜像仍为复审前已验证快照。这些边界不替代已完成的源码专项验收。

本次提交范围为：7 个 src/datapilot/web 文件（app、client、contracts、service、store、ui、worker），scripts/web_recovery_probe.py，3 个 Web 测试文件，以及 docs/api-v1.md、docs/api-v1-openapi.json、本记录、research/p6c-review-fixes-validation.json，共 15 个文件。用户原有 docs/codex-prompts-v2.4.md 和新增 v2.5.md 不纳入提交；其余 P3/P4/P5B/P6A/P6B 核心、迁移、依赖和锁文件未改。

若需复验，先设置以下环境，再运行专项；使用新 basetemp 后缀，保留原始证据：

```powershell
$env:PYTHONUTF8 = '1'
$env:DATAPILOT_RUN_DB_TESTS = '1'
Remove-Item Env:DATAPILOT_RUN_LIVE_TESTS -ErrorAction SilentlyContinue
$targets = @('tests/test_web_contracts.py', 'tests/test_web_postgres.py', 'tests/test_web_recovery_postgres.py', 'tests/test_web_review_fixes.py', 'tests/test_web_ui_retry.py', 'tests/test_persistence_contracts.py', 'tests/test_recovery_versions.py', 'tests/test_postgres_integration.py')
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
.venv\Scripts\python.exe -m pytest @targets -k 'not management_reentry_and_cli_health' --junitxml="artifacts/p6c-rereview/recheck-py311-$stamp.xml" --basetemp="artifacts/p6c-rereview/tmp-recheck-py311-$stamp" --tb=short -q
.venv-313\Scripts\python.exe -m pytest @targets -k 'not management_reentry_and_cli_health' --junitxml="artifacts/p6c-rereview/recheck-py313-$stamp.xml" --basetemp="artifacts/p6c-rereview/tmp-recheck-py313-$stamp" --tb=short -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check --exclude docs/codex-prompts-v2.5.md .
git diff --check
```

该专项明确排除 management_reentry_and_cli_health 管理入口重入用例，不执行管理初始化或重新 Seed；真实 reader 权限、PG17/pgvector、SQL 安全/超时/行数仍在专项覆盖内。需要完整回归或新镜像浏览器复验时另留新日志，不能覆盖下方历史快照。没有尚待实现的 P2 修复；后续仅在新变更或验证失败时继续处理，不自动进入其他阶段。

## 复现与根因

原六个独立反例准确路径为仓库内被忽略的 `artifacts/p6c-review/test_boundaries.py`，历史 JUnit 与 summary 保留。开发前再次执行该原文件，得到 **6 failed / 0 errors，88.14s**，记录 `artifacts/p6c-fixes/before-reproduced.xml`。反例已按原意保留到非忽略的 `tests/test_web_review_fixes.py`，纳入本次授权提交；没有删除有效断言以绕过缺陷。

| 项 | 实际根因 | 最小修改位置 | 关键验证 |
|---|---|---|---|
| A / P1 | Worker 只读一次 cancel_requested；Runtime 不存在时取消被吞掉，旧 Worker 随后注册并完成 | web/worker、store、app、service | 注册前/初始化中取消、并发时序、真实 API 重启、旧创建重放、取消不能被审批/恢复清除、零调用 |
| B / P1 | 客户端每次 POST 随机新 key，UI 仅在收到 ACK 后保存 Run | web/client、ui | 后端真实提交后丢失响应只关联原 Run；HTTP 客户端重建、Streamlit rerun/重连/明确重试；新任务另起意图 |
| C / P1 | worker.main 从 outbox 的旧 Settings 重建执行策略，绕过 API 当前策略拒绝 | web/worker、service、store、app | 当前宿主策略与跨进程 hash 检查、模型/预算/数据库身份变更拒绝、密码轮换不误判、原 Manifest 保留 |
| D / P2 | 轮询异常直接结束唯一 Dispatcher；子进程退出未记录，命令持续 pending 并反复启动 | web/worker、store | 瞬时轮询错误存活、连续三次失败关闭、真实子进程异常只派发一次且其他任务可执行、遗失派发/已知 busy 有界 |
| E / P2 | Corpus 列表逐项调用 dataset()；一个撤回授权抛异常导致整个列表 403 | web/store | 在同一查询快照按 owner、enabled、Dataset/version JOIN 过滤；合法 Corpus 保留；继续检查两侧 hash、版本/源 pin 与 CorpusPin 身份 |
| F / P2 | Store 返回最多 101 项，响应 DTO 上限 100，未切页就校验导致 500 | web/store、app、contracts、ui、service | 真实 PG Web 元数据 100/101/205 项分页及页外空集合/非法参数；HTTP 超量反例返回有界 200；入库授权不依赖第一页 |

F 的 205 项是合成 Web grant 元数据，不冒称 205 次完整业务文件导入。实际 CSV/XLSX→PG→MCP→指标/报告仍由原 P6C 与全量集成测试覆盖。

## 复用机制与新增项的必要性

没有新增 Scheduler、Agent 状态机、恢复引擎、账本、数据库表、迁移、依赖或模型工具。

- A：复用原 `run_durable(interrupt_before=["planner"])` / 官方 Saver 建立零模型、零指标调用的初始化点；重新读取持久 Outbox 后才走原 resume。`cancel_requested` 单调 OR，拒绝新审批/恢复重置；取消重放仍传播到现存 Runtime。原 P5B 取消和未知结果的预算规则不变。只对实际不存在 Runtime 的取消投影零 usage。
- B：新增纯客户端 `creation_intent` 函数，保存 body/key 快照；UI 的 `create_intent` Session State 跨 rerun/HTTP 重连复用，ACK 后仅附 run_id。`_pending_create` 为未显式传 key 的 HTTP 调用保留失败意图。两者分别覆盖调用者和 UI 生命周期，不成为权限来源，不自动重发请求。
- C：`host_settings_hash / publish_host_settings / check_host_settings` 仅比较可信配置，复用 `web_requests` 的内部 `host_policy` 元数据记录，不保存凭据。每个新 outbox 增加一个 `host_policy_sha256`，使未注册任务也绑定数据库身份。`settings_provider` 只在可信 API 进程绑定；Worker 不从模型或 outbox 获取它。ProductService 的受控 Settings setter/bind 使宿主配置变更同步发布 hash，Worker 只有比较权。
- D：原 Dispatcher 拆出一次 `poll` 以局部捕获异常和测试；`poll_failures / last_error` 仅为宿主进程健康/有界失败计数。`sequences` 绑定子进程与它实际派发的 command_seq，防止旧退出覆盖新命令。Store 的 `dispatch_start / dispatch_failed / dispatch_busy` 复用 outbox 的 status_hint、processed_seq、last_error：`dispatching:<seq>:<attempt>` 表示已预留派发，`dispatch_busy` 仅接受执行前退出码 75。没有第二份外部调用日志；权威调用、预算和恢复仍在 P5B。
- E/F：`dataset_payload` 复用三处 hash/身份核验，消除原 N+1 授权查询的撤回竞态；`has_dataset` 保证导入授权不受列表页截断影响。新增 DTO `offset / limit / next_offset` 仅表达有界页面，旧 datasets 字段保留。OpenAPI 只同步这些实际参数/字段。
- 测试进程 driver 显式把 Fake 模式传播给其子进程，避免测试重新读取当前 `.env` 的 live 默认值；这不是生产绕过宿主策略。

清理过的冗余实现：移除了跨 Runtime 初始化持有的新增注册锁（补测证明会碰到现有 Web lock_timeout）；最终不增加该锁。派发标记直接复用 Outbox，移除了临时独立派发 receipt；不重复保存完整数据库身份对象。Dataset payload 校验集中复用，历史单项授权仍保留。

## 数据与历史 Run 兼容

不改原 PostgreSQL 数据、不重新 Seed、不删卷；只增加测试授权的独立合成 Dataset/Run 和必要的宿主 Web 元数据。`src/datapilot/persistence/`、原 P3/P4/RAG/Report 业务源码、迁移、锁文件保持不变。

已注册历史 Run 继续原 Manifest、来源版本、Artifact/Journal/Ledger 与 P3 Evidence/Verification 重查，不补写或变更原 verdict。缺少新 pin 的旧未注册载荷无法证明原数据库身份，返回 `RECOVERY_POLICY_UNBOUND`、要求人工重新授权；不静默迁移为可执行。已接受取消的旧 outbox 标记保留且不能逆转。

## 复审前完整测试与浏览器快照（历史记录）

执行命令、JUnit SHA、真实统计和各阶段源码指纹见 [结构化验证记录](research/p6c-review-fixes-validation.json)。以下来自复审前实际执行，不以历史 CI 替代本地验证。该次全量执行期间源码冻结，部署的 12 个 Web 源文件与当时本地一致；后续两个 P2 补丁改变了 store/worker，当前镜像尚未包含这两个补丁，最终源码验证见文首专项。

| 验证 | 真实结果 | 耗时 | JUnit（位于 artifacts/p6c-fixes/） |
|---|---|---|---|
| 开发前原六反例 / 3.11 | 6 failed，0 errors | 88.138s | before-reproduced.xml |
| 复审前原六反例 / 3.11 | 6 passed | 78.081s | counterexamples-final.xml |
| 扩展反例 + Streamlit Mock / 3.11 | 19 passed | 298.947s | expanded-second.xml |
| 原 Web/恢复初次专项 / 3.11（中间快照） | 24 passed | 456.873s | web-first.xml |
| **完整回归 / Python 3.11.16** | **587 passed，1 skipped** | **1645.21s** | full-py311.xml |
| **完整回归 / Python 3.13.15** | **587 passed，1 skipped** | **1680.41s** | full-py313.xml |

唯一 skip 是 `tests/test_live_model.py` 的显式付费 API 测试，本轮未授权、不运行。真实 PG17、pgvector、MCP、ONNX 文档、API/Worker 进程重启及原 P5B unknown/预算/P3 ID/hash/verdict 断言都实际运行。该快照 Ruff、format、Diff、JSON 和引用检查通过；当时 main/本地 origin/main 为审查基线，未 commit/push。历史“未提交”不撤销用户随后对本次本地提交的授权，亦不构成当前 GitHub CI 结果。

实际全量命令（已安装的 uv.lock 对应环境）：

```powershell
$env:PYTHONUTF8 = '1'
$env:DATAPILOT_RUN_DB_TESTS = '1'
Remove-Item Env:DATAPILOT_RUN_LIVE_TESTS -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -m pytest --junitxml=artifacts/p6c-fixes/full-py311.xml --basetemp=artifacts/p6c-fixes/tmp-full-py311 --tb=short -q
.venv-313\Scripts\python.exe -m pytest --junitxml=artifacts/p6c-fixes/full-py313.xml --basetemp=artifacts/p6c-fixes/tmp-full-py313 --tb=short -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check --exclude docs/codex-prompts-v2.5.md .
git diff --check
```

原忽略目录六反例需单独运行，先创建 artifacts/p6c-fixes 父目录并将 tests 加入 PYTHONPATH；具体命令在 JSON 中。不要将其 conftest 插件和 tests/ 在同一 pytest 收集调用中重复加载。

浏览器使用重建后的 Fake 模型 Demo 镜像，真实走合成工作簿解析/预览→Schema 确认→PG 导入→Semantic/Metric 审阅→持久创建→宿主批准→300 CNY 报告/图表。Dataset `b12beb40-427d-5fe2-92e8-44137ce5228d` v1，新 Run `f3e0ed7d-e5f0-492e-9831-501f39e6e4ca`；Evidence `0b6f18e7-08fa-4270-b994-404e00d57ea6`，Verification `53e38105-185e-4c71-8b56-7efd86a177c5`。API/UI 实际重启后，浏览器从任务列表恢复同一报告；真实 MCP 重读其 verdict 仍为 verified，完整报告 hash `1ebeccac089b383d0840c99d7745b6d7a72bb5f4a92cb9bc0610a57d6d7f962c` 不变。

同时复核上轮已有 Run `b3356290-33c6-4ac4-b957-93b881fc841c`：原 Evidence `5c0143bc-edb1-485b-8223-f0282c684e19`、Verification `91e0dd31-5540-4827-86c2-35a96b9259e8`、各自 hash、verified verdict 与完整报告 hash 均在本轮重启前后完全一致。原 PG 容器 `6f559b06708f` 持续健康，未替换。截图、两次只读证明和原始 JUnit 保存在忽略的 artifacts/p6c-fixes/，结构化记录保留 SHA，避免把私密运行目录提交到 Git。

开发过程失败也保留在 `artifacts/p6c-fixes/`：初次缺少 basetemp 父目录导致 1 failed/5 errors；修正调用后才得到上述 6 个真实反例失败。把独立反例插件与 tests/conftest 合并收集曾报重复注册，之后分开执行。扩展第一轮 11 passed/4 failed 包含两处断言应检查结构化 error.code、初始化锁超时和开发中父/子进程源码版本混用；对应记录不删除，不算最终通过。

## 限制与风险

- 仍是可信本地单用户。宿主策略 hash 由受限 Web 元数据角色维护，不是抵抗数据库管理员篡改的签名或生产租户鉴权。配置变更须由可信宿主发布/重启；不宣称撤销已发出的外部请求或退款。
- 新任务零调用初始化增加一次原 Runtime/MCP 建立开销；没有重写原执行/恢复机制。初始化中若注册已提交但官方初始 Checkpoint 尚未保存即崩溃，沿用原 P5B 缺失状态拒绝，不猜测执行或自动修复。
- 未确认退出/遗失派发可能已做完工作，也可能尚未开始；保守停止，需要宿主核对。没有提供强行清空 Journal、重置预算或自动解除 unknown 的入口。poll 熔断后需修复环境并重启 API。
- offset 分页按当次授权快照排序；并发新增/撤回时跨页不保证全局快照，应刷新。Corpus 保留原 100 项有界列表，未扩展为通用分页系统。
- UI 创建意图覆盖同一 Streamlit Session 的 rerun/HTTP 失败/重连。完整 Session 丢失应先查看已有任务，不声称跨浏览器新 Session 的自动意图恢复。
- 本轮不做付费模型质量评测、P6C.1 或其他阶段；按最新授权完成本地提交，不自动推送。最终 SHA 在 Git 成功后另行报告，本记录不嵌入自引用提交 SHA。
