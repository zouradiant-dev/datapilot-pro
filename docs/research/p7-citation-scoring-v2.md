# P7 引用评分 v2

日期：2026-11-04。负责人明确接受额外的真实、授权文档引用后，本轮调整当前评分口径。产品 Runtime、Report、Goal、P3、Gold 和冻结 v3 评分文件未修改。

## 新规则

版本为 `p7-current-authorized-citations-v2`，入口为 `evaluation/p7_v3_current/scorer.py::score`。`score_legacy` 保留此前的评分行为，每份新结果同时记录 `legacy_strict_correct`。

- 不再仅因引用超出 Gold 的相关文档集合就判整题失败。
- 所有引用仍须通过签名采集、授权范围、artifact/excerpt 一致性，以及冻结 Source、版本、IndexVersion、Chunk/span/Hash、模型和 chunker 身份核验。
- 必需事实、数值、业务终态、拒绝语义、因果、预算、协议与恢复维度继续使用原判断。
- 额外来源不能补足 Gold 要求的最少相关来源数量，也不能替代缺失事实。
- `citation_quality.document_precision` 按已发布的去重 Document ID 计算，记录相关文档占比；额外文档 ID 单列。它是质量指标，不再单独否决整题。原检索 Recall/Precision/MRR 保留。

这是一项已观察案例后的评分口径修订，结果必须标注新版；不把它表述为新的独立盲测成绩。

## 非付费验证

| 检查 | Python 3.11.16 | Python 3.13.15 |
|---|---:|---:|
| 新引用评分与既有评分/签名/恢复定向测试 | 79 passed | 79 passed |
| failed / errors / skipped | 0 / 0 / 0 | 0 / 0 / 0 |

16 项新增公开合成用例覆盖：真实授权额外引用允许；缺失必需事实、相关来源不足、越权、版本/Source/Hash 篡改、重新签署但不符合原 pin 的伪造引用、unknown/未审批、错误签名、预算和因果边界仍失败。测试不依赖本地私密工件、数据库或 Provider。

Ruff、format、JSON 和 `git diff --check` 通过。未执行完整 CI。

## 保存采集的离线复评

仅使用前轮已签署的 8 份真实 PG/MCP/BGE + Fake Worker 采集，没有重跑任何 Run、数据库查询或模型调用。

| Case 后缀 | 原严格结果 | 新严格结果 | 文档引用精确率 |
|---|---|---|---:|
| 031 | PASS | PASS | 1.0 |
| 032 | PASS | PASS | 1.0 |
| 033 | FAIL | PASS | 0.5 |
| 035 | FAIL | PASS | 0.5 |
| 051 | BLOCKED | BLOCKED | — |
| 052 | BLOCKED | BLOCKED | — |
| 053 | FAIL | PASS | 0.5 |
| 054 | PASS | PASS | 1.0 |
| 068 | FAIL | PASS | 0.5 |
| 069 | FAIL | PASS | 0.5 |

完整 Case 前缀为 `p7-holdout-v3-`。合计从 **3 PASS / 5 FAIL / 2 BLOCKED** 变为新版口径下 **8 PASS / 0 FAIL / 2 BLOCKED**。8 份结果的非引用维度与旧评分完全相同，Source pins 全部通过，未新增安全违规。051、052 的合同范围问题仍未解决，本轮未执行它们。

旧 Gold、采集、签名、score.json、历史总结及 STOP 保留不变；新结果写入独立目录。复评前后核对来源与旧结果 SHA256，没有覆盖原分数。

## 文件与后续

- 修改：`evaluation/p7_v3_current/scorer.py`。
- 新增公开测试：`tests/test_p7_current_citation_scoring.py`。
- [机器结果与 SHA256](p7-citation-scoring-v2.json)。
- 本地证据：`artifacts/p7/final50-citation-policy-v2-20261104/`，含两版 JUnit/日志、`rescore.py`、逐题 `score-v2.json` 与 `summary.json`。

下一步只需处理 051、052 的 Report/RAG Dataset 范围与指标关联合同。真实 DeepSeek 的逐题质量结论仍需对应 Live 证据；本轮是离线评分修订，新增 Run 和付费调用均为 0。旧执行 Freeze/Manifest/Permit 未刷新；后续正式执行须显式绑定新版评分身份，不能静默替换旧冻结评分。

未 Commit、未 Push，先前工作区改动保留。
