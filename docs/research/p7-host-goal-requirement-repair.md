# P7 Phase 2C.1：Host Goal 全量要求判定修复

2026-10-30，**PASS（本轮有界验收）**。只修复宿主目标判定，没有重跑历史 Pilot、调用付费模型、切换默认 BGE、提交推送或启动 Phase 2C.2。

## 1. 根因与实际链路

历史 qc06 的冻结记录显示：Qwen 找到正确 ownership 来源，Search/Goal 分数通过原下限，但 `rag_completion_goal.unsupported_requirements=true`。旧 `retrieval_goal` 使用 `全部|所有|完整` 的无对象子串判定，把“所有权/所有者”当成全量要求。

原链路未改动：

1. 可信原问题进入 `orchestration/rag_completion.py:retrieval_goal`，不以模型改写搜索词替换原问题。
2. `Coordinator`、`ToolRegistry` 使用该宿主 Goal 绑定工具与完成要求；`validate_submission` 检查授权工件、引用、相关性及最少来源。unsupported Goal 不能产生成功检索收据。
3. `reporting/service.py` 再调用同一 `retrieval_goal`，unsupported 时不把文档升级为业务事实。该守卫是 qc06 失败关闭的第二道检查，不是本轮修复位置。
4. `persistence/session.py` 把完整 Goal 写入 Run Manifest；`inspection.py` 重建并核对，原 `Backend.authorize` 比较 Manifest Hash。

因此修复应放在原目标判定，不能在 Report 强制 completed，也不能以召回正确覆盖原失败记录。

## 2. 先验案例与修复前证据

新公开集合：[host-goal-requirements-v2.json](../../tests/fixtures/rag/host-goal-requirements-v2.json)。包含 30 条输入的分类、unsupported 预期、可信 Scope 行为、完成条件，以及新合成英文/中文原件及 E2E Gold。它是公开回归 Dev，不是新的盲测 Holdout。

- 预登记文件：`artifacts/p7/host-goal-repair-v2/preregistration.json`。
- 预登记 SHA256：`64f1316bd83080b54258cb2e4c7dfd34b98f31b64d064659e38d1cc8cb28deff`。
- 在修改产品前执行：**14 failed / 18 passed**，日志/JUnit 为 `before-py311.log/.xml`。
- 用例和预期结果修改后保持原 SHA；未按检索结果修订 Gold。

| 输入类别 | 新规则 | 后续约束 |
|---|---|---|
| 所有权/所有者、ownership/owns 普通业务名词 | 不错误标为全量 | 仍须真实授权、相关来源、全部必需事实 |
| 所有文档/原始文件/相关来源/整个语料/无遗漏要求 | unsupported | 不能证明语料穷尽性；返回 insufficient/unavailable |
| 两份已 pin 来源中的条件、全部已确认事实 | 不等同于遍历全部文档 | 只覆盖可信宿主实际确认的 Required Facts，缺失仍保留 |
| “所有管理员的所有权配置” | 单独标为歧义/范围未能证明，保守 unsupported | 应澄清或 unavailable，不能暗中缩为一个管理员 |
| 全部账单明细 | 此 RAG 目标不支持穷尽导出 | 不产生 SQL 权限或越过行数限制 |
| 另一个 owner/租户的来源 | 文本不是授权 | 实际 Scope/Corpus/version 在原宿主/MCP 拒绝；解析器不充当认证器 |

精确字面定位、原最少来源要求、时间/最新快照拒绝都保留。“所有权相关的所有文档”仍拒绝；没有把包含“所有权”的整句无条件放行。

## 3. 最小产品修改

唯一产品文件：[rag_completion.py](../../src/datapilot/orchestration/rag_completion.py)。

- 新增小函数 `exhaustive_requirement`：识别量词与文档/文件/来源/证据/语料等集合对象，兼顾明确无遗漏要求；排除普通“所有权/所有者”和有限已确认事实的误判。使用有界确定性语法，没有新 LLM 或解析框架。
- `retrieval_goal` 复用此判定；保留最近/最新/日期、快照、最少来源及字面定位逻辑。
- 新增常量及 Goal 字段 `requirement_policy=host-goal-requirements-v2`：为新的判定语义赋予持久身份，不作为任何授权。

第一版修复在既有安全回归中暴露“所有新顾客学习软件文档”被误放行：两 Python 版本均为 **1 failed / 200 passed**，原日志 `unit-regression-py311/313.*` 保留。随后补强量词与集合对象间的有界修饰语匹配，保留这条原断言；最终两版各 **201 passed**。没有删除旧负例或降低断言。

本轮其余新增文件都是测试/交付：

- `tests/test_host_goal_requirements.py`：30 条预登记分类与 2 条版本/来源要求不变量测试。
- `tests/test_host_goal_postgres.py`：复用原摄取与 Report fixture 的真实 BGE/Qwen 证据、报告、授权和持久恢复测试。
- `tests/host_goal_probe.py`：可信测试子进程入口，仍调用原 Durable/ReportDecisions。legacy 开关只加载固定保留的修复前函数，以构造**新测试记录**验证拒绝，不读取/改写真实历史 Run。
- 本报告与同名 JSON：实际结果、SHA、限制。没有新增 Scheduler、MCP、Verifier 或预算账本。

## 4. Policy、Receipt 与恢复兼容

Embedding ModelSpec、Search/Goal Policy SHA、512/1024 维索引和阈值均不变，无需重写旧 IndexVersion。`requirement_policy` 属于任务完成要求身份；它进入完整 Goal Hash，因而进入原收据的 `goal_sha256` 和原 Run Manifest。

- Receipt 结构仍为 `rag-submit-v1`，检索任务结构仍为 `retrieval-task-v1`；没有伪装成重建了向量策略。
- 新 Run 的恢复重新生成 v2 Goal，原 Manifest、Artifact、Receipt、Journal、预算校验全部有效。
- **旧 RAG Run 缺少 v2 字段，当前代码恢复或 Inspector 发布会返回 `RECOVERY_IDENTITY`。** 不静默重新解释旧 Goal，不补写 Hash，不迁移旧收据，不自动回退旧规则。
- 这意味着旧 RAG Run 不能直接用本版本继续执行/重新发布；需受审查的固定旧部署或另行明确的迁移决策。本轮没有实施迁移。无 RAG Goal 的 SQL-only/P3 路径不受该字段影响。

真实跨进程测试在新库创建 legacy 规则的暂停记录，再用当前代码恢复，确认拒绝且调用、工件、预算逐项不变。新 v2 暂停记录则可恢复 completed；重复恢复报告与 usage 相同、无新增调用/工件/预算。没有修改 P5B 核心来实现这些结果。

## 5. 真实 PG/MCP/报告验证

新库 `datapilot_test_host_goal_repair_v2_20261030` 位于原隔离测试 PG17/pgvector 实例，仅执行原迁移至 0008 与 runtime-init，没有 Seed、删卷、全局角色变更或旧库写入。

新英文来源规定所有权转移须由当前所有者与安全专员审批；不是旧 qc06 的正文。BGE 使用新中文对应原件，Qwen 使用固定 CUDA-FP16 及英文原件。全部结果来自真实索引、受限 MCP、原 Worker/Verifier/Report/Durable；模型只提供同一脚本决策，**不是 DeepSeek 自主效果评测**。

| 验证 | 实际结果 |
|---|---|
| 普通所有权目标、合法 Required Source 与事实 | completed，真实检索收据及引用通过原 Inspector |
| 一项事实缺失 | partial，不强制 completed |
| 事实没有原件依据 | unavailable |
| 真正全量文档目标 | unavailable，不能提交成功完成收据 |
| 可信宿主要求因果证明 | partial，保留 `causal_conclusion_not_verified` |
| 仅相似背景/无关 Required 来源，无所需事实 | unavailable，不以背景补事实 |
| owner 或 IndexVersion 错误 | 原权限/版本检查拒绝 |
| 新规则跨进程恢复、重复恢复 | 结果、引用及预算一致 |
| legacy Goal 在新规则恢复 | `RECOVERY_IDENTITY`，原工件/调用/预算不变 |
| 既有 Qwen 高相似干扰反例 | 缺失 Required 来源不能被相似来源替代 |

首轮新 PG 测试夹具漏写原 helper 必需的 `metric=None`，20 条在 Scope 构造时失败，没有进入 Runtime。`ownership-pg311.log/.xml` 全部保留；只补齐测试接线，未修改 Gold、产品或断言。修正后以新测试记录执行，未清理旧资产。

## 6. 最终测试与实际工件

最终源码 SHA256：`fb3d3374a7410bb26e07a7d89a2787309594c3626f778ff8cd39a54854781457`。

新实现清单：`artifacts/p7/host-goal-repair-v2/implementation-final.json`，SHA256 `6d63aa709a1dcf6543bf5d5ce7316ccacec2b37a114c2f35b90c8246dfa9639c`。包含 339 文件身份及逐项测试 SHA；`implementation.json` 是修正测试接线前的中间快照，不是最终清单。`product-delta.patch` 对照本轮修改前源码。

| 最终执行集 | Python 3.11 | Python 3.13 |
|---|---:|---:|
| 新解析 + Completion/Original Query/Citation/Partial/因果/快照/Qwen 契约 | 201 passed | 201 passed |
| 新 BGE/Qwen 端到端与版本恢复 | 20 passed，420.40s | 6 passed、14 deselected，194.05s |
| 既有 BGE/P3/Original Query/Citation/Partial/版本与 unknown 回归 | 21 passed，295.45s | 21 passed，296.65s |
| 既有 Qwen 高相似度 Required 来源负例 | 1 passed，69.00s | NOT_RUN，不重复声称覆盖 |

共 **402 项非集成定向测试、69 项真实 PG/MCP 测试通过**；不将它们称为 471 条独立业务任务。3.13 新 PG 只选 completed 与跨进程/legacy 身份重点项，其余 14 项是 deselected，不是通过或 skip。没有运行完整 pytest、Linux/Docker 重验、远端 CI、历史 Pilot/Holdout 或付费 Live。

Ruff check、format --check、JSON、Markdown 本地引用及 `git diff --check` 通过。Git 的既有 LF/CRLF 提示不等于 whitespace 失败。

工件位于 `artifacts/p7/host-goal-repair-v2/`：

- `preregistration.json`、`before/`、`before-py311.*`：预登记与原始失败。
- `unit-regression-*`、`ownership-pg311.*`：中间回归失败和夹具错误，不覆盖。
- `unit-final-py311/313.*`、`ownership-pg311-r2.*`、`ownership-pg313.*`、`compatibility-pg311/313.*`、`qwen-negative-pg311.*`：最终 JUnit/日志。
- `tmp-*`：原件、实际绑定、逐 Run 配置/输出/检查和子进程日志，全保留。
- `historical-integrity.json`、`database-audit.json`、`implementation-final.json`、`product-delta.patch`、`result-seal.json`：完整性、版本与账本记录。
- [同名 JSON](p7-host-goal-requirement-repair.json)：机器可读计数及逐文件 SHA。

新库最终 64 Runs/64 Ledgers/100 Artifacts；158 条脚本模型调用 complete，156 条工具调用 complete，**4 条工具 uncertain 是原 unknown-outcome 故障测试的预期保留结果**，没有盲重发或释放为零。它们不是新的供应商异常，不允许清理或冒称数据库全部终态。持久模型配置均为 fake；真实 Provider 请求为 0，脚本 usage 不当作真实 Token/费用。

可复现入口（仓库根目录；数据库环境必须显式绑定新隔离测试库，不能用生产 `.env`）：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_host_goal_requirements.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_host_goal_requirements.py -q
.venv\Scripts\python.exe artifacts/p7/host-goal-repair-v2/pytest_run.py <新结果标签> tests/test_host_goal_postgres.py
.venv\Scripts\ruff.exe check src/datapilot/orchestration/rag_completion.py tests/test_host_goal_requirements.py tests/test_host_goal_postgres.py tests/host_goal_probe.py
.venv\Scripts\ruff.exe format --check src/datapilot/orchestration/rag_completion.py tests/test_host_goal_requirements.py tests/test_host_goal_postgres.py tests/host_goal_probe.py
git diff --check
```

不要重跑初始化、覆盖已有结果标签、删除数据库或把测试 legacy 开关接入产品。私密连接信息不进入公开结果，MCP 仍只继承各自 Reader。

## 7. 历史保护、限制与下一阶段

相对 `qwen-lifecycle-v1-77ceb2a7eaca` 的 335 个文件，只有授权的 `rag_completion.py` 改变，其余 334 一致，修复前原文件完整保留。五套历史结果 seal 共 **662 个文件 Hash 一致**，包括 Phase 2C 全部 239 个封存文件。原 Pilot BGE 14/16、Qwen 15/16 不改写；本轮没有执行旧 qc06，也不把本轮新来源当作旧成绩修正。

未修改 P3、Report、Journal、Ledger、Durable 核心、Embedding/阈值、Scope、旧 Gold/Scorer/Seal；当前分支/HEAD 与开始一致，既有未提交修改保留，没有 commit/push。未写历史数据库；没有冒称对旧数据库做了新的全量逐行审计。

剩余边界：这是中英文的有限、保守目标语法，**不是完整自然语言意图理解**。复杂否定、并列指代、多语言或极长修饰仍可能需要澄清，不能用它承诺任意穷尽性。unsupported=false 只是进入既有证据验证的资格，绝不表示自动授权或自动业务完成。旧 RAG Run 的新版本恢复限制必须在部署前明确告知使用者，不可静默改 Manifest 来解除。

Phase 2C.2 建议另行授权后再做：预登记约 100 条新的公开 Dev，训练/校准与独立验证分离，覆盖所有权/量词/否定/复合要求、双向跨语言、多 Required、缺失事实、相关背景、时间/版本/权限、因果边界。Gold 和阈值先冻结，分别统计解析、召回、收据、事实与报告；保留 BGE 默认及旧 Pilot。对歧义分类单列分母，不为达到分数缩窄目标；如需调规则只在开发子集，新的验证集封存后不再调。此次不生成/执行这 100 条，不执行 Live；付费或生产切换仍须独立授权与新冻结。
