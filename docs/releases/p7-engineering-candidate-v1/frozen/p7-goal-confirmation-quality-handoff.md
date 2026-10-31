> 公开脱敏副本。历史原件 `docs/research/p7-goal-confirmation-quality-handoff.md` 保持不变、仅本地保留。
> 原件 SHA256：`da2bfc30e29d4c20655401ec4194464b0f0b8f9a949ace0b8dd7d9db581f85b7`。仅替换本机路径和不可公开工件链接，历史结论/分数不变。

# Phase 2C.7 交接

本轮已结束，正式质量扩展 BLOCKED。先读本报告及机器JSON，不重做已经完成的24条观察。

## 实际状态

- 分支 p7-ci-verification-20261028；HEAD f8b122438d2c67ab26e618ecded72ecc18454015；保留所有旧未提交修改，无commit/push。
- 用户答复没有独立人工审核人，明确按 NOT_VERIFIED；不再就同样资源重复询问。
- 24公开合同：技术形状20/24，有限目标过拒4/15，签名复评24/24一致；不是自然语言语义准确率。
- 40条件性A/B槽位全部not_run，20条正式业务Gold未物化，不能称已完成独立Pilot注册。
- 最终源码浏览器/P3/原Outbox及真实API/UI重启已验证。原空召回失败保留；补充文档引述和SQL1229CNY完成，均排除正式质量收益。
- 撤回返回403 GOAL_REVOKED；原Inspector工件Hash/账本、SQL P3 refs未改。
- Python3.11/3.13各81项非集成定向通过；真实PG3.11八项通过，3.13三项通过；Qwen一项RAM不足失败，未补跑。
- 资源失败被保留为BLOCKED，不能用旧阶段通过或停止服务后的可用RAM代替测试。
- 原产品源码/策略/依赖未改；只新增研究输入、技术评分/薄HTTP驱动、两份测试与本轮三份文档。v1研究评分器保留；v2只修DTO身份定位，属于观察后离线修正。
- 临时8027/8527 API/UI与本轮浏览器页已关闭；所有DB/工件/故障记录保留。

## 文件与真实命令

根目录：<LOCAL_PATH>

主要新文件：`evaluation/goal_confirmation_quality/{cases,gold,sources,protocol}.json`、`invoices.csv`、`{common,host,scoring,scoring_v2}.py`、两份 `tests/test_goal_confirmation_quality*.py`、本轮三个 `docs/research/p7-goal-confirmation-quality-*` 文件。

所有运行、私密环境、源码注册、签名采集、日志、JUnit在 `artifacts/p7/goal-confirmation-quality-v1`。先读 `contract-summary.json`、`restart-integrity.json`、`withdrawal-integrity.json`、`history-adjudication.json`、`final-static-checks.json`、`result-seal.json`。密钥、宿主Session、DB DSN不能输出或提交。

已执行的真实PG selectors：

```text
pg311 / Python3.11:
tests/test_web_goal_confirmation_postgres.py::test_confirmation_ack_loss_concurrent_repeat_uses_one_run_and_one_event
tests/test_web_goal_confirmation_postgres.py::test_fact_requirements_are_not_proofs_even_after_confirmation
tests/test_web_goal_confirmation_postgres.py::test_document_request_missing_corpus_requires_clarification_but_sql_still_completes
tests/test_web_goal_confirmation_postgres.py::test_original_web_outbox_resumes_new_goal_across_processes
tests/test_web_goal_confirmation_postgres.py::test_unknown_outcome_is_not_replaced_by_new_contract_or_retried
tests/test_web_goal_confirmation_postgres.py::test_cross_conversation_confirmation_and_client_scope_forgery_are_rejected
pg-edit311:
tests/test_web_goal_confirmation_postgres.py::test_edit_supersedes_and_retry_cannot_reuse_old_confirmation
tests/test_web_goal_confirmation_postgres.py::test_real_rag_completed_restart_and_confirmation_withdrawal
pg313: 上述fact_requirements、document_request_missing_corpus两个测试
legacy313:
tests/test_trusted_goal_scope_postgres.py::test_cross_process_attestation_or_v3_identity_refusal[bge-True]
qwen311 (FAILED, do not call passed):
tests/test_web_goal_confirmation_qwen_postgres.py::test_qwen_confirmation_original_worker_and_inspector
```

如后续得到单独补验授权，先保证充足可用RAM且没有并行BGE/GUI会话。只用新JUnit标签，不覆盖qwen311，不循环重试；现有wrapper将凭据绑定到新测试库并拒绝覆盖：

```powershell
Set-Location -LiteralPath '<LOCAL_PATH>'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe artifacts/p7/goal-confirmation-quality-v1/pytest_run.py qwen311-next tests/test_web_goal_confirmation_qwen_postgres.py::test_qwen_confirmation_original_worker_and_inspector
```

上条是**未来补验命令，当前未执行**。不要再次运行 `host prepare/collect`、`register.py`、追加控制作者工具或历史STOP Runner。签名只读复评分配新标签可用 `python -m evaluation.goal_confirmation_quality.scoring_v2 audit-next`，但现有两份完全一致，不需要无故重复。

## 剩余工作与保护

1. 若获修复授权，先用新公开Dev验证MRR否定、中文文件名边界/解释任务、否定文档需求、澄清日期默认值；不在本24条结果上刷分，不变P3或权限。
2. 充分资源下单独补Qwen确认链，而非启动新A/B；保留当前资源失败。
3. 当前独立人工语义审查未验证；没有新的正式业务准入，不自动进入40或80观测/Live。
4. 新隔离库包含有意注入的unknown-outcome测试记录，以及撤回测试的原Outbox取消证据。不能重置账本、清记录或自动重发。撤回后的旧Run不应再公开发布，原工件仍保留供只读审计。
5. 保护所有旧Gold/Scorer/Seal、2C.4 STOP与179not_run、2C.2/旧Live成绩、Qwen环境与BGE缓存；不Seed、删库、删卷。

## NEXT CODEX SESSION PROMPT

继续DataPilot Pro P7 Phase2C.7后续工程，先阅读AGENTS.md、docs/research/p7-goal-confirmation-quality-validation.md/json及本handoff，保留全部未提交修改。先只读核验result-seal、JUnit和当前源码，不重复采集24条，不覆盖原失败或补跑旧STOP。当前人工语义审查按用户决定NOT_VERIFIED；40个条件性业务槽位全部not_run，不能自动扩展。Qwen当前PG控制因RAM低于3GiB失败；先说明资源条件，不循环重试、不改门槛。报告里的4类过拒及日期控件风险仅为下一阶段修复建议，未授权不得直接改产品。若本轮新指令授权具体修复或单项补验，严格按新范围执行；不调用付费模型、不切默认BGE、不写历史库、不提交推送、不进Gate3。
