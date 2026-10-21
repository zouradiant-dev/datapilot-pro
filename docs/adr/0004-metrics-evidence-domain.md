# ADR-004：SaaS 语义、证据验证与业务域扩展

日期：2026-10-21。状态：P3 已落实 SaaS Registry/Verifier 子集，详见 ADR-005 与 semantic-metrics.md；通用 Domain Pack/非文件 Connector 仍为设计。

## 领域数据契约

下列为原逻辑目标接口；P3 的实际严格 DTO 和新 0003 持久化模型见 semantic-metrics.md。TaskEnvelope、通用 Domain Pack、文档证据与动态运行时未在本阶段实现；不要求每个名词对应独立微服务或表。

| 对象 | 最小信息 | 不变量 |
|---|---|---|
| DatasetVersion | dataset_id、version、文件/批次 hash、Schema/映射版本、状态、source_ref | 查询固定 ready 版本，变更不能悄悄覆盖历史 |
| SemanticBinding | entity/column_ref、业务名、时间/单位/币种、关系基数、确认状态、版本 | 字段名相似不代表同一业务含义 |
| MetricDefinition | metric_id/version、domain/version、定义/别名、实体粒度、时间列/窗口、过滤、单位、null/zero 政策、所需字段、可执行计算引用 | 已确认才能作权威口径；模型不能自行修改 |
| Evidence | evidence_id、dataset/version、metric/version、SQL 或文档 locator、参数、计算版本、结果/内容 hash、artifact_ref、完整性/截断、verification_refs | hash 保证完整性，不能单独证明业务正确 |
| VerificationResult | passed、layer、rule_version、failure_type、missing_evidence、retryable、feedback | 结果来自具体校验器，不能让模型自报 verified=true |
| TaskResult | task/plan_version、status、evidence_refs、artifacts、error、usage_refs | 引用必须存在、版本匹配且在范围内 |

## SaaS 指标基线

- `paid_invoice_revenue` 沿用当前口径：paid 账单按 invoice_date 求 amount_cents 合计，CNY 整数分，时间右开。不称为 MRR、会计确认收入或付款日期现金流。
- MRR/ARR 需明确订阅周期、有效区间、经常性收费、折扣/退款/货币等输入与政策；缺少所需字段时说明不可可靠计算，不用账单求和替代。
- 客户流失与订阅流失分开：约定事件、期初/平均基数、活跃状态构造、取消与到期、重订阅政策。现有 status 是记录最终生命周期状态，不能直接作历史月份活跃快照。
- 新增订阅沿用 start_date，包含套餐变更记录；不能等同新客户。客户新增用 created_at。
- 使用量分析明确 feature、周期、订阅/客户粒度、缺失与真实零值；JOIN 聚合前确认基数，避免账单×事件重复计数。
- 报告区分已验证事实、有证据支持的解释和待验证假说；收入贡献分解、统计关联不自动构成因果推断。

## 六层 Verifier 与恢复

1. 安全：SQL AST、工具能力、数据范围与数据库权限。
2. 结构：结果列/行/类型/有限值、行数和截断契约。
3. 语义：指标版本、时间窗口、实体粒度、过滤、币种/单位、必要字段。
4. 数值：独立 SQL/确定性 Python 对照或可证明的不变量，不由 LLM 心算或比较自身重复结果。
5. 引用：证据存在、来源和结果 hash/版本一致、权限与引用位置有效。
6. 目标：请求的子问题得到支持；不能计算时说明缺失条件。LLM 可辅助解释，但不是唯一终态判定者。

“全部数字都有 Evidence ID”只是必要条件；错口径 SQL 的证据同样可能完整。缺证据返回 MISSING_EVIDENCE 让外层定点补查；编译错误局部修复；数据不足明确无法计算；安全/未授权 NON_RETRYABLE，不允许 Replan 换路径绕过。

## Domain Pack 与 Source Connector

`DomainPack`：domain_id、version、canonical_entities、entity_mappings/field_aliases、metric_definitions、quality_rules、verification_rules、evaluation_cases，可声明 connector 类型。来自服务端可信配置与已确认 Dataset 绑定；不允许上传文件包含任意 Python/SQL 规则并被执行。

`SourceConnector`：source_type、capabilities、extract_snapshot、schema_mapping、provenance、watermark（可空）、结构化错误。返回受控 SnapshotRef、源系统/提取时间/批次、external_record_id（若有）、hash、解析与映射版本；不把连接器凭据交给 Agent。

首发实现文件快照路径；接口不要求提前开发 API/增量同步。saas 为唯一首发主业务。drycleaning 是后续 Phase F 领域包，复用导入、Registry、Runtime/Harness 和四 Worker，不复制一套 Agent。未知 POS 软件/API/字段保持未知，仅在取得授权报表后映射；缺少真实数据时 fixture 明确标 synthetic。

干洗店候选实体：customers、orders、order_items、payments、member_transactions、pickup_records。会员充值、余额消费、订单实收、退款不双计；无成本不输出准确利润，无交付记录不输出超期率。跨域同名指标不能直接混用，指标绑定 Domain Pack 与 Dataset 版本。

## 验收

Gate B 覆盖漏 paid 过滤、JOIN 双计、右开边界、客户/订阅混淆、单位/币种、null/零分母、字段缺失、伪造引用及因果夸大。后续 ≥50 个独立 SaaS E2E 问题有开发集/保留集、独立 Gold 与 manifest；干洗店真实试点另列结果，不替代 SaaS 主评测。
