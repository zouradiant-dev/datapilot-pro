# P7 第二步：Required + Claim-grounded Supplement 产品政策

本轮执行范围仅为第二步引用政策的最小产品实现与定向验收。用户在核对三类政策后明确指示“进行第二步修复”，构成该政策的项目负责人批准；真实依据和记录时间见 [负责人决策](research/p7-citation-policy-owner-decision.json)。这不是独立第三方人工审核，不自动确认任何新 Dataset/Metric/业务 Claim，也不追溯改写旧 Gold、Scorer、分母或成绩。

原 [待裁决提案](p7-citation-policy-adjudication.md) 和 [候选 JSON](research/p7-citation-policy-candidate.json) 保留原字节/PENDING 历史状态；本记录和新的负责人决策记录表达当前获批的产品政策。没有重新执行历史 Holdout、付费 Live、第三步查询策略、Gate 3 或 Git 提交推送。

## 三类来源的实际处理

| 分类 | 发布条件 | 对业务完成的作用 |
|---|---|---|
| Required | 来源由宿主声明，精确 Corpus/Index/Source/Document/version/hash 必须在原 MCP Scope 内；facts 任务还须匹配原宿主确认的必需引述 | 只用实际支持必需事实的片段计算覆盖；全部声明的必需来源、minimum_sources、指定文档名和事实要求均需满足 |
| Claim-grounded Supplement | 原权限/版本有效；绑定原始宿主目标；宿主确认具体事实/原文引述；仍通过原相关性筛选、注入过滤及 fact_coverage | 单独展示；不计 minimum_sources，不满足指定的必需文档，不填补必需事实、P3 或因果证明 |
| Irrelevant / unproved extra | 未绑定可核验 Claim、不相关或引述未得证的额外片段 | 不进入发布的证明引用；工件原件继续留在私密 Artifact，不伪造删除历史 |

一次检索可包含多类片段。无需让 RAG Worker 自行声明标签；分类由可信宿主政策和原核验器确定。真实但无关来源会被过滤；人为把它加入已生成报告，verify_report 会拒绝。

补充引述无论有多少，都不能替代 Required。只有补充事实可展示而必需证据缺失时，报告保留 unavailable（存在已验证 P3 等其他必需目标时仍可能 partial），limited_results_visible 表明受限引述可见。insufficient 收据、P3 原 verdict 和因果缺口不会被改成完成。

## 必要代码增量

仅修改三个既有源码文件：

| 文件 | 作用 |
|---|---|
| `src/datapilot/reporting/contracts.py` | 新 CitationSource 仅存六项精确来源身份，防止同名/旧版本或多个 Chunk 混计；新 CitationPolicy 保存版本、目标 SHA、必需来源和最多4个补充 DocumentFact；ReportScope 可选 citation_policy 默认 None；ReportClaim 可选 supplementary_coverage 单独保存已核对引述。 |
| `src/datapilot/reporting/service.py` | validate_citation_policy 以原 MCP 元数据核对分类声明，不授予权限；原 fact_coverage 仅增加显式 facts 参数以复用同一引述算法；报告过滤、完成门控和 Markdown 分开处理必需/补充。 |
| `src/datapilot/orchestration/coordinator.py` | 新政策启用时，在 Planner/Worker 模型调用前检查政策与原 Reader scope，拒绝错误身份或版本。 |

source_identity 是六项身份的一处统一取值函数，用于去重和分类；没有新增数据库表、Registry、模型、工具、调度器、预算账本或恢复引擎。工具、Reader grants、BGE、0.55 阈值、Top-k、两次搜索上限、模型 Prompt 和 P3 六层规则未改。

CitationSource 使用 Source 级身份而不携带伪造权限；具体 Claim 仍复用 DocumentFact 的完整 ChunkCitation/span/hash、quotation 与 confirmation_ref。政策目标 SHA 防止在不同用户目标间直接复用。必需事实不能被重新标记成补充事实；重复来源/Claim、重叠必需和补充 Claim ID、缺失确认的补充定义及未知政策版本由严格 DTO 拒绝。

同一 Source 的补充事实可以独立展示，但不会额外增加来源计数。图表仍只来自原 P3 verified MetricBridge，补充引述不变成图表数值或 P3 Verification。

## 宿主接线与兼容

政策是可信 Python 宿主契约，不是 Web CreateTask、Planner、模型工具、文档正文或 Memory 的参数。已有已确认宿主 scope 可按以下方式创建新 Run：

```python
from datapilot.reporting.contracts import CitationPolicy, ReportScope
from datapilot.orchestration.runtime import text_hash

policy = CitationPolicy(
    goal_sha256=text_hash(trusted_scope.question),
    required_sources=host_pinned_sources,
    supplementary_claims=host_reviewed_document_facts,
)
scope = ReportScope.model_validate_json(
    trusted_scope.model_copy(update={
        "partial_evidence_policy": "partial-facts-v1",
        "citation_policy": policy,
    }).model_dump_json()
)
# 使用原 run_durable(report_scope=scope, ...) 创建新 Run。
```

示例中的来源和事实必须由原可信宿主审查并经 MCP 重新核验；政策批准不等于上述每条业务事实均已被用户审批。

默认 None/空补充字段不序列化，因此旧 Scope/Report/Artifact 的序列化 Hash 保持。显式新政策自动进入原 ReportScope、Manifest 和报告授权 Hash。旧 Run 不能改用新政策恢复，原 Backend 返回 RECOVERY_IDENTITY；按原政策恢复仍可复用终态。官方 Saver 的有限 DTO 自动白名单包含新契约，无 pickle、迁移或新 Checkpoint。

本轮保留第一步 partial-facts-v1 的原有机制；两个政策显式配置、职责不同。本轮未修改 Web task_payload/UI 默认行为，网站仍采用原默认政策，不静默迁移任何历史 Run。

## 新 Dev 验收与可复现性

37个新单元/契约反例使用全新公开合成归档/日期材料，覆盖三类来源、两来源/指定文档门控、原文伪造、版本/Hash/Corpus/Document 越界、未确认定义、去重、假 Metric、因果、快照、注入、伪造发布引用和旧报告冲突。

真实 PG 测试复用已有公开合成 cp09/cp10/cp07 原 Corpus 与已批准夹具，不重新摄取、不 Seed。实际链路为脚本 Fake 决策→原 Gateway/LangGraph/MCP→本地 BGE + PG17/pgvector→原引用/事实校验→原 Report/Journal/Saver。NoModel 新进程恢复禁止新增模型调用。cp07 的真实 P3 Evidence/Verification ID/hash/verdict 与预算在恢复中保持；补寄队列补充引述不能证明送达保证。

真实检索的子集反例仅在可信测试端从实际结果构造受限工件，不声称模型自主选择或检索质量改善。无关果园文档通过第二次真实 MCP 查询取得，报告没有发布它；没有降低阈值。没有读取旧 Holdout Gold 调整实现或回填成绩。

Python3.11 / 3.13 的最终单元/协议回归均 **253 passed**；其中37项为本轮新测试，216项为第一步与原有定向回归。首次新契约未实现时为 **3 failed / 1 passed**；失败日志保留。首轮真实 PG 为8 passed，最终真实 PG/MCP 结果及完整性证明见 [机器验收记录](research/p7-citation-policy-repair.json)。这些数量不等于独立业务任务完成率。

最终真实 PG/MCP/跨进程验收：Python3.11 **11 passed，170.19秒**；Python3.13 **11 passed，172.08秒**。其中8项验证新政策，3项复核第一步的 unknown-outcome、P3终态恢复与旧策略；每版本共264项定向验收，无 skip/xfail。Ruff 通过，262个文件格式通过，git diff --check 返回0。JUnit 为 final-unit-311/313.xml、final-pg-311/313.xml。

最终完整性核对保护1740份既存文件和75044条既存数据库记录：只有三个授权源码出现差异，旧 Gold/Seal/Scorer/历史结果、第一步封存原件均未改写；既存数据库行无修改/删除。新增24个本轮脚本 Fake 测试 Run、5组新 P3 Evidence/Verification及对应 execution/checkpoint 记录；未新增 Dataset/Corpus/Source、迁移或权限。24是包含重复验证/故障探针的 Run 数，不是独立业务评测分母。

新增 `tests/test_citation_policy.py`、`tests/test_citation_policy_postgres.py` 和 `scripts/citation_policy_probe.py`；后者只复用原脚本 Fake 与 run_durable 做跨进程/既有 fault hook 验收，不是第二个执行框架或模型工具。测试中途修正了测试作者对来源 anchor 的构造：只复制原 manifest 的元数据，不创建没有原文支持的临时“确认事实”；最终测试在冻结后的同一实现执行。

命令在仓库根目录执行，PG 测试首先核验精确隔离 Docker 身份与专用连接：

```powershell
$env:PYTHONUTF8='1'
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest tests/test_citation_policy.py tests/test_partial_evidence_report.py tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_cross_source_report.py tests/test_rag_completion.py tests/test_orchestration.py tests/test_orchestration_hardening.py tests/test_persistence_contracts.py tests/test_rag_only_web.py tests/test_snapshot_requirements.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/test_citation_policy_postgres.py tests/test_partial_evidence_postgres.py::test_precommit_submission_unknown_remains_uncertain_without_resend 'tests/test_partial_evidence_postgres.py::test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp07]' tests/test_partial_evidence_postgres.py::test_policy_manifest_conflict_and_legacy_restore -q -p no:cacheprovider
# Python3.13 使用 .venv-313\Scripts\python.exe 执行同样命令。
.venv\Scripts\ruff.exe check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
.venv\Scripts\ruff.exe format --check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
git diff --check
```

本机需保留此前公开 Dev 的私密 bindings；缺失时不得在用户库自动建数据或冒充成功。日志/JUnit/本轮开始前的源码副本及完整性快照均位于忽略目录 `artifacts/p7/citation-policy-repair-v1/`。没有运行完整 pytest、浏览器 Smoke、远端 CI 或真实模型实验。

## 限制与停止点

系统证明的是宿主确认引述与来源一致，无法独立判断任意开放语义 Claim 是否真实、是否与全局目标有关。错误的宿主业务审查仍是残余风险；不得把确认引用当作因果/财务验证。补充事实仍须满足原检索目标相关性规则，低于0.55的片段不会因政策标签获准。summary/locate 仍沿用原任务契约，不声称已验证额外业务事实。

后续正式评测如要采用新政策，须新版本 Protocol/Gold/Scorer/Implementation Freeze 和独立授权；当前未创建这些正式实验版本。旧待裁决快照、失败、v3/v4、Gold/Seal、第一步成果和原 not_run 分母保留。本轮只封存非付费产品验收，不允许沿用旧 Permit。完成第二步后停止，未开始原问优先或任何付费 Smoke。
