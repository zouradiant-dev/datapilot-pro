# ADR-008：P5A 可压缩视图、权威边界与 Memory 契约

日期：2026-10-21。基线 `fb4c73461c4900f9128d011fd6dcf194f5926beb`。本决策只实施 P5A，保留 P4.1、官方 LangGraph 和 SQL/MCP 边界，不实施 P5B。

1. **权威与投影分离。** ContextManager 是现有 Gateway 的每 Worker 适配器，原 Loop 完整 AI/Tool 历史不改。SourcePin、MetricBinding、P3Reference 与 AuthoritySnapshot 是宿主范围/版本的快照，不是模型授权参数；固定 JSON/hash 防止浅层 frozen 对象的嵌套字段漂移。RunState、Registry、预算和取消服务不纳入可裁剪候选。
2. **先保存后减少视图。** L0 使用原 ArtifactStore；L1–L4 前把完整规范 transcript 存为同任务 context 工件，不另建文件或向量存储。配额/引用失败先终止，不能先截断后声称可恢复。“完整”限于同 Run 内存；跨进程持久化留给 P5B。
3. **按闭合轮次处理。** 每个 assistant tool_call 必须有唯一、同名、同 ID 的 ToolMessage。L1/L2 不删消息，L3 只折叠完整旧批次为引用，至少保留最新批次。未结算/重复 ID、孤儿/错绑 ToolMessage 或额外 System 消息拒绝。原 Loop 在完整历史检查 ID，折叠后仍不能重用旧 ID。
4. **保守摘要。** L4 不生成自由事实：目标、约束、unresolved、scope、Metric/时间/单位、P3 refs、Artifact refs 和 archive hash 必须逐字段等于宿主期望；只允许选择已观察的 turn ID。无法验证则 CONTEXT_LIMIT。它是受限摘取，不是通用语义摘要，也不将 P3 verified refs 接入业务报告。
5. **同一预算所有者。** 原 BudgetLedger 新增批量原子预留，覆盖摘要与最大合法后续视图。后续上界来自全部固定字段和至多 8 个最长合法 turn ID，不占用整个上下文窗口。实际调用仍经 Gateway，并发不能争用最后两次额度。拒绝摘要时仅释放从未发出的 follow-up，已发出/取消/未知 usage 保守 settle，重复 settle/release 明确拒绝。
6. **受限读取。** read_context 是固定 Registry 工具，按本任务实际清单、run/task/plan 和类型校验，分页及 JSON 编码后输出限长。仅归档/Schema，以及 RAG 本任务已取得的文档可读；不接路径、不读 SQL 行、不接受跨任务引用、不直接查询数据库。业务 SQL/检索路径不变。
7. **Memory 最小化。** MemoryEntry 只允许枚举偏好，或带版本的术语/决策引用，无任意正文/凭据/业务行/权限字段。宿主显式 review 才能存入内存实现；每次使用检查 owner/scope/worker/source_version/时间/失效。它只提供线索，不能复制 Registry、改业务口径、设置 verified 或恢复执行，模型没有 Memory 写工具。
8. **不假设缓存收益。** 不使用推测的私有 cache-edit API；cold/pressure 仅是本地策略，supplier cache_support=unverified。真实 Token/价格/延迟收益须另行实测，合成组件规模变化不等于供应商省费。

接口、源参考、失败用例、PG/Mock 分层结果及限制见 [交付](../context-engineering.md)。Gate C 未完成，P5B 必须另行授权。
