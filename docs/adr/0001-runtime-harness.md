# ADR-001：LangGraph Runtime 与领域 Harness 的双层执行

日期：2026-10-21。状态：P4 已落实 D9–D10 子集，见 ADR-006；持久预算/PG Saver/Memory 仍待 P5。适用范围：SaaS 主线，共用机制可供后续 Domain Pack 使用。

## 背景

原 P0/P3 背景为固定四节点链与同步模型接口。P4 已改为固定拓扑/动态 DAG/Send、独立 Worker 子图与原生异步调用；旧 `SQLAgent.run`、`JSONModelClient.generate` 作为独立兼容/P3 路径保留。持久检查点和共享持久预算仍未实现，内存原子账本不能替代它们。

## 决策

外层复用 LangGraph StateGraph、Send、Command、reducer、RetryPolicy、Checkpointer、interrupt/resume。业务层负责计划合法性与就绪任务策略，不另建通用执行队列、检查点回放或第二套 Scheduler 状态存储。

固定编译可复用图：`Planner → ValidatePlan → Scheduler → Worker → Verifier → Finish / Recovery / Replan`。执行中的 DAG 是 State 数据，不是模型任意创建的代码或图节点。简单问题只产生一个 SQL 任务；复杂问题按必要能力拆分。Send 仅派发依赖成功且产物有效的任务，限制任务总数、扇出、并发与重规划次数。

SQL/RAG 的自主 Loop 优先表达为 Worker 子图：`decide → validate_action → execute_tool → verify_feedback → repair / finish`。Analysis 的确定性算法可以直接执行；Report 根据已验证证据生成内容。子图输入/输出独立，显式适配父图；继承父 checkpointer 不等于接收整个父 State。

| 层 | 负责 | 不负责 |
|---|---|---|
| Runtime | 节点执行、superstep、channel/reducer、并发、检查点、暂停恢复 | 指标定义、业务事实正确性 |
| Harness | 就绪任务策略、上下文、工具契约/权限、预算、验证、错误分类/恢复 | 再造 Pregel、通用回放与模型训练 |
| Domain | 指标/映射/质量/验证规则、领域任务模板与评测 | 特化 Runtime 内核、启动任意工具 |
| Worker | 当前任务下的模型行动和有限反馈循环 | 私自启动绕过外层登记的递归调度器 |

## 状态、预算与错误边界

- TaskEnvelope/TaskResult 带 run/task/plan_version、dataset/version、依赖引用和证据引用。并发结果 reducer 对重复相同结果幂等接受，冲突失败；旧计划结果只能显式验证后复用。
- State 保存任务、引用、版本、预算引用/必要快照，不保存连接、SDK、秘密或大表。预算权威记录采用原子预留/结算账本；Checkpoint 快照不能替代并发原子性。
- 统一模型入口覆盖规划、子任务、摘要、Memory 辅助调用。允许复用 Mini 的子 Agent、权限模式与局部预算代码；外层共享预算和 MCP 能力约束始终生效。内部 bypass 不能改变数据库 grants。
- 模型调用改为真正 async adapter，或明确隔离的受限执行器；不能把 async 函数名当并发已生效。保留既有同步接口兼容层和独立取消测试。
- SQL 编译错误由 Worker 最多修复一次；安全拒绝不重试；短暂工具/Provider 错误指定唯一重试所有者。失败 DTO 不会自动触发 RetryPolicy。未知异常不得一概变成 MCP_CONNECTION_ERROR。
- Command.goto 不替换静态边；interrupt 前逻辑会重放。人工确认仅用于确需确认的操作，恢复值由可信服务端校验，不能作为模型可伪造的授权。

## Checkpoint 迁移的未决项

优先官方 PostgreSQL Saver，使用独立执行元数据角色/连接；其基础设施写入不是模型业务查询，Worker 不持有凭据。当前适配器未安装，未做持久恢复验收。

现有规则要求固定 Schema 经 Alembic；官方 Saver 自带 setup/MIGRATIONS。Gate C 持久化实施前须补充迁移 ADR：评估在显式部署流程中由 Alembic 受控协调官方迁移，包含需要 autocommit 的 DDL；若必须给元数据 schema 设置官方初始化例外，再明确更新规则。当前不自动运行 setup、不修改历史迁移、不在请求内执行 DDL。此未决项不阻塞 Parser、导入或语义层设计。

## 备选方案与后果

- 完整复制 Mini 调度/JSON Session：会与 LangGraph 恢复分叉，未采用。
- 一个节点包住整条长 while Loop：短流程可保留现有实现；长流程恢复粒度过粗，后续拆子图。
- 立即 Fork LangGraph：尚无证明公开 API 不足的复现，延后为独立实验。

验收：非法 DAG 拒绝、独立输入、依赖调度、有界并发、取消和预算、局部失败恢复、interrupt 重放、原 SQL 回归。真实 PG Checkpointer 重启测试须与内存探针分开报告。参考 [源码研究](../framework-research.md) 与 [路线图](../roadmap-v2.md)。
