# Fresh Web Smoke 两项失败修复

2026-11-02。修复源码提交：`434dc1870925b4740b51078804703f287f058dcd`（基于 `cccd829f7240b9ff56b7d3817c7b716c39616108`）。原 Freeze `p7-fresh-web-smoke-admission-v1-483bc675998f` 保持不变；这是本地修复，不是新的 Live 通过。

## 1. 根因与修复前证据

### 1.1 RAG Worker 完成但 Report 不发布文档事实

历史 Run `cc12be91-1f1f-486e-8fdb-d513857b8640`：

- Goal 的 `required_facts` 只有 `description`，`citation`、`quotation`、`confirmation_ref` 均为 `null`。
- `ReportService.fact_coverage()` 只接受已确认的 `citation + quotation`；因此 coverage 为空，`docs` 在转换为 coverage 后被清空。
- `topics_match` 为 false，最终 `business_completion=unavailable`，错误包括 `required_document_source_missing` 与 `document_fact_unverified:fact_1`。
- 这不是 Document/Chunk ID 字段改名问题；Artifact 中的 citation 含正确 Source/Document ID。**第一个丢失点是 Goal 未传递事实引述证明**。

### 1.2 SQL+RAG 预算预留失败

历史 Run `fc2201a1-f88e-4661-b9ec-24c654a0c08d`：

- 已用 7,119 Token，root 剩余 10,881。
- 第三次模型调用后 context 估算由 10,995 变为 12,131；下一次预留 13,331（含输出 1,200）在派发前被拒绝。
- 估算仍是原 `utf8_bytes_plus_128`，没有改成真实 Provider usage。
- 视图存在确定重复：同一 137 字符文档正文同时出现在 search 与 `read_context`；随后一次空搜索结果仍保留；压缩时又注入完整 authority anchor。L1/L2/L3 已尝试，但 12,131 仍超过可用 10,881。
- 没有发生第四次模型调用，也没有 unknown。

## 2. 最小修复

### RAG 事实传递

- `FactRequirement` 增加可选 `quotation`；UI 为每个事实提供“逐项原文引述”输入。
- Goal review 期间由宿主只读 MCP 检索原始问题，将引述匹配到唯一授权 source/chunk；宿主生成 `DocumentFact(citation, quotation, confirmation_ref)`。
- `task_payload` 不信任客户端 citation/quotation；客户端只提供引述文本，不能直接提交证明。
- `base_payload` 比较时移除宿主附带的 fact proof，但仍比较原问、Dataset/Source/版本。
- 无引述、引述不唯一或找不到时保持 `unavailable/can_confirm=false`，不自动升级。
- 原历史 Run 的旧合同保持 unavailable，不重跑、不篡改。

### 预算上下文

- L1 视图去重：完全相同的文档正文在后续 tool result 中只保留引用，不重复正文；空搜索结果压缩为简短引用。
- 紧预算时优先使用**紧凑 authority anchor**（authority SHA、allowed tools、不可验证声明），完整 authority 仍保留在不可变 prefix；不删除目标、版本、单位、时间窗口或证据引用。
- 未修改 8 calls / 18,000 tokens、1,200 output、父子账本、原子预留、unknown-outcome 或 L0–L4 结构；没有提高额度，也没有用缩小系数低估真实 usage。
- 预算仍不足时继续在调用前 `BUDGET_EXCEEDED`。

## 3. 验证

| 验证 | 结果 |
|---|---|
| 非集成 3.11 | **1344 passed，404 deselected** |
| 非集成 3.13 | **1344 passed，404 deselected** |
| collect 3.11 / 3.13 | **1748 / 1748** |
| Context 单元 | **39 passed**（两版） |
| Web Goal PG/MCP（3.11） | **16 passed** |
| RAG-only / SQL+RAG / admission PG（3.11） | **38 passed** |
| 新增引述事实反例 | **2 passed**（3.11；3.13 同组 41 passed） |
| SQL-only 回归 | **passed** |
| 空搜索/重复正文/紧预算 | 合成 ContextManager 反例通过 |
| 历史 SQL+RAG 上下文重放 | 原始运行消息与 artifact，估算 **11,448 → 9,615**（已含紧凑 authority）；加输出 1,200 = **10,815 ≤ 10,881** |

预算重放使用保存的 worker messages/artifacts 与按原 manifest 重建的 authority，是**非付费工程控制**，不是新的 DeepSeek Run；原始事件 10,995/12,131/13,331 仍保留。真正不足的预算仍会在调用前拒绝。

## 4. 修改文件及必要性

| 文件 | 原因 |
|---|---|
| `src/datapilot/web/contracts.py` | 接收可选精确引述，不接收证明 |
| `src/datapilot/web/goal_confirmation.py` | 宿主解析引述到唯一 citation，生成 DocumentFact |
| `src/datapilot/web/service.py` | base task payload 不把客户端引述当证明 |
| `src/datapilot/web/ui_components.py`、`ui_chat.py` | 提供引述输入并展示已选引述 |
| `src/datapilot/orchestration/context.py` | 去重重复正文/空结果，紧预算压缩 authority anchor |
| `tests/test_context_engineering.py` | 重复正文、空结果、紧预算控制 |
| `tests/test_web_goal_confirmation_postgres.py` | 真实 PG/MCP 引述事实与缺引述反例 |
| `.github/workflows/test.yml` | 1748/404/1344 计划数；无白名单 |

## 5. 仍未解决

- 历史 RAG Run `cc12be91…` 的旧 Goal 没有引述证明，仍为 **unavailable**；未重跑、未改历史结果。
- 预算修复只在 ContextManager 与保存上下文重放中验证；**没有执行新的完整 SQL+RAG Live**，因此不能声称新 Live 已通过。
- 新源码尚未运行完整 CI，也未建立新 Freeze/新 Permit；原 Freeze 和旧 Permit 不可复用。
- 实际 Provider 账单与本次修复无关（本轮 0 次付费调用）。
- 单 Run 180 秒仍不是硬终止；下一次 Live 必须继续按原 30 秒 Provider timeout、Campaign 截止/取消边界授权。

## 6. 提交与 CI 状态

- 本地修复 Commit：`434dc1870925b4740b51078804703f287f058dcd`
- 远端未推送；HEAD 之后仅追加本文档提交。
- 完整 CI：**PENDING**；计划 1748 tests（1344 non-integration + 404 PG）。未把本次修复标为 Live 通过。

## 7. 下一次新 Live 所需授权边界

必须使用新提交、新 Freeze、新完整 CI PASS、新 Permit 与新的负责人授权；不得复用旧 Campaign/Permit/剩余额度。建议仍为 3 个固定案例各一次、DeepSeek `deepseek-flash`、Thinking disabled、无自动重试、串行 1、每 Run 8 calls/18,000、全局 24/54,000；单 Run 180 秒仍不是硬终止。
