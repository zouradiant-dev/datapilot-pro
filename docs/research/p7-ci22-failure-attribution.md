# GitHub Actions #22：有界失败归因

核验时间：2026-11-01T12:39:23+08:00（Asia/Shanghai）。本轮仅诊断，CI 仍为 **failure**，没有修复或重新验收60个集成用例。

## 远端事实与原始证据

[DataPilot checks #22](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41218164036)，attempt 1，分支 `p7-engineering-candidate-v1`，提交 `607e68c988121e0e686ee36f740e601a5f8e0e86`。UTC 2026-10-31 16:07:51–16:46:20，对应北京时间2026-11-01 00:07:51–00:46:20。不是此前 #21 的收集错误：本次1717个测试已收集，业务集成确实执行后失败。

| Python | 非集成 | 集成 | 集成 pytest 耗时 | Job |
|---|---|---|---|---|
| 3.11 | 1329 passed / 0 failed / 0 skipped | 265 passed / 60 failed / 63 skipped | 2208.92秒 | [124586952027](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41218164036/job/124586952027) |
| 3.13 | 1329 passed / 0 failed / 0 skipped | 265 passed / 60 failed / 63 skipped | 1577.98秒 | [124586952279](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41218164036/job/124586952279) |

两版60个失败 node ID完全相同，是60项独立测试在两个环境的重复观测，不是120种缺陷。63个skip为62个需显式Qwen/CUDA opt-in和1个需另行授权的Live；本轮未增加skip。初始化、锁定依赖、Ruff、格式均成功；无证据将失败归因于Python版本、PG未启动或缺少Embedding。两版 `test_trusted_goal_scope_postgres` 与 `test_web_goal_confirmation_postgres` 合计各27 passed、0 failed、13 skipped，为已经走新版确认的真实PG/MCP/HTTP控制，不能替代未到达下游断言的旧测试。

完整ZIP、两份job日志及解出的unit/integration JUnit均保存在忽略目录 `artifacts/p7/ci22-failure-diagnosis-v1/`。机器记录见[分类JSON](p7-ci22-failure-attribution.json)，包含60项身份、断言、根因、修复方向和文件SHA；原始大日志/源码快照不发布。

| Artifact | ID | ZIP SHA256 |
|---|---|---|
| Python3.11 | 13050301091 | eeb8dd67921767bfe4a16809978ac678b7112065d9fa5904fc8772029c86d91a |
| Python3.13 | 13049368848 | ae8d49cde3cce20310558b8ee0a130b290317e0d22dc4f777cd7dcbe08b50c11 |

ZIP按GitHub digest校验后解包，两个 `commit.txt` 均匹配上述HEAD；未覆盖#21日志或任何旧Seal。#22的 `/tmp/pytest-*` 子进程探针结果未包含在上传工件中，故不能从JUnit补造其内部Ledger或收据。下一轮可在原上传目录追加有界、脱敏的诊断摘要，不能上传完整Prompt、业务行或凭据。

## 聚合结论与置信度

**首个阻断归因：A类59项、B类1项；C类直接失败未证实；D类安全回归未证实，但发现1项公开接口能力缺口（D1），须单列裁决。** 第58项兼有A与D1，不额外计入60分母。A类归因不能保证补前置条件后全部转绿；尤其3个篡改用例、3个预算/恢复用例仍须真实PG定向补验。

| 根因 | 项数 | 实际机制 | 最小改造方向 |
|---|---:|---|---|
| A1 Web缺正式Goal确认 | 7 | 403 GOAL_CONFIRMATION_REQUIRED / RECOVERY_IDENTITY；旧负例拒绝码发生前置变化 | 复用现有HTTP确认事件与独立执行审批 |
| A2 旧Host/RAG合同缺完整有限范围确认 | 44 | completion_eligible=false；insufficient，Report unavailable/partial或无context claim | 对已审阅有限合成合同走原Host确认，未知范围不确认 |
| A3 篡改断言被前置范围守卫遮蔽 | 3 | Report丢弃无资格目标，未调用Citation校验，pytest.raises不成立 | 先有合法确认与有效原件控制，再保留逐字段篡改raises |
| A4 预算脚本额外进入完成纠正 | 3 | 固定4轮脚本的complete被拒，达到WORKER_LIMIT；不是已有证据显示总Token超支 | 修正范围前提，不扩大预算；真实PG仍待验证 |
| A5 旧纯语义入口无确认通道/输入 | 2 | complete被拒；固定脚本可能MODEL_OUTPUT_INVALID，未达到预设crash点 | 保留安全拒绝；用已有可信Host路径做正向测试；第58项另裁决D1 |
| B1 local-only旧源码快照 | 1 | --legacy加载未跟踪的artifacts路径，FileNotFoundError | 公开合成的历史identity数据夹具 |

### A：合法确认的具体要求

Web第1、17–20、60项必须从授权Conversation/Message的 `goal_contract` 开始，用当前 `expected_version`、`expected_contract_sha256`、`reviewed_contract`、`covers_original_goal`、`prerequisites_resolved` 和真实会话actor经原HTTP launch提交；由服务生成event ID并与Outbox同事务绑定。随后独立 `approve` 才能执行。第1项不能继续 `store.command(create)` 写一个缺事件的RAG Run；应在真实确认创建的新Run上测试101 Corpus列表边界，保留原测试的授权和Hash损坏断言。

第21项是拒绝顺序变化：`/tasks` 的任何文档请求当前在解析后直接 GOAL_CONFIRMATION_REQUIRED，后续旧 `WEB_SCOPE` 断言也会被遮蔽。保留legacy入口拒绝与空Run列表；将未授权Corpus的精确拒绝验证放在正式Conversation合同提案入口，而不是只把第一个错误码改到绿。

库级Report/Worker测试可调用原可信宿主 `confirm_finite_scope`，但只能用于预先明确定义、公开合成且确实审阅的有限合同；单独记录这一模拟Host决定，不冒充真实人工签字。必须在Required/Supplement策略、事实要求、Dataset版本、指标和RagScope全部固定之后确认；不能在通用fixture里看到非空文档就无条件确认，也不能直接构造/注入Attestation DTO。业务因果、缺事实、未知全集、越权仍应partial/unavailable/拒绝。所有原P3、引用、预算和恢复断言继续执行。

### B：可公开重建，但不伪造历史

仅第33项证实依赖未发布输入：`tests/host_goal_probe.py --legacy` 固定导入 `artifacts/p7/host-goal-repair-v2/before/rag_completion.py`。本机存在不代表GitHub应拥有。用公开合成问题及可审计旧策略输出构建一个最小的legacy goal identity JSON，注明旧源码SHA/投影版本；用新测试Run验证原Manifest不兼容拒绝。现有 `host-goal-v2-identity.json`、`host-goal-v3-identity.json` 提供实现模式，但不能偷换该更早身份。不要上传原私密工件、补历史数据库或改旧Run Hash。

### C / D：不能抹去的剩余问题

- **D1：第58项的公开facade能力缺口。** [run_question](../../src/datapilot/graph.py) 的签名没有可信ReportScope/rag_task_scope参数，内部创建Coordinator也没有传该身份；普通语义请求无法在此入口提供v4完成依据。本轮实际调用带该参数立即TypeError，未执行DB/模型。Coordinator已有合法 `rag_task_scope` 支持，因此不是整个RAG功能丧失。需要裁决此legacy facade是否只保留低信任查询；若是，保留其拒绝并在现有Host/Coordinator路径保留原语义正向测试；若要求facade支持合法语义完成，须独立授权一个显式Host合同透传的最小产品改动。不能仅把成功断言降为unavailable、改成literal查询，或自动确认所有文本。当前无越权/false completed证据。
- **3个篡改测试必须重新抵达真实引用验证。** 本轮替身显示无确认时未发布坏引用，确认后会拒绝；这只反驳“未抛异常就等于已发布假引用”，不证明所有PG字段、Owner/Index变化均安全。原raises保留；真实PG补验是后续门槛。
- **3个预算/恢复用例仍有下游不确定性。** #22只保留blocked；替身解释了守卫新增纠正所致WORKER_LIMIT，但还须实际检查持久Journal/账本/Artifact与跨进程恢复，不能直接宣告是纯旧测试问题。
- **本轮本机PG复验NOT_RUN。** 只读探测Docker Desktop Linux daemon管道不存在。没有启动Docker、复用用户库、创建/Seed数据库或运行全量PG。该限制属于本轮验证环境，不是#22失败的原因。
- 当前无C类PG连接/权限初始化失败、无已证实D类安全事故，不等于证明其不存在。前置断言后未执行部分的覆盖仍有缺口，不能由265 passed或上述27个控制代替。

## 代表性验证（本轮实际执行）

没有修改产品或正式测试。两版各仅4项现有定向测试：

```
python -m pytest -q -p no:cacheprovider \
  tests/test_web_goal_confirmation.py::test_confirmation_dtos_never_accept_host_attestation_or_actor \
  tests/test_web_goal_confirmation.py::test_ui_pending_reload_requires_three_explicit_decisions_and_preserves_original \
  tests/test_goal_scope_integrity.py::test_old_successful_report_cannot_supply_missing_host_confirmation \
  tests/test_rag_completion.py::test_semantic_retrieval_can_complete_without_literal_keyword
```

Python3.11 **4 passed / 4.55秒**；Python3.13 **4 passed / 4.63秒**。它们是DTO/Mock HTTP UI/脚本Worker单元合同验证，不是真实浏览器或PG重放。分别有JUnit与完整日志 `representative-contracts-311/313.*`。

`representative_probes.py` 每版另做相同的小型内存对照：

- 原Report：无Host确认的坏Citation返回unavailable、Citation校验调用0、公开引用0；用原Host接口构造的已确认合同会触发EVIDENCE_INVALID。
- 原BudgetDecisions与原Coordinator/Worker Loop：同一公开合成输入、18000 Token上限、4 Worker轮次、压缩设置不变，未确认WORKER_LIMIT/blocked，确认后succeeded/completed；均5次Fake调用、8700 Token、usage_complete=true。不是Provider账单，也不是PG Ledger验收。
- 旧快照路径 `git ls-files --error-unmatch` 非零；facade参数TypeError在任何I/O之前复现。

诊断替身首次缺citation_ref、第二次document_id非真实MCP的chunk身份，导致探针自身失败；r1/r2日志与结果保留，不能列为产品缺陷或通过记录。修正替身契约后的r3两版通过。没有因此修改正式测试、产品、Embedding或0.55阈值。

## 下一轮最小修复与验证顺序（本轮未实施）

1. 先确认D1入口预期，避免把功能丢失藏在测试迁移中。保持Goal/P3/Report/Durable核心原值。
2. 更新A1正式HTTP构造；库级有限Host fixture增加独立、明确的合成审批前置条件，仅用于有限正例。保留未知/越权/因果/缺证据负例；确认后再测恢复、篡改、Required/Supplement、Partial Evidence、Original Query。
3. B1改用公开合成legacy identity夹具，停止依赖私密路径；保留不兼容RECOVERY_IDENTITY断言。
4. 先每根因1–2代表用例在新隔离PG跑通，包括第28或53项篡改、第55项预算；保留错误日志。才申请最终完整双版本PG矩阵，不立即整套重跑。
5. 若出现确认后仍错误发布、越权、P3错误或账本冲突，作为新的D类缺陷另行报告，不热修核心、不删测试、不改历史Gold。

后续代表命令示例（须由已有可信环境配置注入新隔离PG；不复制本机凭据）：

```
python -m pytest -q -p no:cacheprovider \
  'tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[summary-completed]'
python -m pytest -q -p no:cacheprovider \
  tests/test_document_fact_postgres.py::test_real_pins_and_scope_cannot_be_forged
python -m pytest -q -p no:cacheprovider \
  'tests/test_phase4_postgres.py::test_real_rag_budget_pressure_uses_only_original_limit_and_preserves_facts[True]'
python -m pytest -q -p no:cacheprovider \
  'tests/test_host_goal_postgres.py::test_legacy_requirement_manifest_is_not_silently_reinterpreted[bge]'
```

## 预计修改文件与保护范围

预计仅为下表13个失败测试模块、共享 `tests/reporting_fixtures.py`、`tests/host_goal_probe.py`、必要的 `scripts/rag_recovery_probe.py` 与一个公开合成legacy identity JSON。优先复用 [现有HTTP确认测试](../../tests/test_web_goal_confirmation_postgres.py) 的candidate/decision/confirm模式和原Registry/Host接口；不新建确认框架。D1若需产品兼容透传，只可能另批最小 `src/datapilot/graph.py` 适配，本轮没有实施。

本轮实际只新增本报告、[机器分类](p7-ci22-failure-attribution.json)与忽略目录下下载/诊断记录。没有修改 `src/`、`tests/`、workflow、依赖/迁移、Gold/Scorer/Seal/STOP，没有写数据库、发起付费调用、重跑CI、commit或push。此报告不是P7质量Gate通过或候选发布准入。

## 60项逐项分类

编号同时对应JSON完整nodeid/断言。每行两版都失败；下面报告的是首个阻断，不删除后续测试职责。

| # | 测试身份 | 类别/根因 | #22实际首个失败 | 预期受影响文件 |
|---:|---|---|---|---|
| 1 | `test_corpus_listing_cap_must_not_revoke_existing_run_authority` | A · A1 | RECOVERY_IDENTITY（RAG Run缺事件） | [test_chat_review_regressions.py](../../tests/test_chat_review_regressions.py) |
| 2 | `test_real_policy_report_terminal_reuse_preserves_citations_p3_and_budget[cp09]` | A · A2 | unavailable != completed | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 3 | `test_real_policy_report_terminal_reuse_preserves_citations_p3_and_budget[cp07]` | A · A2 | partial成立，但找不到context claim | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 4 | `test_new_policy_survives_cross_process_cut_without_model_reissue[rag_submission_committed]` | A · A2 | unavailable != completed | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 5 | `test_new_policy_survives_cross_process_cut_without_model_reissue[report_artifact_committed]` | A · A2 | unavailable != completed | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 6 | `test_new_policy_survives_cross_process_cut_without_model_reissue[checkpoint]` | A · A2 | unavailable != completed | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 7 | `test_real_supplement_only_and_forged_quotes_cannot_fill_required_sources` | A · A2 | supplementary_coverage为空 | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 8 | `test_real_unrelated_source_is_not_published_even_after_separate_search` | A · A2 | unavailable != completed | [test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) |
| 9 | `test_five_independent_business_cases_real_sources_and_p3_gold[paid_invoice_revenue-分析已支付账单收入并解释账单口径-已付款账单收入和经常性订阅金额有什么区别？-300]` | A · A2 | partial；documents=EVIDENCE_INSUFFICIENT | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 10 | `test_five_independent_business_cases_real_sources_and_p3_gold[customer_churn-计算期初客户队列净流失率并提供口径来源-客户流失与订阅取消的期初队列口径-0.4]` | A · A2 | partial；documents=EVIDENCE_INSUFFICIENT | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 11 | `test_five_independent_business_cases_real_sources_and_p3_gold[subscription_churn-计算订阅合同流失率并附业务定义-订阅合同流失与降级如何区分？-0.666666666667]` | A · A2 | partial；documents=EVIDENCE_INSUFFICIENT | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 12 | `test_five_independent_business_cases_real_sources_and_p3_gold[usage-汇总产品使用量并说明事件数量限制-产品使用事件数量和活跃用户数有什么区别？-35]` | A · A2 | partial；documents=EVIDENCE_INSUFFICIENT | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 13 | `test_five_independent_business_cases_real_sources_and_p3_gold[active_subscriptions-核对时点活跃合同并引用订阅历史要求-活跃订阅合同的时点口径与历史数据要求是什么？-4]` | A · A2 | partial；documents=EVIDENCE_INSUFFICIENT | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 14 | `test_rag_and_metric_references_survive_cross_node_checkpoint` | A · A2 | partial != completed | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 15 | `test_real_persisted_metric_and_document_tampering_is_rejected` | A · A3 | 坏引用未抛AgentFailure | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 16 | `test_prompt_injection_source_and_denied_tool_do_not_approve_report` | A · A2 | RAG unavailable != succeeded | [test_cross_source_postgres.py](../../tests/test_cross_source_postgres.py) |
| 17 | `test_confirmed_document_purpose_survives_chat_review_and_durable[locate-completed]` | A · A1 | 403 GOAL_CONFIRMATION_REQUIRED | [test_document_confirmation_postgres.py](../../tests/test_document_confirmation_postgres.py) |
| 18 | `test_confirmed_document_purpose_survives_chat_review_and_durable[summary-completed]` | A · A1 | 403 GOAL_CONFIRMATION_REQUIRED | [test_document_confirmation_postgres.py](../../tests/test_document_confirmation_postgres.py) |
| 19 | `test_confirmed_document_purpose_survives_chat_review_and_durable[facts-unavailable]` | A · A1 | 403 GOAL_CONFIRMATION_REQUIRED | [test_document_confirmation_postgres.py](../../tests/test_document_confirmation_postgres.py) |
| 20 | `test_confirmed_document_purpose_survives_chat_review_and_durable[conclusion-partial]` | A · A1 | 403 GOAL_CONFIRMATION_REQUIRED | [test_document_confirmation_postgres.py](../../tests/test_document_confirmation_postgres.py) |
| 21 | `test_legacy_creation_and_source_injection_do_not_grant_confirmation` | A · A1 | GOAL_CONFIRMATION_REQUIRED != 旧拒绝码 | [test_document_confirmation_postgres.py](../../tests/test_document_confirmation_postgres.py) |
| 22 | `test_real_worker_receipt_report_and_persistent_fact_coverage[missing]` | A · A2 | receipt insufficient != complete | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 23 | `test_real_worker_receipt_report_and_persistent_fact_coverage[year]` | A · A2 | receipt insufficient != complete | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 24 | `test_real_worker_receipt_report_and_persistent_fact_coverage[absence]` | A · A2 | receipt insufficient != complete | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 25 | `test_real_worker_receipt_report_and_persistent_fact_coverage[partial]` | A · A2 | receipt insufficient != complete | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 26 | `test_real_worker_receipt_report_and_persistent_fact_coverage[summary]` | A · A2 | receipt insufficient != complete | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 27 | `test_real_worker_receipt_report_and_persistent_fact_coverage[causal]` | A · A2 | receipt insufficient != complete | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 28 | `test_real_pins_and_scope_cannot_be_forged` | A · A3 | 坏引用未抛AgentFailure | [test_document_fact_postgres.py](../../tests/test_document_fact_postgres.py) |
| 29 | `test_new_public_ownership_report_chain[bge-complete]` | A · A2 | unavailable != completed | [test_host_goal_postgres.py](../../tests/test_host_goal_postgres.py) |
| 30 | `test_new_public_ownership_report_chain[bge-partial]` | A · A2 | unavailable != partial | [test_host_goal_postgres.py](../../tests/test_host_goal_postgres.py) |
| 31 | `test_new_public_ownership_report_chain[bge-causal]` | A · A2 | unavailable != partial | [test_host_goal_postgres.py](../../tests/test_host_goal_postgres.py) |
| 32 | `test_new_goal_cross_process_restore_preserves_receipt_and_budget[bge]` | A · A2 | unavailable != completed | [test_host_goal_postgres.py](../../tests/test_host_goal_postgres.py) |
| 33 | `test_legacy_requirement_manifest_is_not_silently_reinterpreted[bge]` | B · B1 | --legacy FileNotFoundError，exit1 | [test_host_goal_postgres.py](../../tests/test_host_goal_postgres.py) |
| 34 | `test_goal_and_business_eligibility_remain_separate[bge-complete-completed]` | A · A2 | unavailable != completed | [test_host_goal_safety_postgres.py](../../tests/test_host_goal_safety_postgres.py) |
| 35 | `test_goal_and_business_eligibility_remain_separate[bge-negative-completed]` | A · A2 | unavailable != completed | [test_host_goal_safety_postgres.py](../../tests/test_host_goal_safety_postgres.py) |
| 36 | `test_goal_and_business_eligibility_remain_separate[bge-partial-partial]` | A · A2 | unavailable != partial | [test_host_goal_safety_postgres.py](../../tests/test_host_goal_safety_postgres.py) |
| 37 | `test_goal_and_business_eligibility_remain_separate[bge-required_gap-partial]` | A · A2 | unavailable != partial | [test_host_goal_safety_postgres.py](../../tests/test_host_goal_safety_postgres.py) |
| 38 | `test_goal_and_business_eligibility_remain_separate[bge-causal-partial]` | A · A2 | unavailable != partial | [test_host_goal_safety_postgres.py](../../tests/test_host_goal_safety_postgres.py) |
| 39 | `test_cross_process_v3_reuse_or_v2_identity_rejection[bge-False]` | A · A2 | unavailable != completed | [test_host_goal_safety_postgres.py](../../tests/test_host_goal_safety_postgres.py) |
| 40 | `test_real_original_query_report_and_terminal_reuse[cp09]` | A · A2 | unavailable != completed | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 41 | `test_real_original_query_report_and_terminal_reuse[cp06]` | A · A2 | unavailable != partial | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 42 | `test_real_original_query_report_and_terminal_reuse[cp12]` | A · A2 | unavailable != partial | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 43 | `test_call_and_feedback_cut_points_do_not_reissue_search_or_settle_twice[worker_model_committed]` | A · A2 | unavailable != completed | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 44 | `test_call_and_feedback_cut_points_do_not_reissue_search_or_settle_twice[tool_committed]` | A · A2 | unavailable != completed | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 45 | `test_call_and_feedback_cut_points_do_not_reissue_search_or_settle_twice[rag_submission_committed]` | A · A2 | unavailable != completed | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 46 | `test_call_and_feedback_cut_points_do_not_reissue_search_or_settle_twice[report_artifact_committed]` | A · A2 | unavailable != completed | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 47 | `test_model_selected_second_search_and_its_committed_feedback_are_reused` | A · A2 | unavailable != completed | [test_original_query_postgres.py](../../tests/test_original_query_postgres.py) |
| 48 | `test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp04]` | A · A2 | unavailable != partial | [test_partial_evidence_postgres.py](../../tests/test_partial_evidence_postgres.py) |
| 49 | `test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp06]` | A · A2 | unavailable != partial | [test_partial_evidence_postgres.py](../../tests/test_partial_evidence_postgres.py) |
| 50 | `test_committed_submission_or_report_crash_reuses_without_new_model[rag_submission_committed]` | A · A2 | unavailable != partial | [test_partial_evidence_postgres.py](../../tests/test_partial_evidence_postgres.py) |
| 51 | `test_committed_submission_or_report_crash_reuses_without_new_model[report_artifact_committed]` | A · A2 | unavailable != partial | [test_partial_evidence_postgres.py](../../tests/test_partial_evidence_postgres.py) |
| 52 | `test_partial_refs_restore_across_node_checkpoint` | A · A2 | unavailable != partial | [test_partial_evidence_postgres.py](../../tests/test_partial_evidence_postgres.py) |
| 53 | `test_real_fact_validation_after_rehydration_rejects_wrong_hash` | A · A3 | 坏引用未抛AgentFailure | [test_partial_evidence_postgres.py](../../tests/test_partial_evidence_postgres.py) |
| 54 | `test_explicit_false_report_survives_real_sources_and_readonly_inspection` | A · A2 | partial != completed | [test_phase12_postgres.py](../../tests/test_phase12_postgres.py) |
| 55 | `test_real_rag_budget_pressure_uses_only_original_limit_and_preserves_facts[True]` | A · A4 | blocked != completed | [test_phase4_postgres.py](../../tests/test_phase4_postgres.py) |
| 56 | `test_compacted_durable_restore_keeps_known_results_or_blocks_unknown[None]` | A · A4 | blocked != completed | [test_phase4_postgres.py](../../tests/test_phase4_postgres.py) |
| 57 | `test_compacted_durable_restore_keeps_known_results_or_blocks_unknown[tool_committed]` | A · A4 | blocked != completed | [test_phase4_postgres.py](../../tests/test_phase4_postgres.py) |
| 58 | `test_real_semantic_retrieval_checks_original_goal_not_model_search_keywords[True]` | A/D1 · A5 | insufficient != semantic_retrieval | [test_rag_completion_postgres.py](../../tests/test_rag_completion_postgres.py) |
| 59 | `test_committed_rag_control_restores_across_process_without_duplicate_calls[semantic-rag_submission_committed-3]` | A · A5 | MODEL_OUTPUT_INVALID；exit0 != crash91 | [test_rag_completion_postgres.py](../../tests/test_rag_completion_postgres.py) |
| 60 | `test_real_document_upload_retrieval_report_and_source_ref` | A · A1 | 403 GOAL_CONFIRMATION_REQUIRED | [test_web_postgres.py](../../tests/test_web_postgres.py) |

C/D归因界限：A/D1一行不是已证实的越权或错误完成；真实PG迁移后仍失败的项目必须重新分类，不能靠本表提前免验。
