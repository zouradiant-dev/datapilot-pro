# P7 三项策略 Smoke：Scorer 空收据最小修复

2026-10-29。按负责人本轮“修复 Scorer”的授权完成新版本离线修复及复评。没有调用 DeepSeek、连接数据库、启动 MCP、执行 Embedding 或续跑 Campaign；原 [Live 停止记录](p7-three-policy-live-smoke.md) 与全部原件不改写。

## 根因与唯一逻辑修改

原 `rag_result` 已按当前 Plan/版本定位 TaskResult，验证身份、编排 Verification 和 Artifact；失败、取消、阻塞任务合法地可以没有 `rag_completion`。成功或 unavailable 任务仍必须有真实、匹配的提交收据。

新 Smoke 的 [Scorer](../scripts/p7_policy_smoke.py) 原第 237 行在返回展示字段时却只判断 `rag` 是否存在，就读取 `rag["rag_completion"]["verdict"]`。因此 tps-07 的合法 failed/null 结果产生 TypeError，中断后续评分。

本轮唯一既有代码改动为该表达式增加 **`rag["rag_completion"] is not None`** 判断：合法无收据返回 JSON null；原业务状态、Worker 状态、错误、证据和严格成功条件都不变。没有宽泛异常吞噬，没有生成假收据，没有将失败改成 unavailable/完成，也没有默认补出 verified。原 `rag_result`、P3、六层 Verifier、报告、Gold、来源、预算、Prompt、0.55 阈值及权限均不修改。

代码变化范围：

- 修改 `scripts/p7_policy_smoke.py`：1 行表达式改为 3 行，净增 2 行，无新增函数、字段或模块抽象。
- 新增 [test_policy_smoke_receipts.py](../tests/test_policy_smoke_receipts.py)：复用已有公开合成签名/任务 fixture，共 16 条测试，不读取真实 Smoke 私密数据或 Holdout。
- 新增本文与 [结构化修复记录](research/p7-three-policy-scorer-repair.json)。审计脚本、旧/新源码副本、JUnit、差异与封存均在忽略目录 `artifacts/p7/three-policy-scorer-v2/`。

## 真实红绿与定向回归

| 验证 | Python 3.11 | Python 3.13 |
| --- | --- | --- |
| 修复前新公开测试 | **6 failed / 10 passed** | 未重复执行红例 |
| 最终源码定向回归 | **124 passed，1 integration deselected** | **124 passed，1 integration deselected** |
| 原 7 条签名记录离线复评 | 6 passed / 1 failed | 与 3.11 完全一致 |

六个红例分别覆盖 failed/cancelled/blocked × 显式 null/省略收据字段；修复后均正常输出严格失败，保留实际状态和 null verdict。其余反例验证：成功或 unavailable 缺收据继续拒绝，错 Run/版本/编排 Verification/Artifact/Scope、unknown 状态及伪造 tool_call_id 继续 fail-closed；合法的 empty 收据保持原 verdict 和拒答评分。没有以空字典代替收据或删除检查。

最终回归包括新测试、原 policy Smoke、原 Smoke 准入/预算、版本化 Scorer 和 RAG completion 契约。第一次回归后只做格式化换行，随后对最终源码重新执行，两版分别 4.38s / 4.54s。结果不跨轮累计计数。

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest tests/test_policy_smoke_receipts.py tests/test_policy_smoke.py tests/test_p7_smoke.py tests/test_p7_scorer_versions.py tests/test_rag_completion.py -m 'not integration' -q
.venv-313\Scripts\python.exe -m pytest tests/test_policy_smoke_receipts.py tests/test_policy_smoke.py tests/test_p7_smoke.py tests/test_p7_scorer_versions.py tests/test_rag_completion.py -m 'not integration' -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check src scripts tests migrations
git diff --check
```

Ruff 全仓通过；261 份 Python 格式通过；Diff 检查通过，已有 LF/CRLF 提示保留。完整 pytest、真实 PG/MCP、浏览器、远端 CI 均 **not_run**：本轮只改离线展示分支，没有以此前实测冒充新数据库验收。

## 同一批原件的 v1 / v2 对照

先在修改前重现原 6 条评分及 tps-07 的 TypeError，再保留旧源码并封存新 Scorer，使用同一 Case/Gold/签名采集/HMAC Key 离线对照。没有重新请求模型或改写原始响应。

| Case | 原 Scorer v1 | 修复 Scorer v2 | 实际业务结果是否改变 |
| --- | --- | --- | --- |
| tps-01 | passed | passed，全部评分字段相同 | 否 |
| tps-02 | passed | passed，全部评分字段相同 | 否 |
| tps-03 | passed | passed，全部评分字段相同 | 否 |
| tps-04 | passed | passed，全部评分字段相同 | 否 |
| tps-05 | passed | passed，全部评分字段相同 | 否 |
| tps-06 | passed | passed，全部评分字段相同 | 否 |
| tps-07 | TypeError，无严格分数 | **strict_correct=false**；Worker failed、receipt=null、业务 blocked | 否，仍不满足 Gold completed |
| tps-08 | not_run | **not_run** | 否，不补造宿主拒绝结果 |

计划分母始终 **8**，已观测 **7**。原评分为 6 passed / 1 scorer_error / 1 not_run；修订离线评分为 **6 passed / 1 failed / 1 not_run**。新增的是第 7 条可解释的失败评分，没有新增一次模型成功，也没有把结果修成 7/7。Python 3.11/3.13 的新旧逐条对照结构完全一致。

原 Live 的 **25 次调用、37,320 Token、USD 0.007696404 估算费用、账单未对账**保持原记录；本轮新增调用及费用均为 0。原 Campaign 仍为 `SMOKE_STOPPED_EVALUATOR`，没有改成完整执行成功；原 tps-07 目录仍没有 `score.json`，修订评分写入独立版本目录。

## 版本和完整性

| 对象 | SHA256 |
| --- | --- |
| 原 Implementation Manifest | `c46f092849e2fdd98f1220244641a1b8a43942c8b36c34429913cd7b2d6a79ce` |
| Scorer v1 原字节 | `3c8f4a0b6c305c23130950cd79cc6c2de6401738985cb33519766b3ac65cca3d` |
| Scorer v2 新字节 | `c5b178d5011847f96260b3344cc763a36275cbed0d88605e5d294eb8bc6cdb7d` |
| 新测试 | `6a9f31423285eb6d73a47f6040d9bc15e3120750d21148796e503cb5d07d855e` |
| **仅供离线评分**的 v2 Freeze | `4570601cf8c8be452d5e6cadcf5e8b9c9e7f00bf11b489e84dc9a54079af0a9f` |

开工时验证两个原结果 Seal，并保护 713 份已有文件。唯一获授权的字节变化是工作区 `scripts/p7_policy_smoke.py`，其余 **712 份不变**；旧 Scorer 在原完整冻结快照和本轮归档中均按原 SHA 保留。原 Case/Gold/协议/预算/Scorer Seal、模型响应、P3 Evidence/Verification、Journal/账本采集及历史报告 Hash 全部不变。没有连接数据库，因此本轮没有新的业务库写入或恢复操作。

新增测试使工作区闭包增加 1 文件，旧闭包原 284 文件中仅 Scorer 工作副本发生变化；`src/` 及所有业务实现依赖保持原 Hash。新 Freeze 明确 `offline_only=true / live_authorized=false`。**旧 Live Freeze 在当前工作区不再匹配，原准入检查仍正确拒绝；没有修改校验器来让旧 Permit 通行。** 未来 Live 需另建完整 Implementation Freeze 并取得新授权，不能拿这个 Scorer-only Freeze 续跑旧 Campaign。

## 剩余边界

Scorer 缺陷已修复，英文原问相关度不足和 Worker 回合耗尽问题**没有修复**；原 0.55、完成协议与保守业务 blocked 均保留。此次是离线评分完整性修复，不是英文能力提升或完整 Smoke 通过，不构成 Gate 3 准入。这里停止，不自动优化检索、增加回合、补跑第 8 条、调用模型或提交推送。
