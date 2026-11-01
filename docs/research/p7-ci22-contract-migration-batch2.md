# CI #22 Contract Migration — Batch 2

状态：**本地定向验证通过；真实 PG/MCP 为 NOT_RUN，等待本次独立推送批准。不是完整 CI 通过。**

## 基线与边界

- 仓库 `zouradiant-dev/datapilot-pro`，分支 `p7-engineering-candidate-v1`。
- 基线 `25a44c2325889e393d76df960d3ff47452740944`。
- [#22 原失败记录](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41218164036)：每版非集成 1329 passed，集成 60 failed / 265 passed / 63 skipped。该历史结果不改写。
- [#23 四项代表记录](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41276968565)：每版非集成 1331 passed，真实 PG/MCP 4 passed / 0 failed / 0 skipped。该记录只证明原四项，不证明本批通过。
- 本批 11 项：10 项属于 #22 原失败，另加 cp07 既有通过控制，保留 P3 verified、CNY、Evidence/Verification ID 断言。
- 不访问本机或历史数据库、Docker 数据盘，不运行历史实验、不调用付费模型。没有修改产品、依赖、迁移、公开业务夹具、Gold、Scorer、Seal 或 STOP。

## 11 项精确集成范围

下表中的路径均相对仓库根；参数也是 pytest 身份的一部分，不能替换整个模块运行。

| #22 ID | 类别 | 精确 Node ID | 保留的主要断言 |
|---|---|---|---|
| 1 | A1 | `tests/test_chat_review_regressions.py::test_corpus_listing_cap_must_not_revoke_existing_run_authority` | 第 101 个 Corpus 不撤回已授权 Run；精确查找及 hash 损坏拒绝 |
| 21 | A1 | `tests/test_document_confirmation_postgres.py::test_legacy_creation_and_source_injection_do_not_grant_confirmation` | 低信任入口不能确认；真实 HTTP proposal 拒绝未知 Corpus；非法字段 422；无 Run |
| 60 | A1 | `tests/test_web_postgres.py::test_real_document_upload_retrieval_report_and_source_ref` | 真实上传/Embedding、completed、来源 SHA、Trace 不泄露正文/SQL、Mock 标记 |
| 2 | A2 | `tests/test_citation_policy_postgres.py::test_real_policy_report_terminal_reuse_preserves_citations_p3_and_budget[cp09]` | Required/Supplement、completed、报告/usage/持久快照重复恢复不变 |
| 3 | A2 | `tests/test_citation_policy_postgres.py::test_real_policy_report_terminal_reuse_preserves_citations_p3_and_budget[cp07]` | 补充引用不能填补必需事实；partial，P3 仍 verified |
| 4 | A2 | `tests/test_citation_policy_postgres.py::test_new_policy_survives_cross_process_cut_without_model_reissue[rag_submission_committed]` | 提交后崩溃恢复、无新增模型调用/预算使用、原 Artifact 不变 |
| 5 | A2 | `tests/test_citation_policy_postgres.py::test_new_policy_survives_cross_process_cut_without_model_reissue[report_artifact_committed]` | 报告工件提交后崩溃恢复与账本/调用不变 |
| 6 | A2 | `tests/test_citation_policy_postgres.py::test_new_policy_survives_cross_process_cut_without_model_reissue[checkpoint]` | pause/resume 保留补充引用与工件、不重复模型调用 |
| 48 | A2 | `tests/test_partial_evidence_postgres.py::test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp04]` | 缺 Required 来源/事实保持 insufficient/partial，合法局部事实和快照不丢失 |
| 49 | A2 | `tests/test_partial_evidence_postgres.py::test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp06]` | 缺离线规则保持 partial，不升级 documents verified，重复恢复不变 |
| 原通过控制 | P3 | `tests/test_partial_evidence_postgres.py::test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp07]` | 缺送达证明保持 partial；真实指标 verified、单位 CNY、原 Evidence/Verification 引用 |

## 最小迁移方式

1. 两个 Web 正向用例改为原 Conversation/Message → 精确版本/SHA 与三项合成用户决策 → HTTP launch 事件。明确断言 `can_confirm` 且无未解决前提。上传报告用例再经独立 Journal 执行审批，替换旧 `require_review=False`。Corpus 列表用例仅创建待审批 Run，继续验证其原授权断言。
2. 共享公开问题 `BILLING_GOAL` 对齐原来不一致的 SQL 主目标与文档子问题：指定 2025 年 10 月已支付收入和 billing.md 口径总结。Dataset、Semantic、Metric 版本与时间窗口必须逐字段保持；Chat 生成的任务别名不冒充旧别名。脚本首次搜索使用完整原问题，遵守既有 Original-query-first，未改检索参数。
3. 文档 legacy 入口的精确拒绝码迁移为当前 `GOAL_CONFIRMATION_REQUIRED`。**原 `WEB_SCOPE` 拒绝断言仍保留**，改在当前可信 HTTP proposal 上实际提交未知 Corpus 触发；没有仅将所有预期改为 unavailable。
4. 三个 A2 测试函数在最终 Required/Supplement、Partial Evidence 和业务字段固定之后，调用已有 `confirm_finite_scope`。只确认预先审阅的有限问题和授权范围，不确认缺失事实、不产生成功收据、不修改 Worker 结果。共享 `config_for`、`configured` 与 `reporting_fixtures.host_scope` 均不自动确认其他用例。
5. 新增一个纯单元测试，验证上述 Web 合成问题保留完整目标、Registry 版本、时间右开窗口、独立审批、指标关联，并且候选不包含 Attestation/确认事件。

仅新增一个测试问题常量和一个契约测试；复用原 HTTP helper、Host 确认、PG outbox、Journal、Ledger、探针和恢复机制，没有新增框架或产品字段。

## 已执行的本地验证

| 验证 | Python 3.11 | Python 3.13 |
|---|---|---|
| 9 个相关模块的非集成定向回归 | **137 passed / 0 failed / 0 skipped**，8 deselected，6.20 秒 | **137 passed / 0 failed / 0 skipped**，8 deselected，6.70 秒 |
| 精确集成身份收集（未执行） | **11 collected**，无收集错误 | **11 collected**，无收集错误 |
| 本批真实 PG/MCP | **NOT_RUN** | **NOT_RUN** |

8 deselected 是上述模块中的 integration 用例，被非集成 marker 排除；不是 8 项通过或跳过。没有运行本地完整 pytest、完整集成或新的浏览器/真实模型 Smoke。

本地命令与逐版日志/JUnit保存在忽略目录 `artifacts/p7/ci22-batch2-v1/`：

```powershell
.venv\Scripts\python.exe artifacts/p7/ci22-batch2-v1/run_local.py --python .venv\Scripts\python.exe --label py311
.venv\Scripts\python.exe artifacts/p7/ci22-batch2-v1/run_local.py --python .venv-313\Scripts\python.exe --label py313
# 收集使用同一入口加 --collect；仅收集，不连接数据库。
```

`py311-unit.xml`、`py313-unit.xml`、各自 `.log`/`.json` 为实际结果。第一次收集辅助脚本把工作目录定位到了父目录，返回 file not found、没有收集或执行测试；修正辅助脚本路径后两版均正常收集。该准备错误保留在 `py311-collection-launcher-failure.*`，不将它描述为业务/安全失败，也没有覆盖该失败记录。

Ruff、format、工作流 YAML/精确 11 项匹配及 `git diff --check` 的实际结果见相邻机器记录。AST 对比确认六个修改的原测试函数均保留原业务/安全/预算/Citation断言；唯一替换是上述 legacy 提前拒绝码，原来源授权拒绝经真实入口保留。

## 完整性与未完成项

- `src/`、`evaluation/`、`migrations/`、`tests/fixtures/`、`pyproject.toml`、`uv.lock`、`AGENTS.md` 相对基线无差异。未改其他原测试函数和共享 fixture。
- #22 两份归因文件、#23 `verified-results.json`/`RESULT-SEAL.json` 的字节 SHA 与开工快照一致。源码以 Git blob 为准，另保存 Windows 工作区字节 SHA，避免混淆 CRLF/LF。
- 本批没有读写历史数据库，没有重新核验整个历史文件树；完整性结论限于 Git 修改范围和实际检查的历史记录，不冒称重新验证全部历史 Run。
- 原 60 个失败中：4 项已经 #23 双版真实 PG 验证；本批涉及 10 项，**仍待真实 PG 验证**；另外 46 项在本批之外（A1 3、A2 37、A3 2、A4 2、A5 2）。不能把 46 叫作本轮重新执行后的失败数。
- 本地单元验证不证明 pgvector 召回、真实 Required 覆盖、持久恢复或 HTTP 确认落库全部通过。这些以本批 Actions JUnit 为准；新失败仍可能暴露第二层契约或真实产品问题。

## 独立提交与推送计划

本轮本地 `fix(test)` 提交只包含六个测试文件、本工作流及本批两个交付记录；不包含已有未跟踪的 Docker恢复、#22归因、#23结果等本地记录。实际 Commit SHA 交付时报告，并记录在本地 `commit-verification.json`，避免自引用提交 SHA。

**尚未推送；没有触发新的 Actions。** 本次不沿用 #23 的一次推送授权。

批准后计划仅向 `p7-engineering-candidate-v1` 推送该独立提交：

1. 核对远端仍为预期基线、Diff 和本批 SHA，不 force push、不合并 main。
2. 复用原 Actions 双版本矩阵、PG17/pgvector 镜像、角色/迁移/初始化/固定 BGE 流程。保留原完整非集成步骤；PG 步骤精确限定上表 11 项，所有 marker、JUnit、coverage、pipefail 和 always 上传保留。
3. 工作流/Job/scope 标记 `CI22 Batch 2 / NOT FULL CI`、`planned_pg_tests=11`，不宣称完整 CI。下载两份 JUnit/日志后逐项核对身份、数量与原断言。
4. 如发现安全回归，停止并报告；不热修产品、不自动重试失败测试或扩大批次。

本批真实验收通过后，下一批建议优先处理剩余 Web purpose 参数、Host Required/Supplement 篡改负例及 Partial Evidence 的 unknown/节点恢复。A4 余下两个预算 cut-point 和 A5 `run_question` 低信任入口单独定界，不借迁移修改产品 API。待各批完成后另行批准恢复完整集成工作流；本轮不启动下一批或完整 CI。
