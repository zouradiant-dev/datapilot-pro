# ADR-018：目标分类与可信有限范围确认分离

2026-10-30；Phase 2C.5，有界安全修复。先完成本记录和公开案例冻结，再运行v3基线、修改产品。

## 审计结论

1. `requirement_class`未命中有限拒绝语法时返回bounded；`unsupported_requirements=false`仅是未发现不支持条件，不能证明范围。
2. ReportScope是可信宿主合同；DocumentGoal/purpose、DocumentFact确认及CitationPolicy分别确认任务候选、单条事实、引用分类，没有独立的完整原问范围确认。
3. Registry的Semantic/Metric确认及MetricRequest已固定指标、Dataset/版本/窗口，不另建指标确认机制。
4. Completion验证原问Hash、授权片段、来源数和相关性，但没有范围正向证明；Report重复同一分类，因此存在共同失效。
5. Worker改写只影响检索，原Goal和Original-query-first由宿主绑定；新确认不得来自查询词或结果。
6. 完整Goal进入Manifest和Receipt.goal_sha256；Inspector按可信宿主配置重建，可复用原身份拒绝，不修改Journal/Ledger/Checkpoint。
7. fr002引用真实、Goal默认为bounded，局部事实不证明集合齐备；旧记录只读保留。

## 决策

在ReportScope增加可选的`goal_scope_attestation`：一份明确经宿主确认的**有限任务合同**引用。它记录版本、确认依据类型、确认引用、完整ReportScope合同Hash（排除自身）、RagScope Hash。合同覆盖完整原问、文档子目标、Dataset/Metric/窗口、Required Facts、CitationPolicy及其他宿主限制；RagScope绑定owner、版本化Corpus/Document。复用已有Host信任边界和Manifest，不新增签名密钥/数据库/审批引擎。

只允许可信宿主显式调用有限合同确认函数；不能由`unsupported=false`、source存在、事实confirmation_ref、高分、模型或普通审批执行许可自动生成。确认引用是宿主记录引用，不伪称独立人工签字。调用者须已经确认完整原问与合同等价，不能只批准缩小后的事实。函数不能证明任意自然语言等价，这个残余责任必须披露。

分类保留v3有界语法作为负向限制；新Goal版本为`host-goal-requirements-v4`。增加`completion_eligible`及范围确认身份；未确认但未被语法拒绝的目标仍可保持bounded分类，**完成资格为false**，避免把“分类未知风险”再次充作许可。范围不明确需宿主解决，不继续堆关键词。

唯一无需外部确认的原生例外是现有严格完整匹配的“仅定位含指定字面词的片段”合同；证明来自完整匹配的有限语法，不是语义分类回退。组合报告不能以较窄字面子目标自动证明完整原问。

Completion要求新完成资格；Coordinator/Report/Inspector根据同一可信合同重建。Report独立检查合同Hash、RAG Scope和原物理来源/事实，不相信上游succeeded/Receipt自述。无确认时保留可用的独立P3结果，整个组合目标不能completed。显式确认也不解除穷尽、快照、因果或既有证据约束。

原SQL-only/P3不用RAG完成确认，继续原Registry口径。明确有限文档合同可复用宿主确认对象，不需要每次重批指标。没有可信确认的旧语义RAG调用者必须补宿主确认或接受unavailable；本轮不为Web/LLM自动填写确认、不虚构新UI。部署前必须披露该兼容性变化。

## 身份与保护

新Goal及确认Hash进入原Manifest/Receipt，任何原问、owner、Dataset/版本、Metric/窗口、事实、引用策略或Corpus Pin变化都会使确认失效。旧v3恢复失败关闭为RECOVERY_IDENTITY，不迁移或重签旧Run。SQL-only不变。新测试在新隔离库；Phase2C.4停止目录和179 not_run绝不续跑。

## 验收

先登记至少50条公开合成正反例及评分Hash，在修改前运行v3基线；修复后检查有限合同不误拒、未确认目标不完成、伪造/过期确认不被接收；新PG/MCP分别验证BGE/Qwen、P3、跨进程恢复和unknown结果不重发。不是新质量A/B、付费Live或总体自然语言理解证明。
