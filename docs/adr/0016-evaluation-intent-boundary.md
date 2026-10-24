# ADR-016：意图候选实验与业务执行分离

状态：2026-10-24，Gate 1 有界开发实验采用；默认网站部署不变。

## 决定

保留原 Rule-only 文件与原 ChatService。新增最小结构化提案 DTO、宿主验证函数和 rule_only/llm_only/hybrid 三种实验策略；函数只接受既有 Gateway，不创建第二个付费入口。模型没有 scope/version/SQL/审批字段，候选仍需原宿主重新授权与用户审批。月、季度、相对月只由确定性日期代码解析，未知口径保持澄清。

Live DEV harness 复用原 PG Journal、DurableLedger、lease 与 cancellation。评测 campaign 是执行元数据，不增加 Scheduler、恢复引擎、预算账本或 Checkpointer；它没有业务数据库工具。原 P5B issued/unknown/complete 规则和版本/Manifest 不改，只有显式原 campaign resume 才允许读取已提交响应，未知结果仍阻断。实验结果只引用收据与 hash，不公开 Prompt/密钥/业务行。

## 为什么暂不插入 Web

当前 ChatService 的候选解析发生在消息持久化前。直接在这里调用模型会带来并发响应丢失下的额外费用和 unknown-outcome 问题；本轮 Gate 1 只验证候选能力及开发集，不以绕过 Durable 的临时客户端实现产品接入。网站继续使用原解析器，原 task_payload/MCP/审批和业务证据规则保持。真实 API 与业务闭环的准入证据来自已完成 Gate 0；本轮意图调用不是新的业务 E2E。

## 字段和文件的必要性

- ProposedMetric：类别与原文片段，验证语义来源，不含业务公式。
- IntentProposal：问题 hash、候选/澄清、至多两个指标/时间词、文档目标；限制输出体积与遗漏，不授予权限。
- evaluation.py：意图 Gold/Observation、严格槽位比较、分母、Wilson 与去重检索计数，防止测试/Transport/粒度混用；不是通用 Agent 框架。
- prepare/evaluate/summary 脚本：显式可信评测操作，合成数据、独立 Gold、哈希封存和只读收据分析。隔离 PG/重启脚本是此前已启动的工程评测工具，模型不能调用。
- 没有新增生产数据库字段、Schema、角色 grants 或模型工具。

## 限制与后果

受限语义锚点有保守错误拒绝；LLM-only 也必须通过安全守卫，不能和未过滤模型作对照。12 条 dev 的 Hybrid 12/12 不代表总体能力；复杂多轮、长问题、任意术语和剩余开发任务没有 Live 证据。封存 Holdout 与未来 P11 对照单列，不使用已看结果继续调优。后续若要 Web 集成，必须另审同一用户意图的模型计费幂等、持久关联、取消和审批契约，不借此绕过原 Journal。
