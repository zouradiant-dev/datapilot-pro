# repair-v2 Live 结果与 CI 记录

日期：2026-11-02。Campaign `p7-fresh-web-smoke-repair-v2`，Freeze `p7-fresh-web-smoke-repair-v2-7b229020c7c2` / `7b229020c7c265866921b1685cb7ec2b2e598489345dd4073e258152b710d2f2`。

**Live 实际：2 completed / 1 not executed / 0 failed。** 这不是三条全部完成，也不是 3/3 Live Smoke 通过。完整 CI 另行为 PASS。

## 1. CI #31 — PASS

| 项目 | 实际 |
|---|---|
| Run | https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41441154000（#31，attempt 1） |
| Commit | `4cf867ee56b837a170a60b0d2abe2534394bb520` |
| 3.11 / 3.13 收集 | 各 **1748** = 1344 非集成 + 404 集成 |
| 3.11 / 3.13 集成 | 各 **341 passed / 63 skipped / 0 failed / 0 errors** |
| 合计通过 | 各 **1685 passed**（1344 + 341） |
| 原 60 项 | **60/60 passed** |
| Web Goal PG | **16/16 passed**（含新增引述反例） |
| 迁移 0009 | 日志确认 |
| Artifact digest | 3.11 `2f1891df…`；3.13 `95c948f6…`，ZIP SHA256 均一致 |
| 源码身份 | Freeze 27 个文件对 CI `source-sha256` **27/27 匹配，0 mismatch** |

CI 验收记录：`artifacts/ci31/verification.json`。  
CI 通过不等于 Live 三条全部完成。

## 2. 实际 Live 结果

### repair-web-01 — SQL-only：completed

- Conversation `f6428b0b-45e2-448c-9333-9be669338eee`；Message `4154a629-e963-43f0-9ebe-ba39a257611d`；Run `a4b36a6e-3ab2-4c82-9c82-98ac912a7970`。
- 数值 **803.3500000000000000 CNY**，窗口 `[2026-09-01,2026-10-01)`。
- P3 Evidence `8f933269-d64b-4fdd-bf57-0511fb68f17d`；Verification `0b14f25d-4971-4c84-9f51-ccd97bdab8e6`。
- 1 次模型调用，615 Token；business completed。

### repair-web-02 — RAG-only：completed

- Conversation `f8512f35-e11f-44be-acfe-38b0a911700e`；Message `137427b2-e439-445d-8a18-5fa3d7023608`；Run `920557da-fe64-475d-b992-f7ab99c1e690`。
- 事实完成，引用：
  - Source `2c794fb60592a71e5e6d7335e01327e77de933f2297e00750c189eaa227ef51c`
  - Document `5d60eb04b8bf637c7b9a60b21533b8c90e9ded5bca92451ceaff10c972af4a33`
  - Chunk `55469a84ebaa10725d40054188191836b62cc878f974f530fab24bac7f541b31`
  - 行 `1–7`；引述：**企业版退款申请须在 7 个工作日内完成审核，退款金额按原支付币种原路退回。**
- 4 次模型调用，6,861 Token；finish/tool 轨迹：`read_context` → `search_documents` → `submit_rag_result` → `stop`。
- business completed；不再出现历史 RAG 的 `required_document_source_missing`。

### repair-web-03 — SQL+RAG：not executed

- Conversation `08b9d4ec-2b31-41df-827e-2726a0b2c381`；Message `22c83089-7a04-44e0-9fb8-812f40a7ed6e`；Run `02b469bc-96b1-48f2-92ce-8a192efddc5b`。
- 状态：`awaiting_review`；模型调用 **0**；Token **0**；无 Report、无 business completion。
- 共享 Campaign 从最早 admission `12:15:54Z` 起 1800 秒截止为 `12:45:54Z`。浏览器在 `12:45:31Z` 尝试审批时按钮仍未 enabled，未提交 approval；截止后未再尝试。
- 因此是 **未执行（not executed）**，不是业务失败，也不是“通过”。未使用 API 审批兜底，未重跑。
- 新 STOP：`artifacts/p7/fresh-web-smoke-repair-v2/private/live/STOP`，时间 `12:57:33Z`；Live Host 已停止。

## 3. 调用、费用与边界

| 项目 | 实际 |
|---|---:|
| 模型调用 | **5**（SQL 1 + RAG 4） |
| Input / Output | 6,966 / 510 |
| Total Token units | **7,476** |
| Cache read | 4,224 |
| usage_complete | 全部 true |
| unknown calls | **0** |
| 自动重试 | **0** |
| Peak 估算费用 | **0.001459944 USD** |
| 实际账单 | **not_reconciled** |

### 必须披露的边界问题

1. **Permit 到期越界约 27 秒**：负责人窗口为本消息后 24 小时；实际 Permit `expires_at=2026-11-03T12:11:01Z`，比该窗口晚约 27 秒。没有在该 27 秒内调用模型；Campaign 的 1800 秒截止早于此。该 Permit 不可再复用，需新授权。
2. **SQL admission 的 permit digest 修正**：初次 Permit 使用内部 `fact_id=refund_turnaround`，UI 实际生成 `fact_1`，导致 SQL approval 被 `SMOKE_AUTHORIZATION_CHANGED` 拒绝（0 次模型调用）。随后用同一授权重签 Permit，仅把 `fact_1` 与新的 permit digest 对齐，并只更新 `repair-web-01` 的 admission digest；未改旧 Campaign/旧结果。
3. **30 个活跃会话配额已满**：复用了三个既有空会话（`f642…`、`f851…`、`08b…`）作为新消息容器，未修改旧消息、旧 Run 或旧结果。
4. **combined 未执行**：审批控件未变为 enabled，未发出 approval；截止后停止。没有资格把它写成通过或业务失败。

## 4. 旧结果保护

旧 Campaign `p7-fresh-web-smoke-v1` 保持：

- SQL completed / RAG unavailable / SQL+RAG failed/blocked
- **8 次调用 / 12,066 Token**
- 旧 3 条 admission、旧 STOP、旧 Permit、旧结果文档均未修改
- 新结果单独记录，不合并、不追溯提高旧成绩

## 5. 结论

- **CI #31：PASS**（1748/1344/404；341 集成通过、63 opt-in 跳过；0 failed/errors）。
- **Live：2/3 completed，1 未执行**；不能称为“三条 Live Smoke 通过”。
- RAG 事实引用修复在真实 Live 中生效。
- combined 的预算/上下文修复未被本次 Live 实际调用验证；它在此前的 ContextManager 定向验证中通过，但不能替代真实执行。
- 不自动进行第二轮；需新的 Campaign、新的完整授权、新 Permit（且不得重复/延长本次）。

## 6. 文件

- CI 记录：`artifacts/ci31/verification.json`
- Live 原始结果：`artifacts/p7/fresh-web-smoke-repair-v2/private/live/results.json`
- Live 最终状态：`artifacts/p7/fresh-web-smoke-repair-v2/private/live/v2-sql-final.json`、`v2-rag-final.json`、`v2-both-final.json`
- 新 STOP：`artifacts/p7/fresh-web-smoke-repair-v2/private/live/STOP`
- 机器汇总：`docs/research/p7-fresh-web-smoke-repair-v2-results.json`
