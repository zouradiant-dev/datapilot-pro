# P7 Scorer v4：控制事件契约修复与离线验收

**SCORER V4 PASSED**。本轮仅新增版本化离线诊断评测器与独立测试；`src/`、冻结 v3 Scorer/Collector、Gold/Protocol、原记录均未改变。付费请求、Runtime/审批/恢复调用均为 0。

## 1. 原确定性停止根因

原 Journal 的 `rag_correction` 在原子事务中创建 `kind=tool`、`call_key=control:<plan>:<task>:rag-correction`、`tool_name=rag_completion_correction`，指纹为 notice 的 digest。它属于宿主 Stop Hook，并非 assistant 工具请求。原 v3 `call_integrity` 只豁免 P3/report 两类宿主调用，将合法 correction 判为孤儿响应。

030 原生的 5 个 tool_call 都有同名、同 ID、已提交反馈。两次实际搜索后第三次请求返回 `RAG_ATTEMPTS_EXHAUSTED`；这个正确拒绝和其后的宿主纠正不能算越权事故。原错误停止、模型响应与 v3 20/29 原分不改。

## 2. 新契约与修改范围

| 新文件 | 必要性 |
|---|---|
| evaluation/p7_v4/v4_protocol.py | 严格 Notice/Call/Event/Transcript/Witness DTO 与本次协议证据校验 |
| evaluation/p7_v4/v4_score.py | 调用原 v3 业务评分，只替换 protocol 维度；检查新独立 Freeze 与见证文件/签名 key 绑定 |
| evaluation/p7_v4/test_v4_contracts.py | 独立公开合成协议红绿/对抗反例，防止修协议即提升业务成功 |
| evaluation/p7_v4/test_v4_retrieval.py | 显式真实 PG/MCP + 本地 BGE Dev 检查，不执行 Agent |

没有第二套 Scheduler、恢复引擎、BudgetLedger、Registry 或数据库迁移。DTO 仅描述离线证明，不是权限或持久运行状态。Collector 签名算法复用原实现；原 Collector 内容不变。v4 直接调用原 v3 业务评分，保留数值、引用、事实、完成状态及阈值；不复制整套评分器。

只有满足以下全部条件才识别宿主控制事件：

- 原签名采集通过，另有只读 PG/Saver 见证；见证文件与签名 key 的 SHA 由新 Evaluator 封存绑定，不能由模型自述 trusted/host。
- Run/owner/Case/Manifest、plan/task/worker、完整调用集与有序事件集对应原采集。kind、key、tool_name、notice DTO、attempt=1、payload SHA、Journal fingerprint 一致。
- RAG task 的原生检查点含唯一宿主 HumanMessage；notice.trigger 等于它之前完整、已闭合消息前缀的 digest；assistant 与 tool 内容和顺序对应原 Journal。
- 原工具拒绝与 correction reason、event_id/sequence/前后位置对应；纯 final 无提交的 COMPLETION_REQUIRED 使用独立的 assistant 触发分支。每 task 最多一个 correction。
- 原生 tool_call_id 唯一、一一对应，参数指纹和 Worker 能力一致；实际搜索最多两次，已发出但明确失败的搜索也保守计入额度，受限拒绝不能伪装成功，普通结果不能改名 control 绕过。P3/report 宿主调用还校验精确键、角色、请求/依赖指纹。
- 来源缺失、未知类型、错序、错误线程/Hash、重复或孤儿均拒绝。synthetic-dev 见证仅供显式单测，不能证明 Live。

信任边界仍是本地可信宿主、PG 与私密审计 key；不是防御管理员或签名 key 泄露的系统。摘要/Memory/文档正文不能产生见证，也不能授权工具。没有完整旧持久证明的历史格式继续 fail-closed，不扩大兼容豁免。

## 3. 真实红绿与定向回归

| 执行 | Python 3.11 | Python 3.13 |
|---|---:|---:|
| 原 v3 合法 correction / 两次搜索后拒绝第三次的独立红例 | 2 failed | 2 failed |
| 最终 v4 合约 + 原 scorer versions/RAG completion 定向回归 | 109 passed | 109 passed |
| 新三文档 Dev、本地 BGE、真实 PG/MCP、非法 index 拒绝 | 3 passed | 3 passed |

无 skip/xfail，没有删有效断言。收尾另保留了“第三次已执行但失败的搜索未计数”的单独红例（1 failed），补强后两版本均通过。覆盖合法 native/control、第三次受拒、伪造/改名 control、孤儿、run/task/worker/线程/hash/指纹、缺失/重复/错序、配对 ID、超限、严格 DTO/额外字段/类型、源缺失、合成见证不能用于 Live、P3/report、v3/v4 Seal、见证文件和签名 key 绑定、协议修复不得提升未验证业务成功。

最初 Docker 引擎与隔离容器未运行，按原标签启动，仅用于读历史。只读采集脚本的 libpq 参数编码失败、一次扩展测试 NameError、旧 Dev pin 不在当前实例造成的 3 errors 均保留原日志；没有绕过权限。旧 pin 的失败保持，另外经原受限服务追加独立三文档 Dev Corpus后重新验证；不是调整 Holdout 或删除失败。

未重复完整产品 pytest/CI。本轮没有产品源码变化；最终源码定向回归及 Ruff/Diff 结果见 integrity/交付封存。

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest evaluation/p7_v4/test_v4_contracts.py tests/test_p7_scorer_versions.py tests/test_rag_completion.py -q -p no:cacheprovider
.venv-313\Scripts\python.exe -m pytest evaluation/p7_v4/test_v4_contracts.py tests/test_p7_scorer_versions.py tests/test_rag_completion.py -q -p no:cacheprovider
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest evaluation/p7_v4/test_v4_retrieval.py -q -p no:cacheprovider
.venv-313\Scripts\python.exe -m pytest evaluation/p7_v4/test_v4_retrieval.py -q -p no:cacheprovider
```

## 4. 29 条只读复评与版本差异

v3 是原正式冻结评分器；v4 仅为新离线诊断。总 strict 始终 **20/29**，not_run 始终 **31**。下表 v3→v4；T/F 是 True/False，业务状态及失败类别完全未改。

| Case | strict | protocol | citations | retrieval | BusinessCompletion | failure_class |
|---|---|---|---|---|---|---|
| p7-holdout-v3-001 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-021 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-041 | F→F | T→T | F→F | T→T | completed→completed | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-002 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-022 | F→F | T→T | F→F | T→T | completed→completed | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-042 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-003 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-023 | F→F | T→T | F→F | T→T | completed→completed | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-043 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-004 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-024 | F→F | T→T | F→F | T→T | completed→completed | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-044 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-005 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-025 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-045 | F→F | T→T | F→F | T→T | completed→completed | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-006 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-026 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-046 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-007 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-027 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-047 | F→F | T→T | F→F | T→T | completed→completed | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-008 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-028 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-048 | T→T | T→T | T→T | T→T | completed→completed | NA→NA |
| p7-holdout-v3-009 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-029 | F→F | T→T | F→F | F→F | unavailable→unavailable | rag_retrieval_failure→rag_retrieval_failure |
| p7-holdout-v3-049 | F→F | T→T | F→F | T→T | partial→partial | business_or_evidence_mismatch→business_or_evidence_mismatch |
| p7-holdout-v3-010 | T→T | T→T | NA→NA | NA→NA | completed→completed | NA→NA |
| p7-holdout-v3-030 | F→F | F→T | F→F | F→F | unavailable→unavailable | rag_retrieval_failure→rag_retrieval_failure |

030 唯一变化是 protocol F→T。它仍只有一份相关来源、收据 insufficient、事实覆盖不足、业务 unavailable，与 Gold partial 不符，所以 strict 仍 False。不能用协议兼容修复追溯宣布正确。另一独立进程对全部 29 条重算结果逐项相同，没有模型调用。

本 v4 沿用原检索质量统计函数，其中被拒绝的 search_documents 也可能列作空返回 query。协议核验单独确认实际搜索 2 次、拒绝请求 1 次；本轮不顺便改检索指标分母或阈值，未来新协议应明确 attempt/executed-query。

## 5. 冻结与历史证明

当前独立 Evaluator：`p7-scorer-v4-d4bf6aa23fe0`；Freeze SHA256：`08869ca7f1f605eb97c3165b7928d915c71c77804a772f97ce064cc6510f3220`；`mode=offline_diagnostic_only`、`live_allowed=false`。

[Freeze](research/p7-scorer-v4-freeze.json)、[29 条评分与逐项差异](research/p7-scorer-v4-offline-results.json)、[完整性记录](research/p7-scorer-v4-integrity-summary.json)。早期 v4 草稿在正式离线评分前补强见证 key/file 封存绑定后被替代；草稿 SHA、补强前源码与记录保留；收尾又收紧已知失败搜索的计数，重跑双版本定向回归并再封存，29条离线分数与业务维度均无变化。这些不是新的 Live 评测。

933 个既存文件未改；原 v3 Result Seal 的 375 个文件逐一匹配。当前隔离 PG 的 69574 条既存记录无改写/删除；仅 rag.corpora/indexes/sources/chunks 追加新 Dev 的 8 行。P3/Journal/Checkpoint/Artifact/Ledger 均不变，81 次/116,059 Token/估算 USD 0.02674572 不变。

读取时 29 个 Run 已过 TTL；没有修改时钟、TTL、Manifest 或旧 Permit。原签名 inspect_run/NoModel 收据保留并验证；当前 PG SELECT 与官方 Saver SELECT 证明 Journal/消息前缀仍一致。**没有宣称过期 Run 能重新通过 fresh inspect_run，也没有调用 Runtime 恢复它们。**

旧 60 条第一次 Holdout 的 31/29、25/31 与离线 26/31、61 calls/77,897 Token；旧 Smoke 8/8、20 calls/27,167 Token 均保留。新 v3 Live 仍为 BENCHMARK INVALID — FREEZE / EVALUATION INTEGRITY，绝不追溯改为通过。

## 6. 结论和后续边界

新的协议判断更可信：不再混淆宿主控制日志与 native tool 响应，而且新增来源、身份、指纹、消息前缀和限额核验；业务评分未被放松。它不解决 Gold 来源集合争议，也不证明 RAG 业务质量达标。

可以开始另行授权的新独立评测准备：先裁决补充来源政策，明确 executed-query 分母，安排见证在 TTL 前采集；如要改 RAG/Report 的部分证据保留，需独立产品修复与新 Dev 验证，再冻结候选和新的 Gold。当前不具备直接沿用本许可启动新 Live 的条件。31 条旧 not_run 不续跑，不进入 Gate 3，不 commit/push。
