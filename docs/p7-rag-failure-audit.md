# P7 RAG 失败独立审计

**RAG AUDIT COMPLETE**。审计 7 条引用失败与 2 条检索/完成失败；没有新模型调用、历史检索重跑、Embedding/0.55/Top-k/Prompt/Gold/Verifier 改动。不是新的正式效果评测。

## 1. 方法与证据

读取原始目标、文档子目标、原件、索引 manifest、完整签名响应/检索 Artifact、Source/Document/Chunk/Span/SHA、查询与宿主目标分数、完成收据和最终报告。所有已返回片段均通过原 verify_result 和原件 substring/hash 复核；没有把相似度当事实真值。

完整目标/查询/原文仅留私密 `artifacts/p7/scorer-v4/private/rag-audit-full.json`；[公开结构化审计](research/p7-rag-failure-classification.json) 给出查询 SHA/语言、top_k、Source/版本/span/hash/分数、事实与完成状态，不公开原文或私有 Prompt。阈值前候选与未返回文档的分数一律 not_observable。

## 2. 七条引用失败逐条结论

每条均已发布 Gold 必需文档、核心必需事实均有原文证明，且额外文档授权/hash 有效。失败的直接条件是额外来源不在冻结相关集合；这不自动等于事实错误或权限事故。

| Case | 分类 | 原 strict | Gold 争议 |
|---|---|---:|---|
| p7-holdout-v3-041 | related_nonessential_background | False | True |
| p7-holdout-v3-022 | related_nonessential_background | False | True |
| p7-holdout-v3-023 | plausible_acceptable_supplement | False | True |
| p7-holdout-v3-024 | unrelated_authorized_source | False | False |
| p7-holdout-v3-045 | related_nonessential_background | False | True |
| p7-holdout-v3-047 | plausible_acceptable_supplement | False | True |
| p7-holdout-v3-049 | plausible_acceptable_supplement | False | True |

**p7-holdout-v3-041**：发票粒度规则已由核算规程直接证明；额度条款属邻近计费背景，未证明分期不重复。非必需引用，是否允许背景引用需预注册政策。

实际业务 `completed`，Gold `completed`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `settlement.md`（Gold 直接来源）：query score 0.741376，host goal score 0.796513；span [0, 84)，chunk `d01b47d2c879…`。完整 index/source version/SHA 在机器记录。
- `credit.md`（额外授权来源）：query score 0.556475，host goal score 0.653630；span [0, 64)，chunk `4521d547c3ea…`。完整 index/source version/SHA 在机器记录。

**p7-holdout-v3-022**：撤回顺序由撤权流程直接证明；凭据轮换涉及相邻安全生命周期，却不证明 OAuth 两类令牌的先后。不能据额外来源直接判业务事实错误。

实际业务 `completed`，Gold `completed`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `revocation.md`（Gold 直接来源）：query score 0.746915，host goal score 0.806908；span [0, 64)，chunk `364ab3bb68b6…`。完整 index/source version/SHA 在机器记录。
- `credential.md`（额外授权来源）：query score 0.619023，host goal score 0.625490；span [0, 55)，chunk `01bfa0c9125c…`。完整 index/source version/SHA 在机器记录。

**p7-holdout-v3-023**：原目标要求区分额度与实际收款；账单核算和退款口径可作为相关补充，虽非核心提现限制的直接证明。Gold 单来源集合存在过窄争议。

实际业务 `completed`，Gold `completed`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `credit.md`（Gold 直接来源）：query score 0.691068，host goal score 0.758746；span [0, 64)，chunk `4521d547c3ea…`。完整 index/source version/SHA 在机器记录。
- `settlement.md`（额外授权来源）：query score 0.626074，host goal score 0.679808；span [0, 84)，chunk `d01b47d2c879…`。完整 index/source version/SHA 在机器记录。

**p7-holdout-v3-024**：合同续订/流失队列不解释事件 ID 与回调重试计费，属于已授权但无直接目标关联的多余来源；核心事件计量来源仍已命中。

实际业务 `completed`，Gold `completed`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `metering.md`（Gold 直接来源）：query score 0.726569，host goal score 0.758227；span [0, 95)，chunk `a342f44430bb…`。完整 index/source version/SHA 在机器记录。
- `contracts.md`（额外授权来源）：query score 0.575106，host goal score 0.633691；span [0, 82)，chunk `77c99a5eb6f4…`。完整 index/source version/SHA 在机器记录。

**p7-holdout-v3-045**：退款单列由核算规程直接证明；额度规则属于相邻资金概念，非退款登记的必需证明。作为背景是否合适有待独立审查。

实际业务 `completed`，Gold `completed`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `settlement.md`（Gold 直接来源）：query score 0.750129，host goal score 0.774889；span [0, 84)，chunk `d01b47d2c879…`。完整 index/source version/SHA 在机器记录。
- `credit.md`（额外授权来源）：query score 0.565760，host goal score 0.610442；span [0, 64)，chunk `4521d547c3ea…`。完整 index/source version/SHA 在机器记录。

**p7-holdout-v3-047**：全局目标同时涉及人民币账单收入、额度与现金退款；核算规程对该较宽目标具有补充价值，但文档子目标与 Gold 只标额度条款，存在范围不一致争议。

实际业务 `completed`，Gold `completed`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `credit.md`（Gold 直接来源）：query score 0.708278，host goal score 0.723012；span [0, 64)，chunk `4521d547c3ea…`。完整 index/source version/SHA 在机器记录。
- `settlement.md`（额外授权来源）：query score 0.635137，host goal score 0.669772；span [0, 84)，chunk `d01b47d2c879…`。完整 index/source version/SHA 在机器记录。

**p7-holdout-v3-049**：已付收入与缺失 MRR 口径是全局目标的两部分；核算规程可支持收入背景，额度条款支持 MRR 限制。partial 与缺定义保留正确，额外引用是否必然错误仍有标签争议。

实际业务 `partial`，Gold `partial`；必需来源缺失 0，额外来源 1。原 v3/v4 citations 均保持 False。

- `credit.md`（Gold 直接来源）：query score 0.758775，host goal score 0.752983；span [0, 64)，chunk `4521d547c3ea…`。完整 index/source version/SHA 在机器记录。
- `settlement.md`（额外授权来源）：query score 0.558716，host goal score 0.585418；span [0, 84)，chunk `d01b47d2c879…`。完整 index/source version/SHA 在机器记录。

024 的续订/流失队列与事件重试计费没有直接关联，是明确的引用选择噪声。023/047/049 的核算规程对全局收入/额度/退款区分具有补充价值，来源标签可能只覆盖文档子目标而窄于全局目标；041/022/045 是相邻领域背景，是否可保留应有预先一致的精确率政策。以上是 AI 辅助审查意见，**不是项目负责人批准新 Gold**；没有将 6 个争议/边界意见转换为正确分。

## 3. 两条检索与完成问题

### p7-holdout-v3-029

首次中文检索已返回已知事实所需来源；第二次查询指向文档中刻意缺失的驻留事实。模型携带非空 Artifact 提交 insufficient，Worker 转为 unavailable；报告依赖过滤排除该 RAG 的引用，已知事实未被保留。

宿主 minimum_sources=1；实际收据 `insufficient`，选择了 1 个真实非空 Artifact；最终 `unavailable`，Gold `partial`。

| 查询序号 | 语言 | Top-k | 实际执行 | 返回文档 | 拒绝码 |
|---|---|---:|---|---:|---|
| 1 | zh | 5 | True | 1 | — |
| 2 | zh | 5 | True | 0 | — |

已返回 `credential.md`，score=0.739684，goal_score=0.750901；来源/版本/hash 已核实。

纯离线调用**原确定性检索提交 Verifier**，只反序列化已有签名 Artifact、不发 Tool/模型请求、不建新 Evidence：若提交已有片段为 complete，门控会接受为 `semantic_retrieval`。

可能原因：完成决策可能混淆了检索目标与最终事实充分性；随后确定性的报告依赖过滤抑制了可用的部分来源。

不可确认：现有证据不能认定语言或 Embedding 失败，模型为何选择该完成状态的内部原因不可观测。

### p7-holdout-v3-030

两份必需来源仅返回一份。以英文短语为主的改写返回 no_matches，第三次搜索请求被正确拒绝。宿主纠正与 insufficient 收据均已持久化；unavailable 报告没有保留已取得的声明。

宿主 minimum_sources=2；实际收据 `insufficient`，选择了 1 个真实非空 Artifact；最终 `unavailable`，Gold `partial`。

| 查询序号 | 语言 | Top-k | 实际执行 | 返回文档 | 拒绝码 |
|---|---|---:|---|---:|---|
| 1 | zh | 5 | True | 1 | — |
| 2 | mixed_english_rewrite | 5 | True | 0 | — |
| 3 | zh | 5 | False | NA | RAG_ATTEMPTS_EXHAUSTED |

已返回 `annex.md`，score=0.579249，goal_score=0.667757；来源/版本/hash 已核实。

纯离线原 Verifier 对已有片段的 complete 仍拒绝：`EVIDENCE_INSUFFICIENT`。这不是新 Run 或改写实际收据。

可能原因：查询与来源的语言差异、查询具体程度可能有影响；两次搜索上限及保守的部分来源传播规则也影响最终结果。

不可确认：阈值前分数/排名以及替代查询的反事实结果均为 not_observable，无法确定唯一召回原因。

029 两次查询均是中文：第一条已命中合格的已知事实来源，第二条面向来源中刻意缺失的信息，空召回本身合理。原门控已具备完成检索的条件，但实际模型提交 insufficient；随后 Worker 标为 unavailable，原 Report envelope 排除非 succeeded 的 RAG refs，已知事实也未进入受限结果。应区分模型完成决策与确定性部分证据传播，不应简单归因为阈值/Embedding 失败。

030 第一条中文查询只返回合同附件，未找到另一份区域说明；第二条为以英文短语为主的中英混合改写，结果为空。语言差异可能影响检索，但没有阈值前分数与反事实执行，不能确定为唯一原因。第三次中文请求被正确限额拒绝，非第三次实际检索、非权限事故。正确保守地拒绝最终优先级结论，与可以保留已知合同声明，是两个不同完成层次。

## 4. 新 Dev、限制与下一步所需证据

协议测试使用独立 orchid 合成交互，覆盖合法 control/真正孤儿/伪造/配对/限额，不是模型质量测试。另经原受限 RAG 服务追加青栈三文档 Dev Corpus（3 Source/3 Chunk），只读真实 BGE+PG/MCP 两次查询固定 0.55/Top-k5，并验证非法索引拒绝；Python 3.11/3.13 各 3 passed。没有模型自主改写或新的 DeepSeek 成绩。

旧 phase3b 索引在当前 unified 实例不存在，初次 Dev 测试被权限检查正确拒绝，错误日志保留。新 Dev 单独命名和摄取，没有重新 Seed、摄取旧 Holdout、修改旧语义定义或权限。新 Dev 仅证明基础真实接线与边界，不能证明补充文档裁决或生产 RAG 已优化。

| 建议 | 下一次需要的独立证据 | 本轮实施 |
|---|---|---|
| 将必需证明/可接受补充/无关背景分开标注，裁决全局目标与文档子目标的范围 | 新 Dev 双人或负责人审阅的多标注来源集合、预注册 precision/coverage 规则；争议走新 Gold 版本 | 否 |
| 收紧无关引用的选择，保留有用补充 | 新主题下标定引用选择正确率及误删支持来源的负例，不用旧29刷阈值 | 否 |
| 明确检索完成与业务事实充分性的职责 | 独立已知事实+未知事实任务，验 Worker receipt 与 Report partial，不能将 insufficient 升级 verified | 否 |
| 安全保留不可完全回答任务中的已验证背景片段 | 新独立 Dev 覆盖字段/Source不足、收据、事实证明、P3/RAG隔离与重启一致性；设计需另行授权 | 否 |
| 评估语言一致查询策略 | 新 Dev 固定语料/权限/预算/阈值，对照查询语言；不得依据030推定需降阈值或加 Reranker | 否 |
| executed-query 与 denied-attempt 分母、见证及时采集 | 新评测协议单独冻结，TTL 前采集原生检查点/Journals，拒绝记录不当作额外执行 | 仅审计/协议验证 |

新 v4 更可信地判断了协议，但没有解决来源标签争议、029/030 的业务失败或补齐31条 not_run。可以为下一轮独立评测开展另行批准的准备，尚不能直接发起新 Live，也不能把旧 v3 Campaign 改为有效通过。不进入 Gate 3、不改产品、不提交推送。
