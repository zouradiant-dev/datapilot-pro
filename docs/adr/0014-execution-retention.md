# ADR-014：运行保留、专用维护身份与整线程清理

默认不自动删除。仅独立 maintenance CLI 使用无 DDL 的专用身份，runtime/MCP/模型不得获得 DELETE 或维护工具；HTTP 没有清理端点。开发验证执行只在新建隔离数据库构造过期记录，不清理用户原库/Volume。

先 dry-run，显式确认精确 plan hash 后，重新检查 TTL、终态、无原 Run/dispatch 活动锁、无人工审核/保全、无 issued/uncertain 调用、无跨 Run 引用。任何条件变化、未知 Schema、无法读取/验证的状态均 fail-closed，不先删一部分。

已审计锁定的 langgraph-checkpoint-postgres 3.2.0：delete_thread 只按 thread_id 删除 checkpoints/checkpoint_blobs/checkpoint_writes；三表主键均含 thread_id 和 checkpoint_ns，Worker 子图同 thread、不同 namespace；checkpoint_migrations 为全局版本表，绝不删除。实现使用同一数据库事务中的等价精确 thread 删除，并与 execution 的账本/调用/工件/事件/Run 和 Web 绑定一致提交，禁止跨连接调用单独删除造成部分成功。

清理前再次核对官方迁移版本/表布局和最新 Checkpoint 指纹；原 advisory 锁保护并发。审计仅保留执行计划 hash、行数、时间与安全身份引用，不保留原 SQL/Prompt/文档正文。P3 Evidence/Verification、业务表、Dataset/向量来源及保全内容独立保留，不随 Run 删除；静态加密、生产保留周期和自动调度留 P10B。
