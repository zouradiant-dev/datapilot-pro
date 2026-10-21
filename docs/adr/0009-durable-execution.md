# ADR-009：P5B 官方 PostgreSQL Saver 与领域持久状态

日期：2026-10-21。状态：已采纳；P5B 单独授权，不进入 P6/P7。基线 42fb6b6。实际验收见 [交付记录](../p5b-delivery.md)。

## 审计与所有权

RunState 的计划/版本、结果、验证、步骤与终态由官方 LangGraph Checkpointer 唯一管理。Coordinator.plans/reused 改为可由图状态重建的缓存；question 从可信运行身份和图状态重建。store/ledger/cancellation 是独立权威持久服务；transcripts 由 Worker 子图 Checkpoint 保留。contexts/工具句柄/模型客户端/连接重新构建，P5A 的分级算法不改。events 是脱敏审计，不承担调度或恢复权威。

固定官方 langgraph-checkpoint-postgres 3.2.0，与已锁定 LangGraph 1.2.16 / checkpoint 4.3.0 对齐；已审阅同版本官方源码。其 setup 使用 autocommit、dict_row、prepare_threshold=0，并含 CONCURRENTLY 索引迁移，不能塞入 Alembic 事务。

实际源码参考：已安装分发包的 `langgraph/checkpoint/postgres/{base.py,__init__.py,aio.py}`，检查 MIGRATIONS、setup、from_conn_string、aget_tuple/aput/aput_writes 的事务与 search_path 假设；LangGraph 原版子图继承与 sync durability 通过真实跨进程测试确认。仅调用公开 API，不复制官方迁移 SQL，不修改 site-packages；锁文件保存依赖分发哈希。

- 新 Alembic 0004 只管理 execution 内的领域元数据表；0001–0003 冻结。
- 官方 Saver 独占 checkpoints Schema 与 checkpoint_migrations 版本。专用 checkpoint_owner 在显式 runtime-init 命令执行官方 setup；请求/Worker 不调用 setup。
- runtime 角色只有 execution 和 checkpoints 必要 DML/USAGE，无 DDL/超级权限、业务表和上传表权限。MCP 不继承运行存储/迁移/模型凭据，业务读取仍走 MCP。元数据连接不属于模型工具。

## 恢复协议

thread_id 固定绑定 run_id、owner、目标哈希、策略/模型配置、可信源/指标/语义版本和授权范围。恢复先重新建立可信工具会话、检查版本/权限与 Artifact hash；不从 Checkpoint 自授予权限。禁止任意 checkpoint_id/time travel/覆盖图状态作为恢复入口。

官方 Saver 管外层与 Worker 子图状态；调用日志仅记录外部请求边界及去重结果，不实现第二个图调度器。稳定模型请求键绑定账户和压缩前完整消息/工具契约，避免重建冷却视图后重复摘要或付费；工具键绑定任务/版本/call ID 及参数哈希。已知完成结果可复用，冲突明确失败。原始工件完整保存后才生成模型视图，TTL/owner/容量/hash 均校验。

预算沿用 P4/P5A 算法，持久适配在 PostgreSQL 行锁事务中读改写。父子预留、issued 标记与请求绑定原子提交；结果与结算原子提交。重放已知结果不再扣预算；确定未发出的预留可以释放。已发出但结果/usage 未持久化时保守保留预留，标记 uncertain 并阻止自动重发，包括同进程 Replan 后的新请求；不声称供应商 exactly-once 或可撤销外部计费。每个父子账户与调用行/收据独立核对，供应商实际超额必须保留扣减且禁止恢复续跑。

全 Run 的 PostgreSQL session advisory lock 排除并发恢复，断进程后数据库自动释放；取消标志独立持久。重复恢复已完成线程只读回终态。正常 interrupt/resume 用官方 Command/interrupt；恢复值不是权限。只允许现有只读工具，拒绝引入写入/导入工具。PG 不可用时失败关闭，不靠重建内存预算继续请求。

## 验收与限制

真实 PG 跨 Python 进程恢复；模型发送前后、结果落库与 Checkpoint 间、工具工件与 Checkpoint 间故障；父子并发预算、幂等/冲突、取消、权限/版本/hash/TTL 反例。恢复重建时不序列化 Engine、会话、Key 或凭据。采用 Fake/HTTP Mock 决策进行大部分故障注入，真实 API 单独 opt-in。保留 P5A L4 负面费用结果，不优化算法；费用未知就记录未知，不编造扣费。
