# P7 Partial Evidence：第一步产品修复

本轮只修复可信部分证据从 RAG TaskResult 到报告、持久工件和跨进程恢复的传递。引用分类政策仍为 PENDING_OWNER_ADJUDICATION；原问优先、fallback、Live、历史复评分和 Gate 3 均未开展。

## 原因与实现

原 TaskResult/Artifact 已保存片段。Coordinator.envelope 排除了 unavailable RAG 依赖；ReportService.build 又以 source_ready、最少来源数量作为事实核验之前的门控，导致 insufficient 收据中的有效事实不能进入报告。

仅修改三个既有源码文件：

| 文件 | 本轮必要增量 |
|---|---|
| `src/datapilot/reporting/contracts.py` | ReportScope 增加可信宿主字段 partial_evidence_policy，枚举 legacy / partial-facts-v1，默认 legacy。默认值不序列化，保留旧 Scope、Artifact 与 Manifest 哈希。新值进入原 Scope/Manifest/report 授权哈希，无新表。 |
| `src/datapilot/orchestration/coordinator.py` | 对新策略下 unavailable + insufficient 的 RAG 依赖，调用原 verify 重新核对身份、权限、Source、提交集合及宿主接收收据，再允许报告读取原 refs。失败、取消、缺收据、伪造 verdict 不传递部分 refs。 |
| `src/datapilot/reporting/service.py` | 复用原 validate_result、相关性筛选和 fact_coverage。来源不足或 insufficient 时仅展示有宿主原文证明的事实，保留缺失事实和来源门控；insufficient 永远不能使文档目标 completed。原指标关联与 P3 verify_metric 保持。 |

新增字段用于选择新报告解释规则与防止旧 Run 被静默重解释；不提供给模型或 Web CreateTask。新策略由可信 Python 宿主显式配置：

```python
scope = ReportScope.model_validate_json(
    trusted_scope.model_copy(
        update={"partial_evidence_policy": "partial-facts-v1"}
    ).model_dump_json()
)
# 将这个 scope 传给原 run_durable(report_scope=scope, ...)；不要从模型文本选择策略。
```

trusted_scope 必须由原可信宿主重建全部身份/权限/已确认定义。本轮未修改网站默认策略和 UI；旧 Run、现有 Web 创建路径及未显式启用策略的调用仍使用 legacy。后续如启用 Web，须在可信 task_payload 和历史授权重建处同时绑定原策略；不能只改默认值。

没有增加新的证据、事实、预算或恢复状态机。Report 的 missing_evidence 使用原有可扩展代码列表，增加 rag_task_insufficient 表达来源任务未完成；来源数量不足继续保留 matching_document_or_metric_evidence_missing。没有将 Worker outcome/verdict 改成 complete，也没有把文档引述标成 P3 verified。

## 完成与展示边界

| 条件 | 新策略结果 |
|---|---|
| complete 收据、必需来源和全部事实均满足 | 原 completed 行为 |
| insufficient 但有真实、授权、目标匹配且宿主确认的原文事实 | partial，发布有证明的引述；未覆盖目标仍不进入 verified_goals |
| 来源数不足但有已证明事实 | partial，来源缺口继续显示 |
| 仅有相关背景，没有所需事实证明 | unavailable；不能靠非空/Hash/分数生成事实 |
| 因果要求或未确认结论 | 原因果/结论缺口保留 |
| 最新/全局快照无法证明 | 原 snapshot_not_attested 拒绝，不通过部分事实旁路 |
| 来源、版本、Artifact、收据或权限校验失败 | 原拒绝契约；不得发布可信事实 |

部分展示的 documents 只含 fact_coverage 已证明的引述，不把整段不相关正文作为完成证据。关联指标仍须通过原 P3 验证和主题检查。局限：当前事实证明是宿主审核的精确引用，不增加开放语义事实判断能力；summary/locate 的 insufficient 不因此自动得到 partial。

## 持久恢复与历史兼容

新策略仍使用原 execution Artifact、Journal、官方 Saver、Run 锁和 Ledger。报告父引用直接记录原 RAG 工件；新策略进入 Manifest，跨策略恢复由原 authorize 拒绝为 RECOVERY_IDENTITY。旧默认字段省略后恢复仍按 legacy 重建，不迁移旧报告。

验收使用既有公开合成 Dev 的 cp04/cp06/cp07 原来源、固定 BGE、本地 PG17/pgvector 和 MCP，创建全新测试 Run；不重新摄取 Corpus、不重跑旧 Run。脚本 Fake 决策明确选择 insufficient；无 DeepSeek 或其他付费模型请求。

新增 `scripts/partial_evidence_probe.py` 仅用于独立进程验收，复用原 ReportDecisions 与 run_durable；支持既有 fault hook 的硬退出和 NoModel 恢复，未注册为模型工具。新增测试 `tests/test_partial_evidence_report.py`、`tests/test_partial_evidence_postgres.py` 覆盖事实保留、来源缺口、原文伪造、因果、快照、旧策略、收据、跨节点/进程、提交前 unknown、提交后复用、审批前取消、权限/版本变化及新建测试 Run 的 Artifact 损坏。

预算比较允许原调度器在恢复后为确定性 Report 新建零消耗子账户；既有父子账户、pending、receipts 必须完全相同，且不能新增模型调用。终态再次恢复必须整个工件/调用/账本完全相同。测试破坏只针对本轮新建的一个隔离 Run，故障记录保留。

## 验证记录

最终结果与实现哈希见 [机器验收记录](research/p7-partial-evidence-repair.json)。原失败、修正过程和 JUnit 均保存在忽略目录 `artifacts/p7/partial-evidence-repair-v1/`，不覆盖旧实验结果。

修复前第一批公开合成反例为 **7 failed / 9 passed**：包括部分事实丢失、来源不足与策略冲突。修复后的定向单元/协议回归在 Python 3.11 和 3.13 各 **216 passed**，包含扩展后的20个新契约用例；不是216个独立经营分析任务。

最终真实 PG/MCP/跨进程验收在 Python 3.11 为 **12 passed，192.90 秒**，Python 3.13 为 **12 passed，195.15 秒**。每版本合计228项定向测试通过，无 skip/xfail。Ruff 全部通过，259个文件格式检查通过，git diff --check 返回0。JUnit 为 final-unit-311/313.xml、final-pg-311/313.xml，对应日志同名 .log。

历史完整性复核保护1557份既存文件与69803条既存数据库记录。既有文件只有上述三个授权源码发生差异，旧 Gold/Seal/Scorer/实验输出均未变；所有既存数据库行哈希保留。新增42个本轮隔离测试 Run（含探索失败、unknown 和损坏反例，不删除），5组新 P3 Evidence/Verification，及对应原 execution/checkpoint 记录；没有追加 Dataset/Corpus/Source 或 Schema。42不代表独立业务样本数。旧 Run 的 Journal/Evidence/Verification 未被改写。

工程测试曾发现三个测试端问题并保留日志：JSON 字典校验日期应使用严格 DTO 的 model_validate_json；cp07 本来没有可证明的文档事实，不能要求它产生 context；新建零消耗 Report 子账户不等于重复扣费。另外，原 Manifest 冲突代码是 RECOVERY_IDENTITY，测试遵守原契约。没有为这些问题修改 P3、Ledger 或恢复引擎。

执行命令（仓库根目录，现有隔离实例与公开 Dev bindings 存在）：

```powershell
$env:PYTHONUTF8='1'
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest tests/test_partial_evidence_report.py tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_cross_source_report.py tests/test_rag_completion.py tests/test_orchestration.py tests/test_orchestration_hardening.py tests/test_persistence_contracts.py tests/test_rag_only_web.py tests/test_snapshot_requirements.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/test_partial_evidence_postgres.py -q -p no:cacheprovider
# Python 3.13 使用 .venv-313\Scripts\python.exe 执行同样的命令。
.venv\Scripts\ruff.exe check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
.venv\Scripts\ruff.exe format --check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
git diff --check
```

PG 测试的模块夹具先验证精确隔离 Docker 身份，再加载专用连接，绕过此夹具直接运行其他 PG 测试可能使用不同环境。初次克隆若没有私密公开 Dev bindings，应显式准备新的独立 Dev，不能伪造通过或在用户库自动 Seed。

未执行完整 pytest、浏览器 Smoke、CI 或真实模型实验；网站默认策略保持 legacy。本轮测试不等于真实模型业务正确率已经改善。旧 v3/v4 评分、Gold/Seal、历史失败和 not_run 分母保持，不把新 Dev 成绩回填历史 Benchmark。生产源码在工作副本中出现三个有意差异，旧冻结原件不改；新的实现快照仅用于此次非付费修复验收，不能沿用旧付费 Permit。
