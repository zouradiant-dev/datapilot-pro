# P7 Final 50：部分结果封存与下一步

日期：2026-11-03。本轮**不创建新 Permit、不调用 DeepSeek、不续跑已 STOP 批次**。

## 1. 源码身份（步骤 1）

| 项 | 值 |
|---|---|
| 已提交 HEAD | `4cf867ee56b837a170a60b0d2abe2534394bb520` |
| 基线完整 CI | #31 PASS，只覆盖该 HEAD |
| 工作区未提交 | independent document facts、single-case admission、current Formal 入口、`current_worker` 宿主 `confirm_finite_scope` |
| 当前源码完整 CI | **NOT_RUN** |

候选源码树：上述 HEAD + 工作区改动。在负责人批准提交并跑过 3.11/3.13 完整 CI 之前，**不得**对新树签发付费 Permit。

## 2. Final 50 v3 封存（步骤 2）

Campaign `p7-final-50-v3`，STOP=`infrastructure`（017 评分身份校验）。

| 指标 | 值 |
|---:|
| 计划 | 50 |
| 已采集 | 19 |
| 已评分 | 18 |
| 严格正确 | 10 |
| 严格失败 | 8 |
| 本批次未执行 | 31 |
| 模型调用 / Token | 59 / 92,556 |
| 峰值估算 USD | 0.021101424 |
| 账单 | not_reconciled |

严格正确：011–016（SQL）、034、036（RAG 预期 unavailable）、055–056（SQL+RAG）。  
严格失败：031–033、035、051–054。  
017：`blocked`，`Collected scope differs from the frozen task`（usage v3 vs 物化 v1）。  
050：`historical_unknown` 单列。075 在后续批次身份中仍按未知/未执行边界保留。

**不得**沿用本批次剩余额度、替换 key 或提高预算续跑。

## 3. 口径裁定（步骤 3）

| Case | 裁定 |
|---|---|
| 064 | 任务/Gold 要全功能用量；已确认 usage v1 仅 `export_batch`。P3 按定义算出 124，六层通过。原失败保留；不改 Gold/Registry。全功能口径需新任务身份 + 新确认指标。 |
| 077 | 同类错配（全功能 596 vs export_batch 391）。**不派发**。 |
| 017 | 冻结要求 usage v3，物化执行 usage v1，definition_sha256 相同但评分器按版本字段拒绝。显式记录映射；**不在评分器静默重映射**；原 blocked 保留。 |
| 其余 13 条可派发候选 | 见 `p7-final-50-remaining-scope-audit.md`；仅在新授权 + 新 Freeze + 宿主确认绑定修复后才可申请。 |

## 4. 八条“RAG 检索失败”只读拆分（步骤 4）

冻结评分器 `failure_class=rag_retrieval_failure`，但八条全部 `chunk.recall_at_k=1.0`（检索命中）。Report `missing_evidence.documents` 均为 **`goal_scope_not_attested`**。

| Case | 业务状态 | purpose | 检索命中 | 真实缺口 |
|---|---|---|---|---|
| 031 | unavailable | facts | 是 | 宿主未 `confirm_finite_scope`；Gold 另有 missing fact_2 |
| 032 | unavailable | facts | 是 | 同上 |
| 033 | unavailable | facts | 是 | 同上；Gold 期望 unavailable + missing fact_1 |
| 035 | unavailable | conclusion | 是 | 未确认 + 因果不得 verified |
| 051 | partial | facts | 是 | 未确认；metric 侧 amount_unit_unconfirmed 符合 Gold |
| 052 | partial | facts | 是 | 未确认；metric 侧 history_unconfirmed 符合 Gold |
| 053 | partial | facts | 是 | 未确认；Gold 另有 missing fact_2 |
| 054 | blocked | facts | 是 | 未确认 + 因果不得 verified |

分类：

1. **宿主确认缺失**（8/8）：`current_worker` 先前未调用 `confirm_finite_scope`。
2. **检索命中**（8/8）：不是空召回。
3. **引用/事实缺口**：部分 Gold 故意保留无证明 fact；确认后仍应 partial/unavailable。
4. **目标耦合**：本批 Formal 失败主因不是 Web combined 的 metric 耦合；后者已在独立 facts 路径单独处理。

**不改** Prompt、配方、Gold、Scorer 后重测该批次。Harness 修复见 `evaluation/p7_v3_current/current_worker.py` 的 `host_confirm_reviewed_scope`；仅用于后续新授权批次。

## 5. Combined 独立事实路径（步骤 5）

- 诊断：`p7-combined-independent-facts-diagnosis.md`
- 已有一次有界 Live：`p7-combined-independent-live-results.md` — 业务 completed，但源码冻结治理 FAIL（CRLF/新 Live Freeze），完整 CI NOT_RUN。
- 旧 Run `304ca32e…` 保持 unavailable/partial。
- **再申请 Live 前必须**：工作区完整 CI PASS、单一 Freeze 原始字节一致、新 Permit、页面显式 `document_facts_independent=true`、仅 1 Run / 8 calls / 18k Token、失败不重跑。

## 6. 畸形 usage（步骤 6）

`Journal._restore_model` 已将缓存畸形响应类型化为 `RECOVERY_CORRUPT`（见 `docs/p7-unified-regression.md`）。`ValidationError` 在本环境为 `ValueError` 子类，可被既有 except 捕获。隔离 PG 故障矩阵整表重跑仍为 **NOT_RUN**；不并入业务 Live。历史 13 passed / 1 failed 记录保留为修复前快照。

## 7. 后续授权条件（非本轮执行）

1. 提交候选源码并取得完整 CI PASS。  
2. 新 Freeze + 新 Permit；不复用 v3/v6/v7 STOP 批次。  
3. Formal 批次启用宿主确认绑定后，再派发口径已审阅案例如上。  
4. 064/077/017/050 与历史 unknown 单列，不进分母刷分。  
5. Combined Web Smoke 与 Formal 50 分开授权。
