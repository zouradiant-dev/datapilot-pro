# P7 Unified Regression & Release Readiness

**结论：PASS WITH LIMITATIONS — Ready for scoped Smoke。** 双版本最终完整回归、真实隔离 PG/MCP/BGE、用途确认与审批、浏览器及进程/数据库恢复验收通过。可在另行授权后先建立 New Implementation Freeze，再进行有界 DeepSeek Smoke；本轮没有建立正式 Live Freeze、调用付费模型、重跑 Holdout、提交/推送或进入 Gate 3。

## 范围与保护基线

当前 HEAD `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`；开始时已有的 Phase 1–4 和 P7 未提交工作全部保留。以 `artifacts/p7/unified-regression/before-files.json` 的 763 份文件 SHA、初始 Git 状态及原 Gate 2B 数据库逐行 SHA 为保护基线。本轮改动单独对照该基线，不将整个 Git Diff 归为本轮。

原首次 Live 仍为 31/60 observed、29 not_run、61 次调用/77,897 Token；Scorer v1 25/31、v2 只读修订 26/31，Gold/Seal 和原费用记录不改。本轮模型决策仅 Fake/脚本化及 HTTP SDK Mock；真实数据面为 PG17、pgvector、本地 BGE、MCP 和原 P3/Report/恢复链路。

## 最终测试总览（按唯一身份去重）

| 环境 | 本地单元/契约 | 真实 PG/MCP 集成 | 最终完整结果 | 耗时 |
|---|---:|---:|---|---:|
| Linux Python 3.11.14 | 768 | 217 | **985 passed / 1 Live skipped** | 1447.015 秒 |
| Linux Python 3.13.11 | 768 | 217 | **985 passed / 1 Live skipped** | 1589.375 秒 |
| Windows Python 3.11.16 | 768 passed | 不以本行重复计算 | 218 deselected（217 集成＋1 Live） | 27.588 秒 |
| Windows Python 3.13.15 | 768 passed | 不以本行重复计算 | 218 deselected（217 集成＋1 Live） | 29.166 秒 |

两版 Linux 各收集 **986 个唯一测试身份**，集合完全相等；最终均 0 failures、0 errors、0 xfails、0 deselected、0 environment-blocked。唯一 skipped 是 `test_live_model.py` 的付费 Live opt-in 守卫，本轮未授权。Windows 只补充平台单元/契约覆盖，不声称 Windows 完整 PG 集合全部通过。畸形 usage 故障输入各产生一条预期 Pydantic 序列化 warning；没有忽略失败。

同一测试在不同轮次/版本反复执行不增加唯一分母。14 项 HTTP SDK Mock、五项新用途确认 PG 测试、七项 Phase 4 PG/Durable 测试等都已包含在完整矩阵，不能再加到 985。测试是工程验收，不是 985 个独立业务 Holdout，也不代表 DeepSeek 业务成功率。

覆盖包括 SQL AST/Reader/动态 Dataset 授权、独立 SQL 对照、P3 口径/单位/版本/六层规则、真实 BGE/pgvector/MCP 来源与引用、事实不足/部分覆盖/伪造引用、SQL+RAG 报告、Context L0–L4、并发父子预算、跨进程 Journal/Checkpoint/Artifact、unknown-outcome、Web Host/Origin/CSRF/幂等/取消/审批和隔离维护。按测试文件划分的专题集合中，Durable/恢复相关 61、Web/聊天相关 125、P3/报告相关 173；它们含单元与集成且互有交集，不作为额外合计。

唯一身份、真实集成差集、JUnit 与控制台记录位于本机忽略目录：

- `artifacts/p7/unified-regression/linux311/final3/full.xml`、`linux311/final3-console.log`
- `artifacts/p7/unified-regression/linux313/final3/full.xml`、`linux313/final3-console.log`
- `stable-win311.xml`、`stable-win313.xml`、`final-test-counts.json`、`final311-counts.json`、`final313-counts.json`

这些本机证据没有自动上传 GitHub。最终源文件 SHA 记录 `stable-candidate-v3.json`（252 文件）只是本次验证候选，不是正式 Live Implementation Freeze；最终 API 镜像 114 份源码/迁移文件和两版测试容器各 246 份源码/测试/脚本/迁移文件与工作区逐字节一致。四套 Python 实际已安装依赖均无锁文件版本不匹配。

## 本轮最小修复

1. Web 复用原 ChatSelection/DocumentQuery、候选与审批，明确用途和待核验事实；客户端只能描述要求，不能提交事实证明或扩大 Corpus/Dataset scope。原 Rule-only `intent.py` 和冻结语义候选保持原字节。
2. `Journal` 的两个缓存恢复入口复用同一有界解码校验。原响应畸形时返回 RECOVERY_CORRUPT，不重新请求、不修改原响应或保守计账；无新状态、迁移、恢复引擎。
3. Phase 4 正式测试改用临时输出与仓库内探针，去掉对本机忽略目录脚本的依赖。原未知结果故障与预算断言保留。
4. 旧正向文档夹具显式声明其总结用途；HTTP 故障夹具给 SDK 冷启动足够外层时间，实际注入的 read timeout/cancel 保持；纯 Mock 夹具使用虚拟 Key，不依赖操作者真实凭据。
5. Docker 镜像原缺少 Alembic 配置/迁移目录，补复制未修改的配置和历史迁移。Schema/角色策略、依赖和锁文件不改。

具体接口见 [API v1](api-v1.md)。公开 Web 尚不能签发可信 Fact Proof；没有证明时仍 partial/unavailable，不能将输入文本当作 verified。

## 环境与可复现入口

本轮日期 2026-10-26（Asia/Shanghai）。Windows 本地 Python 3.11.16 / 3.13.15；Linux 完整矩阵为 Python 3.11.14 / 3.13.11，按未修改的 `uv.lock` 执行 `uv sync --locked`。不能把 Linux 完整矩阵称为 Windows 全集。Docker VM 共享约 7.6 GiB 内存，测试容器未设置额外 CPU/内存配额，两版同时执行；这不是性能或 SLA 基准。

新建项目 `datapilot-p7-unified`（PG 55441、API 8911、UI 8511）与 `datapilot-p7-unified313`（PG 55442），仅测试这些隔离资源。真实 PG 17.11、pgvector 0.8.6，镜像固定 SHA；迁移 0007，官方 Checkpointer 显式初始化成功，首次各 Seed 240 客户。旧 `datapilot-pro` 和 `datapilot-p7b` 未被初始化、Seed、重启或清理。

核心入口：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest -m "not integration and not live" -q
.venv-313\Scripts\python.exe -m pytest -m "not integration and not live" -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check src tests scripts migrations
git diff --check
```

全仓 Linux 入口为私密验证目录 `linux-test-driver.py` 调用 `pytest -p no:cacheprovider --basetemp=... --junitxml=... --tb=short -q`，不是筛选通过用例。`linux-run.py`/`infra.py` 先验证确切新项目、镜像、标签、卷和 DSN，再配置隔离实例；守卫仅用于测试基础设施，不修改 Runtime 授权。配置 `DATAPILOT_RUN_DB_TESTS=1`、`DATAPILOT_P7_ISOLATED=1`、`DATAPILOT_RUN_LIVE_TESTS=0`、Fake 和空 API Key；两个 Gate 2 Mock 用例在自身范围使用虚拟 Key/固定 profile，并替换 Transport，绝不访问供应商。

正式 Phase 4 故障探针移入 `scripts/budget_context_probe.py`：原七项测试继续经原 `run_durable`/Journal/账本与故障切点验证；只把输出改为临时目录，避免依赖本机忽略文件。新探针是非模型测试入口，不是第二套恢复机制。

## 接线与变更必要性

对照本轮开始的文件 SHA，业务修改仅八个 Web 文件及一个 Journal 文件：

| 文件 | 最小作用与必要性 |
|---|---|
| `web/contracts.py` | `FactRequirement` 仅有 ID/说明，严格拒绝 proof/citation/verified 等额外字段；文档用途与最多八个事实要求有界校验；序列化省略旧默认字段以保留旧哈希。 |
| `web/chat_contracts.py` | 原 ChatSelection 接收显式用途与要求，禁止重复事实 ID/矛盾用途；旧请求不新增空字段，保持幂等输入哈希。 |
| `web/chat.py` | 在原冻结解析器之后应用用户明确选择；未确认用途继续澄清，不让模型批准。 |
| `web/service.py` | 新文档任务未确认用途则拒绝；绑定既有 DocumentGoal，无 proof 的要求保留未验证；恢复旧 Scope 不隐式变成 summary，仍校验原授权哈希。 |
| `web/chat_routes.py` | 原审批投影保留用途与 required_facts，不在中途丢字段。 |
| `web/ui_components.py` | 一个共用用途/要求控件，复用原表单；说明用户文本不是事实证明。 |
| `web/ui_chat.py`、`web/ui_management.py` | 将控件值传给原 ChatSelection/CreateTask；无新会话/审批/调度状态。 |
| `persistence/journal.py` | 两个既有恢复入口共用有界模型响应解码；缓存畸形时类型化 RECOVERY_CORRUPT，解码前不释放预留，不改历史调用或重新发送。 |

新字段只表达用户要求，不授予 Dataset/Corpus/Document 权限。旧客户端可读取旧记录，创建未声明用途的文档任务需确认；旧未确认报告不能被新规则升级为 completed。冻结 `web/intent.py`、`web/semantic_intent.py`、P3/Report/预算与检索生产代码保持本轮前 SHA。

其他改动：Dockerfile 补入原 Alembic 配置和迁移目录；CI 增加隔离 PG 的 HTTP SDK Mock 故障测试，格式检查显式覆盖全部 Python 目录，避免改写负责人规划 Markdown 的代码围栏。新正式测试为 `test_document_confirmation_web.py` 三项与 `test_document_confirmation_postgres.py` 五项。五份旧测试仅修复显式用途、Mock 配置和故障测试冷启动环境；`test_phase4_postgres.py` 复用原七项测试/断言，改用正式探针和临时输出。未删除安全断言、未新增 skip/xfail，原 bad_usage 的 xfail 在红例得到修复后移除。

`docs/api-v1.md` 与实际 `app.openapi()` 生成的 `docs/api-v1-openapi.json` 同步新契约。未修改历史迁移、Schema、grants、依赖或锁文件；不重建 Registry、Scheduler 或预算引擎。

## 历史报告与数据库保护

原 `bh2-024` 签名采集载荷 SHA `13c229cbe4b37af827667c29b713f72da317d062f99aaa8ddf0eaa37438376e4` 保留，旧报告仍 partial。现规则投影因旧文档用途未确认而为 unavailable，其他报告字段一致，`verify_report` 返回 REPORT_EVIDENCE_INVALID。

先记录宿主端点不匹配的 RECOVERY_IDENTITY；随后在原可信 Docker 端点执行原 `inspect_run` 的只读验证：端点身份匹配后，在 restored proof 检验阶段以 RECOVERY_IDENTITY 拒绝不兼容报告。没有运行节点、重放模型、恢复旧任务、重评分或绕过 Manifest。它证明安全拒绝，不代表旧报告可在新规则下完成恢复。

历史库前后全部逐行 SHA **完全相等**：273 Evidence、265 Verification、122 Semantic、135 Metric、503 Run/账本、1,962 calls、1,531 Artifacts、6,860 events、4,985 Checkpoints、21,705 checkpoint_writes、8,921 blobs，以及其余 Web/RAG/迁移元数据均相同。不存在覆盖、删除或新增历史行。证据见私密 `before-database.json`、`final-database.json` 和 `final-database.log`。Gold、Seal、Scorer、原结果与费用文件逐字节核对另列最终汇总；用户 v2.4/v2.5 规划不改。

## 明确的非阻断限制

- 不支持可信最新/跨来源同一时点快照，继续拒绝 snapshot_not_attested/unsupported_requirements。
- Token 字节估算仍保守；本轮没有调整系数、预算上限或将缓存折抵逻辑预算。
- Web 只能提交事实要求，不能签发可信 Fact Proof；开放事实/因果不能证明时保持 partial/unavailable。
- 原问优先 RAG 候选未合并，Embedding/0.55/Top-k/两次搜索与 Completion 规则不改。
- 原报告规则冲突时恢复失败关闭；没有大型旧报告兼容引擎。
- 本轮没有真实模型质量、Token、缓存、计费或性能结论；供应商端 exactly-once 仍不能保证。
- GitHub 远端 CI 为 not_run，没有 commit/push/workflow dispatch；只有本地 CI-equivalent。

## 失败历史与分类（保留，不累计进最终去重分母）

| 原始记录 | 结果/根因 | 分类与处理 |
|---|---|---|
| `initial-unit-311/313.xml` | 各 764 passed / 1 failed；GBK 默认读取 UTF-8 文件 | Windows 环境：明确 PYTHONUTF8=1，未改冻结解析器。 |
| `pre-fix-confirmation.xml` | 2 failed：旧 Web 无用途/事实要求入口 | 本轮授权接线，新增三项单元及五项真实集成反例。 |
| `initial-pg311.xml` | 174 passed / 9 failed / 13 errors / 16 skipped | 开发拷贝缺临时目录/Alembic、旧用途夹具和私有探针依赖；不是最终源码。 |
| `pg313/full-pg313.xml` | 204 passed / 12 failed / 1 xfailed | 开发/混合拷贝环境与旧夹具；原 bad_usage xfail 不能当通过；最终矩阵移除该标记。 |
| `pg313/bad-usage-red2.xml` | 1 failed：畸形缓存 usage 恢复返回未分类异常 | 产品边界缺陷：Journal 类型化 RECOVERY_CORRUPT；随后 HTTP Mock＋真实 Journal 14 passed，保守预算与零重发断言保留。 |
| `pg313/legacy-purpose-red.xml` | 2 failed：旧正例未显式声明用途 | 夹具过时：声明 summary，未改完成标准或安全断言。 |
| `linux311/round1-preserved.xml` | 972 passed / 2 failed / 11 setup errors / 1 Live skipped | 首轮临时目录父路径缺失、Mock 依赖操作者配置；环境补齐，不能以这一轮作为最终验收。 |
| `linux313/round1-preserved.xml` | 983 passed / 2 failed / 1 Live skipped | Mock 缺 Key/model/profile；首次只补 Key 仍被 harness 重载环境覆盖，中间轮日志保留后停止。最终同一隔离 DSN 显式固定纯 Mock profile，并取得 15 passed 的定向证据。 |
| `ruff-format.log` | 全仓格式检查要求改写既有 `docs/codex-prompts-v2.5.md` 代码围栏 | 负责人规划文档不改；格式入口覆盖全部 Python 代码目录，Ruff lint 仍检查全仓。 |

中间失败未删档，最终完整集合重新执行全部适用用例。最终统计只按 testcase 的模块/名称/参数身份去重，不相加多轮运行次数；定向 77/14/5 等已包含在完整集合中的用例不另加通过数。

## 浏览器、审批和真实基础设施结果

浏览器验收使用本轮隔离演示 `http://127.0.0.1:8511/`，API 为 8911；没有替换用户原 8501 服务。先在浏览器选择合成样例、查看 Schema、确认入库及字段/指标口径；文档通过已授权 HTTP 摄取公开合成 `billing.md`，真实本地 ONNX Embedding，明确不是浏览器文件上传。

实际 Chat-first 文档路径：未声明用途/Corpus → 待确认 → 用户选择授权 Corpus 和 summary → 新消息/原审批 → Durable RAG/Report → 保守 unavailable。默认 Fake 未取得可发布文档引用，因此没有伪称浏览器 RAG 正向 completed。真正的 locate/summary completed、facts unavailable、conclusion partial 四种结果由五项 **真实 HTTP＋PG＋MCP＋BGE＋脚本化决策** 的正式集成测试覆盖；不是 DeepSeek 质量测试。用户改变用途追加新 Message/Run，原 payload/hash 不变，未授权 Corpus/伪造 Document 参数被拒绝。

浏览器 SQL 路径已实际提交并审批：`分析2025年10月已支付账单收入` → completed/succeeded → **300.0000000000000000 CNY**，时间右开 `[2025-10-01,2025-11-01)`，Evidence `f2405ab9-4fd7-4003-bacd-8dab2f4260b6`、Verification `989bf839-ef74-4b84-9e05-e8c89647815c`。数字来自独立合成样例与原 P3，不是 LLM 心算。图表标明 CNY；精确值以 P3 原值为准。

最终源码镜像构建成功；两个新环境完成 db-init/migrate/runtime-init/seed/health。原镜像实际缺 Alembic 配置/迁移文件，本轮补复制后可随镜像部署未修改的迁移。Compose healthcheck/API/UI 启动、配置校验及 API/UI 重启通过；24 路径的实际 API OpenAPI 与交付 JSON 完全相等。重启前后的 Conversation、两条 Run 报告逐字段一致，P3 Evidence/Verification ID、hash、verdict 均保持。

仅本轮新 PG 实际 stop/start，postmaster 时间从 `2026-10-25 19:59:29.906060+00:00` 变为 `2026-10-25 22:10:45.748510+00:00`。一条 worker 后暂停任务和一条完成任务在中断前存档；断连期间恢复明确 OperationalError，NoModel 计数 0。恢复后两条均 succeeded，完整 Journal 行 SHA、全部父子 Ledger/receipt、已存 Artifact ID/SHA 和 usage 一致，新增模型调用为 0。该探针验证执行恢复协议，普通 SQL 结果不冒称 P3 verified；P3 业务证据保持另由真实报告集成和浏览器重启核对。

故障/恢复记录在 `restart/before.json`、`during.json`、`after.json`、`journal-row-hashes.json`、`instance-result.json`。没有清库、删卷、重 Seed 或重启旧数据库。隔离资源保留供复核。

## 最终安全与发布判定

本轮相对 763 文件保护基线修改 19 份既有文件，新增两份确认测试、一个复用原 Durable 的正式测试探针及本报告；其余 744 份原文件不变、0 丢失，373 份被保护的历史 artifacts 全部保持 SHA。9 份既有 P7 生产代码修改保持本轮前版本；本轮九份生产文件（八 Web＋Journal）共增加 128 / 删除 9 行，无新数据库字段/迁移、Agent、状态机、Ledger 或恢复引擎。共享 UI 控件与 Journal 解码避免重复实现；没有删除有效反例。

Ruff lint 全仓通过，235 份 Python 文件格式检查通过，`git diff --check` 通过；JSON/OpenAPI/本地文档引用核对通过。日志已扫描本轮生成的 DB/Host 凭据，无公开验证日志匹配，私密配置继续被 Git ignore。HEAD 仍为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`，分支 main，无 staged 内容，不自动 commit/push。GitHub CI **not_run**，本地 CI-equivalent 通过不能替代远端结果。

**PASS WITH LIMITATIONS — Ready for scoped Smoke。当前没有阻断本地单用户有界 Smoke 的未解决工程缺陷。**

| 限制 | 根因/证据 | 最小后续行动 | 是否阻断 scoped Smoke |
|---|---|---|---|
| 真实模型行为未验 | 本轮 API 0 次，唯一 Live 测试 skipped；Fake/Mock 不证明实际质量 | 另行批准正式 Freeze 与有界合成 Smoke，完整保留负结果 | 否；这是 Smoke 待验证目标，不是已通过 |
| 最新/共同快照缺能力 | 原 Phase 4 保守拒绝测试通过 | 维持不支持，不把此能力列入 Smoke 成功标准 | 否；相关需求必须拒绝 |
| 开放事实/因果未证明 | UI 无可信 Fact Proof 签发能力，真实集成保持 partial/unavailable | 仅测试可验证定位/总结或有可信证明的宿主事实，不能自批准 | 否；阻止无证据的 completed 宣称 |
| 旧报告恢复冲突 | bh2-024 原可信端点匹配后 restored proof 仍拒绝旧投影 | 保留原记录/只读查看；若未来需要兼容，单独设计，不改旧 Artifact | 否；旧 Run 不纳入新 Smoke 续跑 |
| 保守估算/既有召回局限 | 未调整 Estimator，原问优先未合并，0.55/搜索预算不变 | 将失败如实记录，优化另获授权 | 否；不保证每个复杂任务完成 |
| 远端 CI 未执行 | 本轮禁止 push/dispatch | 获准提交推送后再核对真实 CI | 否；正式发布到 GitHub 前仍须完成 |
| 生产 SaaS 能力未验 | 当前可信本地单用户，非生产认证/多租户/SLO 验收 | 留在原后续路线，不扩大本轮 | 仅阻断生产 SaaS 上线，不阻断本地 Smoke |

可以进入 **另行授权的 New Implementation Freeze → 独立授权 DeepSeek Live Smoke**。本轮已停止于统一回归，不建立新 Campaign，不修改历史 26/31 分数，不继续剩余 29 条，不执行付费调用或 Gate 3。
