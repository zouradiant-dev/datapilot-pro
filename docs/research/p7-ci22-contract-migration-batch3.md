# CI #22 Contract Migration — Batch 3

2026-11-01。**本地契约迁移 PASS；真实 PG/MCP NOT_RUN；推送等待独立批准；不是完整 CI 验收。**

## 身份与已读基线

- 仓库 `zouradiant-dev/datapilot-pro`，分支 `p7-engineering-candidate-v1`。
- 开工 HEAD、origin 跟踪分支及当轮 GitHub API 返回的远端 SHA 均为 `be880d1415f6d5069c914a09417732f5d501805e`。
- 开工无已跟踪修改，六份既有未跟踪 Docker/CI 报告全部保留并排除提交。
- 已读 AGENTS、原 #22 归因、首次代表迁移、Batch 2 迁移、#23/#24 本地真实结果、ADR-018/019、Engineering Freeze 与 Demo Acceptance；这些文件均实际存在，部分仅在本地未跟踪。
- [#22](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41218164036) 原 60 failed / 265 passed / 63 skipped 保持历史值。[#23](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41276968565) 双版各 4 项真实 PG 通过；[#24](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41278805564) 双版各 11 项通过，其中 10 项原失败、1 项原通过控制。

因此开工时原失败中 **14 项已有双版定向 PG 证据，46 项尚未覆盖**。本批从这 46 项中选择附件指定的 15 项，不将它们视作已经真实通过。

## 15 项精确 Node ID 与迁移

| #22 ID | 精确 Node ID | 本次前置条件/控制 |
|---|---|---|
| 17 | `tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[locate-completed]` | 复用 #23 HTTP 确认；补原问题、可确认状态及审阅用途断言 |
| 19 | `tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[facts-unavailable]` | 同上；事实需求不充当事实证明，原 unavailable 不变 |
| 20 | `tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[conclusion-partial]` | 同上；原 partial 和独立 Journal 审批不变 |
| 7 | `tests/test_citation_policy_postgres.py::test_real_supplement_only_and_forged_quotes_cannot_fill_required_sources` | 最终引用政策确认；先验证完整原件；Supplement 单独仍不补 Required；改 quotation 后重新确认范围，再检查事实而非被旧确认 Hash 遮蔽 |
| 8 | `tests/test_citation_policy_postgres.py::test_real_unrelated_source_is_not_published_even_after_separate_search` | 最终 Required 来源政策固定后确认；无关果园来源仍不可发布 |
| 15 | `tests/test_cross_source_postgres.py::test_real_persisted_metric_and_document_tampering_is_rejected` | 最终完整合同确认；新增正确 P3/文档 completed 控制、无确认 partial 控制及错误 Owner；保留所有原 raises，增加 document_id 篡改 |
| 22 | `tests/test_document_fact_postgres.py::test_real_worker_receipt_report_and_persistent_fact_coverage[missing]` | 仅为有限年限问题确认范围；缺 retention 事实仍 unavailable |
| 23 | `tests/test_document_fact_postgres.py::test_real_worker_receipt_report_and_persistent_fact_coverage[year]` | 仅确认同一有限问题；真实原件年限证明仍须通过原 Fact Coverage |
| 40 | `tests/test_original_query_postgres.py::test_real_original_query_report_and_terminal_reuse[cp09]` | Original Query/引用政策全部固定后确认；原 completed、搜索指纹、引用 goal Hash 与恢复相等断言保留 |
| 41 | `tests/test_original_query_postgres.py::test_real_original_query_report_and_terminal_reuse[cp06]` | 同上；缺离线规则仍 partial |
| 50 | `tests/test_partial_evidence_postgres.py::test_committed_submission_or_report_crash_reuses_without_new_model[rag_submission_committed]` | 确认有限合同；保留提交后崩溃复用；新增不同合法确认身份恢复拒绝且快照不变 |
| 51 | `tests/test_partial_evidence_postgres.py::test_committed_submission_or_report_crash_reuses_without_new_model[report_artifact_committed]` | 同上；不重复模型调用、预算或既有 Artifact |
| 53 | `tests/test_partial_evidence_postgres.py::test_real_fact_validation_after_rehydration_rejects_wrong_hash` | 确认后先建立有效原件 partial/identity 事实控制，再执行原错误 Hash raises |
| 55 | `tests/test_phase4_postgres.py::test_real_rag_budget_pressure_uses_only_original_limit_and_preserves_facts[True]` | 仅对 enabled=True 的公开有限合同确认；18000 Token、4 轮、L3、8700 Mock Token 与 5 次调用断言不变 |
| 57 | `tests/test_phase4_postgres.py::test_compacted_durable_restore_keeps_known_results_or_blocks_unknown[tool_committed]` | 原代表迁移已经为此函数绑定有限合同；本轮复用该实现，不重复开发 |

共享函数的 `missing/year`、`cp09/cp06` 和 `enabled=True` 采用明确的测试参数分支；其他尚未迁移参数没有自动获得确认。Web 原 summary 参数也会执行新增的三条加强断言，但其确认流程与终态没有改变；这属于参数化函数共享的验证加强，不新增本批 PG 身份。

## 修改文件与信任边界

仅修改上述七个测试文件、候选分支已有的临时 `.github/workflows/test.yml`，并新增本报告和相邻机器记录。

不新增 Host 确认 Helper、服务、数据库字段、Agent、Approval API 或通用测试框架。复用原 `confirm_finite_scope`、`decision(message)`、HTTP launch、`reporting_fixtures.host_scope`、ReportScope/RagScope、原探针及 Inspector/Journal/Ledger。共享 fixture、配置工厂、脚本探针均未修改，原 `run_question` 低信任入口不变。

Web 仍由服务器生成 pending 合同，经当前版本/SHA 和三个显式合成用户决定提交，再单独执行 Journal approve。没有直接注入 Attestation；库级确认属于公开合成测试的可信 Host 决定，不是独立人工审查签字。

引用负例需要区分「旧合同 Hash 已失效」与「引文事实错误」。#7 变更负例 quotation 后使用原 Host 接口确认新的有限候选合同，保留原 RagScope/Owner/授权索引；确认并不证明引文为真。原事实/引用验证必须继续剔除伪造文字；错误 IndexVersion 仍由来源 pin 验证拒绝，不能因重确认扩权。

#15 和 #53 均在破坏证据前新增合法原件控制。#15 保留单位 USD、Metric 版本、伪造 Evidence、来源 Hash、文档版本/IndexVersion/goal Hash 等原负例，并增加 document_id 与 Owner 拒绝；无完整目标确认时真实 P3 也只能保留 partial。#53 原 raises 未改成 unavailable。

#50/51 仅用原确认函数生成另一个明确的确认引用，尝试恢复同一个已暂停 Run，要求 RECOVERY_IDENTITY 且原快照不变，随后仍按原确认恢复。没有修改或迁移任何历史 Run。旧 v3 identity 拒绝和 unknown 的既有本地合同回归另行执行；本批真实 PG 的 model_response unknown 参数未纳入，不能声称已新增验证该切点。

清理了 #53 中两条已被模块级导入覆盖的局部重复 import；没有删除有效测试、改变 SQL 配方或扩大预算、工具/重试次数。

## 原断言保护

AST 审计逐项保存原表达式；下表按函数合并参数，数量是静态 assert/pytest.raises 个数，不是运行覆盖率：

| 函数/参数 | assert 前→后 | raises 前→后 |
|---|---:|---:|
| Web locate/facts/conclusion | 17→20 | 0→0 |
| Supplement/伪造引文 | 5→7 | 1→1 |
| 无关来源 | 4→4 | 0→0 |
| P3/来源篡改 | 3→7 | 4→5 |
| Document Fact missing/year | 9→9 | 0→0 |
| Original Query cp09/cp06 | 8→8 | 0→0 |
| Partial 提交/报告切点 | 5→7 | 0→0 |
| Partial 错误 Hash | 1→3 | 1→1 |
| Budget enabled=True | 10→10 | 0→0 |
| Durable tool_committed | 11→11 | 0→0 |

所有原 assert 与 pytest.raises 的 AST 均保留，**删除/修改原断言 0**；终态、金额单位、搜索指纹、Source/Fact Coverage、18000 Token、L3、调用次数、预算和恢复断言未弱化。其他测试函数/类/Helper 的 AST 与基线相同。是否真实抵达 PG 下游断言仍须下一次定向 CI，静态保护不冒充该验收。

## 本轮实际验证

| 验证 | Python 3.11 | Python 3.13 |
|---|---|---|
| 10 个相关非集成模块 | **182 passed / 0 failed / 0 skipped**，7.79 秒 | **182 passed / 0 failed / 0 skipped**，8.39 秒 |
| 精确 PG 仅收集 | **15 collected**，身份/顺序逐项匹配 | **15 collected**，身份/顺序逐项匹配 |
| 本批真实 PG/MCP | **NOT_RUN** | **NOT_RUN** |

复用现有测试覆盖 Host 确认绑定、HTTP DTO/UI 三个决定、旧/缺失确认拒绝、Required/Supplement、事实引用篡改、Original Query、Partial Evidence、父子预算、已提交响应复用和 unknown 保守计账。没有新增重复单元框架；单元中的 HTTP/来源/调用替身明确是 Mock/Fake，不是新的真实 PG、浏览器或模型验收。

测试日志、JUnit、命令和运行时源码字节 SHA 在忽略目录 `artifacts/p7/ci22-batch3-v1/`：`py311-unit.*`、`py313-unit.*`、`py311-collection.*`、`py313-collection.*`。可复用的本地命令：

```powershell
.venv\Scripts\python.exe artifacts/p7/ci22-batch3-v1/run_local.py --python .venv\Scripts\python.exe --label py311
.venv\Scripts\python.exe artifacts/p7/ci22-batch3-v1/run_local.py --python .venv-313\Scripts\python.exe --label py313
# 精确仅收集在同一入口加 --collect；如需重新执行须换新工件目录，保留已有结果。
```

本轮按授权第一阶段只执行非 PG 测试与收集，没有启用 DB fixture 或使用项目 .env 连接业务库，没有探测/恢复 Docker 或创建测试数据库。真实 PG 与远端 CI 等待独立推送批准，不将未运行项算通过或通过 skip 隐藏。

Ruff、format、JSON/YAML、工作流精确名单、失败 exit code/pipefail 与 `git diff --check` 均通过。没有运行完整 pytest、完整集成或付费 API；没有发生本地测试失败。

## 定向 Workflow 与推送计划

更新现有候选分支的临时 `test.yml`，没有新建第二套数据库初始化配置；该文件在 be880d1 本来就标记 Batch 2 / NOT FULL CI。本轮只换 Batch 3 名称/Job/scope 与 15 项选择，原完整 CI 的历史定义和验收标准不变，也没有宣布恢复完整矩阵。

- 名称 `DataPilot CI22 Batch 3 - NOT FULL CI`，scope `ci22-batch3`、`full_ci=false`、`planned_pg_tests=15`。
- Python 3.11/3.13、PG17/pgvector digest、全部角色/权限/迁移、固定 BGE 初始化、锁定依赖、完整非集成步骤与 #24 完全相同。
- PG 命令精确匹配上表 15 项；marker、JUnit、coverage、pipefail、always 上传不变。
- 保留 commit.txt、完整源码 SHA、收集 Node ID、逐版 Artifact；不会启动 Live、Qwen CUDA、历史 STOP 实验。
- 当前仓库只有这一个 YAML workflow，push/pull_request 触发保持；推送预计只启动该定向 workflow。外部 GitHub App/webhook 不属于仓库 YAML 的可证明范围，不能对此虚构保证。

本轮创建一个独立本地 `fix(test)` Commit，具体完整 SHA 在最终答复及本地 `commit-verification.json`。本报告进入该提交，避免在文件里自引用其 Commit Hash；源基线 SHA、逐文件 Hash 和提交后核验记录共同定位最终代码。

**等待用户明确回复“确认Batch 3推送”**。批准后先重核远端/本地 SHA 和提交白名单，仅普通推送该提交，不 force/rebase/main/PR；运行后下载两版 JUnit、日志和源码身份，失败仅归因，不热修或连续重跑。本轮没有推送或触发 Actions。

回滚应在另获授权后用普通 `git revert` 撤销本地 Batch 3 提交，不改历史提交、不 reset/delete 未跟踪记录。它恢复的是候选分支原 Batch 2 临时选择，不等于自动恢复完整 CI。

## 完整性、未完成项与条件性后续

`src/`、`evaluation/`、迁移、公开数据/Gold、scripts、共享 fixture、依赖/锁、AGENTS 无差异。12 份开工历史报告/结果/Seal 字节 SHA 保持；没有修改历史 Gold/Scorer/Seal/STOP、数据库或历史 Run。没有重算所有历史私密文件/数据库，不能将 Git 修改范围证明扩张为全部历史数据审计。

Phase 2C.2/2C.4 BLOCKED、Phase 2C.7 独立人工 NOT_VERIFIED、Engineering Candidate ACCEPTED 及真实质量/Live PENDING 均不变。

当前仍只有原 14 项获得过新 PG 证据；本批 15 项待真实验证，另 31 项在本批之外。**只有这 15 项全部真实通过后**，才可将剩余未覆盖项表述为 31（A2 29、A5 2），再另行授权 Required/Document Fact/Original Query/Host Goal 等后续迁移。A5 继续保留低信任入口，不能靠修改产品 API 达到成功；本轮不开展其余任务。

风险：本地合同通过不能排除新增正确原件控制暴露召回问题、真实预算边界或恢复不一致。出现需修改产品核心、false completed、越权、错引用发布或 unknown 重发时必须停止，保留失败，不提高预算、不修改预期。

最终状态：

- **Batch 3 Local Migration：PASS**。
- **Real PG/MCP：NOT_RUN**。
- **Safety Regression：NOT_VERIFIED**（本地单元/静态未发现回归，真实 PG 下游仍未验收）。
- **Git Commit：CREATED**（提交后完整 SHA 见独立核验记录与交付答复）。
- **GitHub Push：AWAITING_APPROVAL**。
- **Full CI：NOT_VERIFIED**。

完成本地提交和校验即停止，不进入下一批。
