# P7 Browser Demo Recovery：Fake RAG 决策与失败投影

2026-11-01，分支 `p7-engineering-candidate-v1`，基线展示提交 `e42277c`。本轮只修复离线 Browser Demo 的两个明确缺口，不调用付费模型，不改 Goal v4 / P3 / Citation / Verifier 安全规则，不提交、不推送。

## 结论

| 项目 | 结果 |
|---|---|
| RAG_QUERY_POLICY 根因 | **定位并修复**（Fake 首查使用了含 Worker Schema 的 HumanMessage） |
| 第二个阻塞 | **定位并修复**（Fake 对非空证据恒提交 insufficient，宿主从未判定 complete） |
| 双版本定向测试 | 3.11 / 3.13 各 **63 passed** |
| RAG-only | **completed**，1 条真实文档 citation |
| SQL+RAG | **completed**，1432.25 CNY + Evidence/Verification + 文档 citation |
| failed Run 浏览器投影 | **可见**：failed / blocked / `RAG_QUERY_POLICY` / 任务明细 |
| 付费模型调用 | **0** |
| 产品安全守卫 | 未修改（仅 FakeTransport 决策 + 新测试） |
| Git | 未提交、未推送；1 个源码文件修改 + 1 个新测试 |

## 1. 精确根因

### 根因 B：Fake 首查未使用完整 Host 绑定目标

原 `FakeTransport.respond` 在 RAG 分支把 `HumanMessage.content` 整体当作 `search_documents.query`：

- `orchestration/loop.py::initial_messages` 构造的 HumanMessage = `task.instruction` + `"\nSCHEMA:\n" + authority_context`；
- 对 RAG Worker，`authority_context()` 是授权/来源 JSON，因此首查字符串实际为：

```text
计算2026年6月…以CNY整数分存储。
SCHEMA:
{"corpora":["a53942ba-…"]}
```

- `orchestration/tools.py` 的首查守卫要求 `args.query == self.original_query`，否则抛 `RAG_QUERY_POLICY`；
- Host 已在 `search_documents` 工具 schema 的 `HOST_FIRST_QUERY_JSON` 中提供精确目标，但 Fake 没有使用它。

**诊断复现**（`artifacts/showcase-browser/20261101-demo/diagnose_fake_rag.py`）：

```text
HUMAN_HAS_SCHEMA True
QUERY_INCLUDES_SCHEMA True
QUERY_EQUALS_HOST False
POLICY_WOULD_REJECT True
```

修复后：

```text
QUERY_EQUALS_HOST True
QUERY_INCLUDES_SCHEMA False
POLICY_WOULD_REJECT False
```

### 第二个阻塞：Fake 恒提交 insufficient

首查修复后，RAG-only Run `cd13933e…` 的检索实际返回 1 篇文档，但任务仍为 `unavailable`：

- `tools.py` 的 `_dispatch(SUBMIT)` 只在 `outcome=complete` 时调用 `validate_submission`；
- Fake 原逻辑对任何非空检索都提交 `insufficient`，因此原 Verifier 从未判定 `complete`；
- 证据本身存在且可检索（直接 MCP 查询 `billing-guide.md` 返回 1 条），所以不是 C（无证据），也不是 D（Verifier 拒绝）；而是 Fake 没有提出可验证的完成请求。

### 已排除的假设

| 假设 | 结论 | 依据 |
|---|---|---|
| A. Host Goal 身份/attestation 不一致 | 排除 | Goal `can_confirm=true`，`completion_eligible=true`，`retrieval_goal` 校验通过 |
| C. 检索无足够证据 | 排除 | 直接 MCP 检索与 Run artifact 均有 1 篇授权文档 |
| D. Verifier 拒绝合法完成 | 排除 | 修复前从未提交 `complete`；修复后原 Verifier 判定通过 |

## 2. 最小源码 Diff

仅修改 `src/datapilot/orchestration/model.py`（**+91 / −20**），全部位于 `FakeTransport`：

1. `_host_first_query`：从 `search_documents` 工具 schema 读取 `HOST_FIRST_QUERY_JSON`，首查严格使用宿主目标；无该字段时保留旧 fixture 回退。
2. `_host_goal`：从 RAG system message 读取 `HOST_GOAL_CONTRACT`。
3. `_rag_outcome`：仅当实际返回文档数 ≥ `minimum_sources` 且 `required_terms` 均出现在文档文本中，才提交 `complete`；空检索 `unavailable`，其余 `insufficient`；`unsupported_requirements` 或 `completion_eligible=false` 一律 `insufficient`。
4. 若宿主拒绝 `complete`，下一次只提交 `insufficient`（同一证据），不重复 complete、不发布被拒结论。
5. 未修改 `RAG_QUERY_POLICY`、`validate_submission`、Goal v4、P3、Citation、MCP 权限或预算。

新增 `tests/test_fake_rag_decision.py`：首查精确性、完成条件、空/不足证据、宿主拒绝后的降级。

旧测试 `test_original_query_policy.py::test_wrong_first_query_is_rejected_without_mutating_model_arguments` 继续证明错误首查仍触发 `RAG_QUERY_POLICY`。

## 3. 双版本定向测试

```powershell
pytest -q tests/test_fake_rag_decision.py tests/test_original_query_policy.py tests/test_orchestration.py
ruff check / format --check
```

| Python | 结果 |
|---|---|
| 3.11.16 | **63 passed** |
| 3.13.15 | **63 passed** |
| Ruff | check / format 通过 |

覆盖：精确 Host 首查、错误目标拒绝、无授权来源不可发布、空证据 unavailable、证据不足 insufficient、合法证据需原 Verifier 判定、宿主拒绝 complete 后降级。未运行完整双版本 CI（本轮未获授权）。

## 4. 新 Run 结果

### RAG-only（浏览器确认 + 浏览器审批）

| 项目 | 值 |
|---|---|
| Run | `b3c1b864-2e78-470c-9f27-99e2f7f6d7a1` |
| 终态 | `completed` / `succeeded` / `completed` |
| 任务 | rag succeeded；report succeeded |
| Citation | Chunk `02ed72c0…`，行 1–1，billing-guide.md 原文引述 |
| 审批 | 浏览器（Go/Enter 触发，详见方法记录） |

### SQL+RAG（浏览器确认 + API 兜底审批）

| 项目 | 值 |
|---|---|
| Run | `f3cb2227-8ac6-416f-b0b7-44dbe3a223cb` |
| 终态 | `completed` / `succeeded` / `completed` |
| 任务 | sql succeeded；rag succeeded；report succeeded |
| 数值 | **1432.2500000000000000 CNY** |
| Evidence | `0fd7fb80-0f02-421a-b7b8-2bd5b6461ef1` |
| Verification | `d0350350-15c5-42cd-b759-3d9c96cde7de` |
| Citation | Chunk `02ed72c0…`，行 1–1 |
| 审批 | 浏览器控件操作后 API 兜底（`api-fallback-after-browser-control`） |

辅助 API 诊断 Run `f2e43d27…`（RAG）与 `d8ea06bd…`（SQL+RAG）同样 completed，仅作工程复核，不替代浏览器截图证据。

Provider 全部为 `mock` / `scripted-fake`，付费调用 0。

## 5. 浏览器截图

目录：`artifacts/showcase-browser/20261101-demo/screens/`（local-only）。

| 文件 | 页面 |
|---|---|
| `07a-contract-pending.png` | RAG-only Goal v4 合同（pending） |
| `07b-contract-confirmed.png` | 三项确认勾选后的合同 |
| `07c-approval.png` | `awaiting_review` 与独立审批 |
| `07d-execution.png` | rag/report 任务成功与执行状态 |
| `07e-report.png` | RAG-only completed + 原文引述/行号/Chunk |
| `07f-report-full.png` | 同一报告消息完整内容 |
| `07g-sources.png` | 来源、口径、时间与验证 JSON |
| `10b-contract-confirmed.png` | SQL+RAG 合同（指标+文档） |
| `10c-approval.png` | SQL+RAG 独立审批 |
| `10-execution.png` | sql/rag/report 三任务成功 |
| `10-report.png` | **1432.25 CNY + Evidence/Verification + 文档 citation** |
| `10-report-full.png` | 同一报告完整消息 |
| `10-sources.png` | 来源与验证依据 JSON |
| `12-report.png` | 历史失败 Run：failed / blocked / `RAG_QUERY_POLICY` / 任务明细 |

`12-report.png` 证明失败状态**可以在 UI 中看到**；此前“页面不显示失败”的判断是截图等待不足（该页约需 30–45 秒完成投影），不是产品缺失。本轮未修改 UI。

## 6. 仍需的产品修改

- **非必需**：失败 Run 的 Streamlit 投影首次渲染较慢（约 30–45 秒），可观测但不利于自动化；若要稳定浏览器测试，建议下一轮只读评估加载顺序/缓存，不改变状态语义。
- **非必需**：Playwright 对 Streamlit 复选框/按钮的自动化偶发不触发；本轮 RAG 浏览器审批成功，SQL+RAG 使用 API 兜底并如实记录。产品的人工操作路径正常，不建议为提高自动化成功率修改 UI。
- 未发现需要修改 Goal v4、P3、Citation、Verifier、MCP 或预算规则的问题。

## 7. 边界与 Git 状态

- 未修改历史 P7 Run/合同/Gold/Seal/STOP、Docker VHDX、当前 Demo Volume、Qwen/BGE 默认 Profile、CI 工作流。
- 未调用 DeepSeek 或其他付费模型；未重跑完整 CI。
- Git：`src/datapilot/orchestration/model.py` 修改（+91/−20）；`tests/test_fake_rag_decision.py` 新增；本报告新增；既有 8 份未跟踪研究文件保持不变。**未 Commit、未 Push、未合并 main。**
- 机器记录：`artifacts/showcase-browser/20261101-demo/evidence/recovery-acceptance.json`（local-only）。
