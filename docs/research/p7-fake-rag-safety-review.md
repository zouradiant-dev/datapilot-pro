# Fake RAG 安全审查与真实 PG/MCP 定向验收

2026-11-02，分支 `p7-engineering-candidate-v1`，远端基线 `e42277c`。本轮是 Browser Demo Recovery 的安全收尾：审查 `FakeTransport` 决策、补齐负例、双版本定向测试、在隔离 PG17/pgvector 上运行真实 PG/MCP 验收。未调用付费模型，未运行完整 CI，未 Commit/Push。

机器记录：`artifacts/showcase-browser/20261101-demo/evidence/fake-rag-safety-review.json`（local-only）。

## 1. 原问题与修复结构

Browser Demo 的 `RAG_QUERY_POLICY` 有两个根因：

1. Fake 把包含 `SCHEMA/authority_context` 的整个 HumanMessage 当作首查 query，未使用工具 schema 中的 `HOST_FIRST_QUERY_JSON`；Host 首查守卫因此拒绝。
2. Fake 对任何非空检索恒提交 `insufficient`，从未让原 Verifier 判定 `complete`。

修复仍只位于 `FakeTransport`：

- `_host_first_query`：从工具 schema 读取 Host 精确首查目标；缺失时回退旧 fixture 行为，Host 绑定路径仍由原守卫拒绝错误 query。
- `_host_goal`：读取 `HOST_GOAL_CONTRACT`。
- `_rag_outcome`：仅当 Host 字段完整且为 `minimum_sources` 正整数、`required_terms` 字符串列表、`unsupported_requirements=false`、`completion_eligible=true`，且实际文档数/字面词满足时提出 `complete`；空检索 `unavailable`，字段缺失或畸形一律 `insufficient`。
- Host 拒绝 complete 后，从**该任务 transcript 中匹配 tool_call_id 的 submit 调用**取回证据并降级为 `insufficient`，不重复 complete；不使用跨任务共享的实例状态，恢复/重放也由消息重建。
- 未修改 `ToolRegistry`、`RAG_QUERY_POLICY`、`validate_submission`、Goal v4、P3、Citation、Report 或 MCP 权限。

## 2. 安全审查结果

| 检查项 | 结果 |
|---|---|
| Host 首查目标优先于 HumanMessage | PASS |
| SCHEMA JSON 不混入 query | PASS |
| 无可信 Host 目标时不绕过首查守卫 | PASS（回退后仍由原守卫拒绝） |
| 错误/翻译/拼接 query | PASS（`RAG_QUERY_POLICY` 保留） |
| Fake complete 候选 ≠ Host 业务完成 | PASS（Host 仍独立验证） |
| 关键词命中 ≠ 事实证明 | PASS（无 Host fact proof 时 `fact_coverage` 为 None） |
| 同 Source 多 Chunk 不满足不同 Source 数 | PASS（Fake 可能提出；Host 拒绝） |
| 旧/撤回/失效授权 | PASS（原测试与 PG 测试保留） |
| 失败后降级不重复 complete | PASS |
| 预算/Journal/Durable | 未改协议；相关 PG 测试通过 |

**结论**：Fake 的启发式可能提出“完成候选”，但原 Host/Verifier 是唯一完成权威；未观察到 False Completion、权限绕过或未验证引用发布。个别候选决策不足（同 Source 计数）被 Host 正确拒绝，记录为“候选不足、最终安全拒绝”，不需要修改安全核心。

## 3. Required Source/Fact 与反证案例

### 3.1 Fake 候选 vs Host 拒绝

新增 `tests/test_fake_rag_decision.py::test_fake_complete_candidate_on_same_source_is_rejected_by_host`：

- 两条 Chunk 同属 `same-billing-guide.md`，goal `minimum_sources=2`；
- Fake 按文档数提出 `complete`；
- `validate_submission` 按不同 source 计数，抛 `EVIDENCE_INSUFFICIENT`；
- 结论：**候选决策不足，最终安全拒绝**。

### 3.2 关键词不能成为事实证明

新增 `test_keyword_presence_cannot_create_host_fact_proof`：

- 文档包含“下一年度退款比例”字样，但同时说“不适用”；
- Goal 的 Required Fact 没有 Host 确认的 immutable citation + quotation + confirmation_ref；
- `fact_coverage` 返回 `{future_refund: None}`；
- 结论：Fake/关键词不能把文档文本变成业务事实证明；Report 仍要求 Host 审核的引用。

### 3.3 其他负例（保留原断言）

- 错误首查：`test_wrong_first_query_is_rejected_without_mutating_model_arguments`（RAG_QUERY_POLICY）；
- 空检索：`test_empty_and_nonempty_insufficiency_have_distinct_terminal_reasons`；
- 无关非空：`test_irrelevant_nonempty_cannot_be_complete`；
- 未确认语义目标：`test_related_semantic_goal_without_confirmation_is_not_self_approved`；
- Required Source / Citation 身份：`tests/test_citation_policy_postgres.py`（8 项真实 PG）；
- Required Fact：`tests/test_document_fact_postgres.py`（7 项真实 PG）；
- 失效/撤回合同：`tests/test_rag_only_postgres.py`（6 项，含 revoke）；
- 旧协议/恢复：`tests/test_rag_completion_postgres.py`（11 项）；
- 部分证据与业务完成：`tests/test_partial_evidence_postgres.py`（12 项）；
- SQL+RAG 跨来源报告：`tests/test_cross_source_postgres.py`（18 项）。

## 4. 首次查询与回退边界

- Host 绑定路径：工具 schema 含 `HOST_FIRST_QUERY_JSON`，Fake 严格使用该字符串；SCHEMA/依赖引用不进入 query。
- 无 `original_query` 的旧 fixture 路径：保留原行为，不新增授权或完成资格。
- 若 schema 缺失/不可解析：回退 `question[:512]`；Host 绑定路径随后仍由 `RAG_QUERY_POLICY` 拒绝，不能“回退绕过”。
- 查询长度超过 512 时由原 `SearchArguments` 拒绝，不截断伪造精确匹配。

## 5. Fake complete 候选与 Host 完成资格

- Fake 只决定“是否提出 complete 候选”，依据是 Host goal 的最低来源数与字面 required terms；
- Host `validate_submission` 独立检查 artifact 身份/版本/hash、不同 Source 数、required terms、`completion_eligible`、unsupported 条件；
- Report 进一步检查 Required Fact 的 Host citation/quote/confirmation 与 P3 证据；
- Fake 不创建 Attestation、不写 Journal/Ledger、不发布报告。

## 6. 双版本定向测试

命令（3.11/3.13 相同）：

```powershell
pytest -q tests/test_fake_rag_decision.py tests/test_original_query_policy.py tests/test_orchestration.py
pytest -q tests/test_fake_rag_decision.py tests/test_original_query_policy.py tests/test_orchestration.py tests/test_orchestration_hardening.py tests/test_rag_completion.py tests/test_rag_completion_transport.py tests/test_rag_contracts.py tests/test_citation_policy.py tests/test_document_fact_coverage.py tests/test_partial_evidence_report.py tests/test_cross_source_report.py
```

| 版本 | 聚焦测试 | 扩展单元/契约 |
|---|---:|---:|
| Python 3.11.16 | **66 passed** | **265 passed** |
| Python 3.13.15 | **66 passed** | **265 passed** |

failed/errors/skipped 均为 0。Ruff check / format 通过，`git diff --check` 通过。

实际 `--collect-only`（3.11 与 3.13 相同）：**1730 tests collected**；integration **388**，非集成 **1342**。相对基线 1724 增加 6 项，全部来自 `tests/test_fake_rag_decision.py`；388 项 integration 未变化。

聚焦 Node ID（新增/关键）：

```text
tests/test_fake_rag_decision.py::test_fake_first_search_uses_exact_host_query_not_worker_schema
tests/test_fake_rag_decision.py::test_fake_complete_requires_host_minimum_and_literal_terms
tests/test_fake_rag_decision.py::test_fake_downgrades_after_host_rejects_complete_without_new_evidence
tests/test_fake_rag_decision.py::test_fake_complete_candidate_on_same_source_is_rejected_by_host
tests/test_fake_rag_decision.py::test_keyword_presence_cannot_create_host_fact_proof
tests/test_fake_rag_decision.py::test_rejected_complete_is_bound_to_its_own_tool_call_and_artifacts
tests/test_original_query_policy.py::test_wrong_first_query_is_rejected_without_mutating_model_arguments
```

完整 Node ID/结果在 `pg_safety/artifacts/junit-unit311.xml`、`junit-unit313.xml`。

## 7. 真实 PG/MCP 定向验收

环境：

| 项目 | 值 |
|---|---|
| Compose | `datapilot-showcase-20261101` |
| 容器 / Volume | `datapilot-showcase-20261101-postgres-1` / `datapilot-showcase-20261101-pgdata` |
| PostgreSQL / pgvector | 17.11 / 0.8.6 |
| 测试库 | `datapilot_test_fake_rag_safety_20261101`（新库，迁移 0008 + runtime-init） |
| Demo 库 | `datapilot`（未用于本轮测试） |
| Live | 测试进程强制 `DATAPILOT_LLM_MODE=fake`、API Key 空、`DATAPILOT_RUN_LIVE_TESTS=0` |
| BGE | 模型 SHA `1294ea4b…`，未切换 |
| 历史 VHDX / Volume | 未触碰 |

3.11 按模块运行（聚合运行首次因 Windows pytest 临时目录 ACL 失败，已保留日志；改用 `--basetemp` 后重跑）：

| 模块 | passed | failed/errors/skipped |
|---|---:|---|
| rag_completion_postgres | 11 | 0 / 0 / 0 |
| rag_only_postgres | 6 | 0 / 0 / 0 |
| citation_policy_postgres | 8 | 0 / 0 / 0 |
| document_fact_postgres | 7 | 0 / 0 / 0 |
| original_query_postgres | 17 | 0 / 0 / 0 |
| partial_evidence_postgres | 12 | 0 / 0 / 0 |
| cross_source_postgres | 18 | 0 / 0 / 0 |
| **3.11 合计** | **79** | **0 / 0 / 0** |

3.13 同一组 7 模块、同一测试库：**79 passed**（24:54），0 failed/errors/skipped。本轮后续仅修改 FakeTransport；已核对 7 个 PG 模块不导入/不使用 `FakeTransport`，因此这 79 项覆盖的是未变化的安全/报告/MCP 组件，最终完整 CI 会在新提交上重跑全部分母。

JUnit/日志：`artifacts/showcase-browser/20261101-demo/pg_safety/artifacts/`。真实 MCP 子进程、PG、BGE（RAG 摄取）均执行；未使用 Mock 替代数据库。

## 8. 浏览器 Demo 回归

上一轮修复后的真实浏览器 Run 仍有效：

- RAG-only `b3c1b864…`：completed，citation Chunk/行号；
- SQL+RAG `f3cb2227…`：completed，1432.25 CNY，Evidence/Verification，citation；
- 失败 Run `fcae43d0…`：UI 显示 failed/blocked/`RAG_QUERY_POLICY`。

本轮修改仅 FakeTransport 决策内部与测试，未改安全守卫/展示服务，因此未重复创建展示 Run。已知限制保持：SQL+RAG 审批使用过 API 兜底，不能称为纯浏览器点击完成。

## 9. 新源码 Diff 与断言保留

```text
 M src/datapilot/orchestration/model.py      +130 / −21
 M .github/workflows/test.yml                +1 / −1（仅 1730/388/1342 数量元数据）
?? tests/test_fake_rag_decision.py           (6 tests)
```

- 仅 `FakeTransport` 修改；未改 Goal v4、ToolRegistry、RAG_QUERY_POLICY、Citation、Report、P3、MCP、Migration、Budget/Journal/Durable。
- 未删除、skip、xfail 或放宽任何既有断言；新增测试为追加。
- `model.py` SHA256：`5363ab5e…`；测试文件 SHA256：`a18b6b68…`；完整值见机器记录。

## 10. 历史工件与 Git

- 8 份历史未跟踪研究文件 SHA256 全部不变。
- 未触碰历史 P7 Run/合同/Gold/Seal/STOP、Docker VHDX、Demo Volume、Qwen/BGE 默认 Profile。
- 纳入提交的文件：
  - `M src/datapilot/orchestration/model.py`
  - `M .github/workflows/test.yml`（仅 test-scope 数量）
  - `A tests/test_fake_rag_decision.py`
  - `A docs/research/p7-fake-rag-safety-review.md`
  - `A docs/research/p7-browser-demo-recovery.md`
  - `A docs/research/p7-browser-demo-showcase-acceptance.md`
  - 既有 8 份未跟踪研究文件保留在工作区，不纳入提交
- 截图、日志、Host JSON、API Key、数据库、JUnit 均为 local-only，不进入提交。
- 本轮在安全审查与定向验收通过后创建一个独立本地提交，不 Push；具体 Commit SHA 由交付回复记录（提交内容不能自引用自身 SHA）。

本地提交信息：

```text
fix(fake): align RAG decisions with host-bound goals
```

## 11. 是否具备进入最终完整 CI 的条件

**具备候选条件，但尚未满足“当前源码已通过完整 CI”**：

- 双版本聚焦/扩展单元测试与真实 PG/MCP 定向测试通过；
- 安全负例未发现 False Completion、权限绕过或未验证引用发布；
- 产品修改仅限 Fake 决策，测试为追加；
- 完整 1730 项 CI 未运行；Actions #28 对应旧源码，不能证明当前修改。

正式 Push 后必须执行一次完整双版本 CI；产品代码提交不使用 `[skip ci]`。本轮不触发、不提前运行。

## 12. Gate

| Gate | 结果 |
|---|---|
| Fake RAG Safety Review | **PASS** |
| Host First Query Policy | **PASS** |
| Required Source/Fact Safety | **PASS** |
| Negative Evidence Safety | **PASS** |
| Python 3.11 Targeted | **PASS**（66 + 265） |
| Python 3.13 Targeted | **PASS**（66 + 265） |
| Real PG/MCP 3.11 | **PASS**（79） |
| Real PG/MCP 3.13 | **PASS**（79） |
| Browser Demo Regression | **PASS**（复用修复后 Run；本轮未重跑） |
| Paid Model Calls | **0** |
| Product Core Security Changes | **NONE** |
| Git Commit | **LOCAL（待审查）** |
| Git Push | **NOT_AUTHORIZED** |
| Full CI | **NOT_RUN** |
