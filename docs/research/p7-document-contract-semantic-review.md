# 新 60 题：文档合同完整语义审阅

日期：2026-11-04，Asia/Singapore。负责人本轮明确授权执行文档合同完整语义审阅；本记录覆盖新 Holdout 的 40 道文档/组合题，未启动正式 Live。

## 结论

**40/40 逐题审阅完成，不能将 40 题整体标记为合同准入通过。**

| 分类 | 题数 | 当前可采取的动作 |
|---|---:|---|
| 可形成有限合同确认提案 | 24 | 已给出完整 Scope、逐事实引述提案、缺失目标和政策，等待合同采纳确认 |
| 精确来源准入待补 | 2 | 已生成单文件索引 Manifest/Hash 预览，未物化或改变原授权 |
| 仅允许宿主拒绝 | 4 | 保留真实非法输入；后续原生准入必须证明零模型/业务执行 |
| 仍有语义/完成状态口径缺口 | 10 | 先解决下列三类差异，不自动批准或登记有限目标确认 |

24 是可供确认的合同提案数，不是业务成功数；4 是本次文档子集的宿主拒绝题，未改变新 60 题原有 6 条拒绝控制的总数。其余题不删除、不挪出新 60 题分母。

## 已补齐的提案

- 引述补足主语、条件和后半句；不能拿孤立时长或第一步操作代表完整要求。逐题核对了 14 份原文、9 个 Corpus Manifest 及其原始/文本/Chunk Hash。
- 补齐草稿遗漏的订阅队列问项及英文授权边界；声明事实没有证明字段，证明提案单独保存在可信宿主审阅材料中。
- 对确实索取而来源未提供的文档事实单列未验证目标，保留负面原文作为缺失理由；不把“未提供某数值”的引述算作该数值已验证。
- 将真正的最终结论保留为未验证 conclusion；因果要求保留原 `causal_requested`，不把观察改成因果证明。
- 分离组合题的文档子问题，完整 Report 问题和原 MetricRequest 不改。两份提案消除了把 SQL 的“全部”范围误判成 RAG 穷举文档要求的问题；没有绕过原目标分类器。
- 对并列文档事实保留独立性；它们不充当指标的 P3 数字证据。明确要求的多个来源继续同时列为必需来源。
- 只对 3 份具有真实缺失文档问项的提案明确建议 `partial-facts-v1`，没有批量开启 40 题的部分发布。所有提案仍无生效的 GoalScopeAttestation。

50 个引述提案通过原生 `fact_coverage`、实际来源跨度/Hash 和授权 pin 检查；其中 37 个属于上述 24 份可确认提案。这是宿主审阅的机械验证，未产生 Runtime 工件、P3 Evidence 或业务质量成绩。

## 10 题需要处理的差异

| 差异 | 题数 | 处理边界 |
|---|---:|---|
| 完整题意与预期业务完成状态未形成一致合同 | 6 | 其中既有可回答的安全说明被要求 partial，也有必需已知子目标与整体 unavailable 的覆盖差异；不添加虚假的未完成目标、不改已接受 Gold |
| 额外数值请求尚无对应指标目标 | 2 | 不能只交给 Runtime 可执行的那部分，再用 Gold 补成 partial；不能把数值请求伪装为文档 Fact，也不能编造 MetricRequest/定义 |
| 主指标不可验证时，题目仍要求的引用会被当前关联规则抑制 | 2 | 必需引用不能静默降为 optional；文档引述也不能据此生成未验证数值 |

上述差异须作为题意、完成状态定义或合同表达能力的明确决策处理。本轮保留负责人已接受的 11 题修订及 Gold，并记录其中尚未解决的合同差异，没有重写题目、Gold、阈值或评分器来使其通过。

另有 2 题明确限定只依据某个文件，但当前索引包含其他文件。原 Repository 要求 pin 的文档集合与索引 Manifest 完全相同；仅缩短旧 pin 会被拒绝。已准备两个追加索引的精确 Manifest/Hash 预览，未写库、未改旧索引，也没有通过放宽权限解决。

## 私密审阅材料与验证

根目录：忽略的 `artifacts/p7/holdout60-formal-preparation-20261104/`。

- `document-semantic-review-v2/private/SEMANTIC-REVIEW.md`：全部 40 题的完整问题、逐题结论、修改提案、未验证问项及拒绝边界。
- `document-semantic-review-v2/private/reviews.json`：可核验的逐题决策和完整 Scope、引述/来源证明提案。
- `document-semantic-review-v2/private/proposed-cases-24.jsonl`：24 个严格 Case 提案，无生效审批或派发。
- `document-semantic-review-closure-v1/private/OWNER-CONFIRM-24.md`：仅含 24 份可确认提案的可读材料。
- `document-semantic-review-closure-v1/private/exact-index-previews.json`：2 个未物化的索引预览。
- `document-semantic-review-closure-v1/private/gap-classification.json`：10 题的具体缺口与 Case 对应，保持私密。

相关公开回归 **149 passed**。430 文件候选、生产 Worker/P3/权限/评分路径及 132 个历史受保护文件均保持原身份；11 题已接受的修订/Gold 回执和原待审记录保留。新增付费调用、数据库写入、正式 Run 均为 **0**。

下一步应处理 10 题差异和 2 个精确索引准入，并确认可采纳的合同；随后才生成新的正式绑定、Gold 映射和 Seal，执行原生 Host→Worker→Collector 控制。语义审阅完成不代替这些准入。

关联记录：[新 60 题正式准备](p7-new-holdout-formal-preparation.md)、[11 题修订接受记录](p7-new-holdout-revised-gold-approval.json)、[当前状态](../current-status.md)。
