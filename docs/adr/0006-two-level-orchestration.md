# ADR-006：D9–D10 固定拓扑、动态 DAG 与受限 Worker 子图

日期：2026-10-21。状态：已实现 P4 编排子集；PG Checkpointer/Memory/长期预算恢复仍属 P5。

## 决策

1. 主 Runtime 继续使用锁定的官方 LangGraph 1.2.16。每个逻辑 Run 创建一个 Coordinator，编译一次固定外层图与一次共享 Worker 子图。Planner/Replan 仅更新经过校验的 Plan 数据，不能创建新节点、代码或工具；不修改 site-packages，不 Fork。
2. 外层 Planner → Scheduler → Send(worker) → Verifier → Scheduler / Replan / Finish。动态出口采用 Command，不再混合相同节点的静态业务出口；只有 worker→verifier、finish→END 为固定边。并行结果用版本/task key 合并，相同结果幂等、冲突失败。Scheduler 只派发依赖已通过且能力可用的任务，按扇出限额分波次。
3. 严格 Pydantic TaskSpec/Plan 定义 DAG；TaskEnvelope、预算/工具能力/依赖引用由可信宿主补入，Planner JSON 无权限字段。TaskResult/VerificationResult 明确终态、来源引用、错误类别及子预算使用；RunState 采用 TypedDict + reducer，不保存模型历史、连接或密钥。
4. SQL 与 RAG 使用同一套可复用 Worker 子图逻辑，但各任务有独立消息、ToolRegistry、能力和输出。SQL 只得到数据库 Schema/SELECT，RAG 只得到检索；注册表对象也不保留另一 Worker 的工具句柄。不能递归创建任意子 Agent 或扩权。Analysis 是固定 Decimal sum/ratio；Report 是确定性证据汇总，均无模型/外部工具。
5. 内层保存原始 AIMessage 与对应 ToolMessage。拒绝非法/重复 call ID、参数和虚构引用；工具错误、拒绝、预算终止或取消不会留下未配对 tool call。成功后模型再次决定返回实际 artifact ID，不能自报业务数字。SQL 编译修复只归本地 Loop，安全拒绝不重试；暂时性工具错误才可进入有界外层 Replan。
6. NativeTransport 使用 ChatOpenAI.bind_tools + ainvoke，SDK 重试关闭。Gateway 是 P4 新模型调用的唯一预留/结算入口，覆盖 Planner、Worker、Replan；原子内存 Ledger 同时检查根与子账户，未知 usage/取消保留保守预留。同一取消信号传至所有 Worker，真实 coroutine cancel 继续向调用者传播。
7. 已验证且定义未变的无依赖源任务可以在新计划中显式复用，记录 reused_from 并重新验证引用；派生 Analysis/Report 重新执行。旧版本结果不能仅凭同名 task_id 自动成为新版本结果。没有通用回放/调度引擎或新恢复队列。
8. P4 使用有界、按 Run 隔离的内存 ArtifactStore；它与 P3 持久化 Metric Evidence 不混称。显式 JSON/本地 Trace bundle 可导出工件以复核引用，公开 Trace 默认不含 SQL、参数、业务行或文档原文。P4 任务验证检查执行契约，不代表通用 SQL 已通过 P3 六层指标语义验证。
9. RAG Loop 与检索协议本轮落地，默认服务没有真实 RAG 后端。组件替身必须在结果/Trace 示例中标注 fixture；真实 Embedding/pgvector 检索、生产鉴权和完整业务报告不提前实现。

## 参考与取舍

本轮重新阅读 Mini 固定提交 `0b452360866433fde0dc77cd37ada9d303546592` 的 Python agent.py/subagent.py/tools.py，借鉴 Loop、fork-return、工具定义/执行分离及权限检查概念。没有复制第三方源码、Prompt、Shell/文件工具或会话框架；归属继续见 third-party-references.md。具体源码位置和独立接口见 orchestration.md。

默认预算调整为 8 次模型调用、20 次外层控制步骤，单 SQL 快路径实际仍只需两次 Worker 决策，配置上限不等于必然消耗。外层步骤不计入内层轮次，内层另受 4 轮/子预算/SQL 尝试和超时控制。Root Ledger 在进程内原子，但未实现数据库事务账本或重启恢复；同一 Coordinator 不是多 Run 并行服务实例。

公开 API 足以表达当前需要，没有证据要求修改 LangGraph 内核。Gate C 仍需 P5 持久恢复、P6 真实检索与业务闭环；本 ADR 不宣布 Gate C 全部通过。
