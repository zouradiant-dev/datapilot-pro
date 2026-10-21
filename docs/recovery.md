# P5B：持久执行与跨进程恢复

当前实现针对可信本地单用户，使用原版 LangGraph 1.2.16、checkpoint 4.3.0 和官方 `langgraph-checkpoint-postgres==3.2.0`。P5A 的 L0–L4/Memory 契约保留；没有新增调度器、源码 Fork、真实 RAG 或报告桥接。部署决策见 [ADR-009](adr/0009-durable-execution.md)，实际结果见 [P5B 交付](p5b-delivery.md)。

## 可恢复状态审计

| 状态 | 分类 | 保存与恢复来源 | 冲突/安全边界 |
|---|---|---|---|
| RunState 的 Plan/version、结果/验证、步骤/Replan、ready/pending、终态 | 权威执行状态 | 官方 Saver，thread_id 等于 run_id | 只恢复最新线程；不接受任意 checkpoint_id、update_state 或时间旅行 |
| Coordinator.plans / reused | 可重建缓存 | RunState.plan_history / reuse_origins | 重新检查任务身份、结果引用与原 Verifier；不把缓存当调度权威 |
| question、owner、配置/能力/版本绑定 | 权威身份 | execution.runs 的 manifest/hash；恢复时与可信宿主重新计算的清单比较 | 目标、scope、模型/预算策略变动拒绝；owner 从宿主提供 |
| Worker 原始 AI/Tool 消息及中间步骤 | 权威协议历史 | 继承父 Saver 的 Worker 子图 | 原始调用配对不删；provider 请求去重不依赖可变的压缩视图 |
| Coordinator.store / L0 原结果 / 上下文归档和摘要引用 | 权威工件 | execution.artifacts；按 run/task/version/id/hash 查取 | append-only；校验完整内容 SHA、owner、TTL、容量；模型读取仍经过原 ToolRegistry |
| Coordinator.ledger / pending / receipts | 权威预算 | execution.ledger；父子账户行锁事务；execution.calls 交叉核对 | 重复结算幂等，冲突失败；未知 usage 保留预留；已 issued 的 ticket 不可释放 |
| cancellation | 权威取消 | execution.runs.cancelled；新进程重新绑定事件 | 取消不因恢复而清零；在途请求按未知结果处理 |
| contexts / last_call / 工具 Registry | 可重建视图和句柄 | 当前宿主配置、原消息、持久工件；每次 Worker 重建 | 已完成模型响应优先按原始输入复用，避免冷却时间改变压缩后产生额外调用 |
| Engine/MCP 会话/客户端/Key/连接密码 | 敏感运行句柄 | 仅当前进程由本地环境重新构造 | 不序列化；模型与 MCP 不获得持久元数据/迁移凭据 |
| events / transcripts 导出包 | 脱敏审计 / 本地 Debug | execution.events / 子图消息或显式导出 | 事件不含 SQL/行/Prompt；Debug 与 Checkpoint 原文属于私密数据，不能公开提交 |
| 长期 Memory | 非执行权威 | 复用 P5A 的受审阅契约和内存实现 | 本阶段未实现永久 Memory 后端；不能代替 Registry 或从 Memory 恢复授权 |

完整工件和 Checkpoint 会包含私密任务/工具内容，部署者需保护 PostgreSQL 与备份访问。Serializer 禁用 pickle fallback，只允许本项目的有限 DTO 和框架原生消息/容器，拒绝任意运行句柄；不从模型输入接收序列化状态。

## 显式部署

已有数据库只做增量升级，不重新 Seed，不清理 Volume。在仓库根目录运行：

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked
uv run --locked python scripts/configure_local.py --add-runtime-roles
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot runtime-init
uv run --locked datapilot health
```

脚本仅给被忽略的 `.env` 添加两组独立随机凭据，保留原有配置。手工部署参考 `.env.example` 的 RUNTIME / CHECKPOINT_OWNER 字段；不要在聊天或 Git 中提供密码。首次空环境仍按 README 初始化并 Seed 一次。

- Alembic 新 `0004` 负责 execution 的 runs/ledger/artifacts/calls/events；0001–0003 不修改。
- 官方 Saver 的 checkpoints/checkpoint_blobs/checkpoint_writes/checkpoint_migrations 完全由官方 setup 管理。`runtime-init` 是显式运维入口，专用 checkpoint_owner 在 autocommit、dict_row、prepare_threshold=0 下执行官方迁移，包括 CONCURRENTLY 索引；不会放进 Alembic 事务。
- runtime 角色只有元数据所需的 USAGE/SELECT/INSERT/UPDATE，无 DELETE、Schema CREATE、角色继承、业务或上传权限。artifacts/events 仅 SELECT/INSERT，checkpoint_migrations 仅 SELECT。请求中从不运行 setup；缺失部署就失败。
- runtime-init 可以重复运行；凭据不进入模型工具。MCP Reader 不获得 Saver 写权限。元数据存储是明确独立的非模型基础设施通道，业务查询继续全部走 MCP。

Windows 的 psycopg 异步连接要求 SelectorEventLoop。CLI 已通过 `persistence.session.run_async` 处理；自行调用 Python API 时也需使用该入口或兼容事件循环，不能用默认 ProactorLoop。

## 跨进程 Demo

以下每一条 CLI 都是独立 Python 进程；Fake 只决定工具与 SQL，结果来自真实 MCP/PostgreSQL：

```powershell
$runId = [guid]::NewGuid().ToString()
uv run --locked datapilot durable start $runId --question '查询客户总数' --mode fake --pause-after worker
uv run --locked datapilot durable resume $runId --mode fake
uv run --locked datapilot durable resume $runId --mode fake
```

预期：第一条 paused，第二条 succeeded/completion.completed，客户数 240（未改变合成 Seed 的环境），第三条返回原终态。结果工件与预算不变，共两次 Fake 决策。普通 `ask` 保留原内存路径；只有显式 `durable` 使用持久执行。

```powershell
$reviewId = [guid]::NewGuid().ToString()
uv run --locked datapilot durable start $reviewId --question '查询客户总数' --mode fake --review
uv run --locked datapilot durable resume $reviewId --mode fake
uv run --locked datapilot durable resume $reviewId --mode fake --approve
uv run --locked datapilot durable cancel $reviewId
```

review 使用官方 interrupt/Command；未批准停留 awaiting_review，零模型调用。批准是可信 CLI 布尔值，不能来自模型摘要。持久取消后不允许再次执行。相同 run_id 同时恢复返回 RECOVERY_BUSY，不建立第二个调度器。

## 外部调用与预算协议

Checkpoint、供应商、MCP 与工件库不存在全局事务。图节点可能至少执行一次；本实现不承诺供应商 exactly-once 或账单退款。

1. 每次模型请求先把父子预留与 issued 调用原子写入，同一 Run 持有 PG session advisory lock。
2. 模型调用键由账户和**压缩前原始消息/工具契约**计算；压缩视图仍执行原 P5A 预算和校验。工具键绑定版本/任务/call_id 和参数 hash。重绑定 call_id 拒绝。
3. 完成响应与 usage/结算同一事务提交；返回结果后、图 Checkpoint 前崩溃时，从日志复用完成结果，不重发或二次扣减。工具 JSON 另存顺序保持的正文，避免 JSONB 键顺序使反馈变成不同输入。
4. 请求发出后结果未提交、取消/超时/PG 断连，标为 uncertain；模型预算保留原最大预留，usage_complete=false。未知工具结果同样阻止自动恢复，包括 MCP 传输错误；同进程 Replan 也不能继续发出新请求。即使操作只读，也不会假定它未执行后盲重试。
5. 恢复交叉核对每个父子账户的调用次数、已知 Token、保守扣减和结算收据；仅没有任何 issued 调用绑定的 follow-up 预留可以释放。相同结算重试幂等，参数冲突失败。
6. 主运行锁连接每次发出/提交外部调用前检查；PG 不可用失败关闭。锁恢复后仍须检查日志，不能重置内存预算续跑。不自动重试未知 API；已提交状态可由新的 CLI 进程再次恢复。

故障脚本只供宿主测试，不是模型工具：

```powershell
$faultId = [guid]::NewGuid().ToString()
uv run --locked python scripts/recovery_probe.py start $faultId --cut model_committed --occurrence 1
# 上条进程实际以 91 退出；下条应复用已提交响应。
uv run --locked python scripts/recovery_probe.py resume $faultId
```

cut 可选 model_issued/model_response/model_committed/tool_issued/tool_artifact/tool_committed。未确认窗口返回 RECOVERY_UNCERTAIN 并停止，需宿主对账；本阶段没有“清零预算并强行继续”接口。脚本拒绝同时指定 paid live 与 crash/long/parallel fixture。

## 恢复校验、配额与边界

- manifest 绑定 owner/原目标、模型与资源策略、能力、SaaS Schema hash、Reader 身份，以及可信 ContextScope / Dataset/source hash / Metric/Semantic 定义。忽略密码轮换但不忽略数据库位置/角色与业务授权变化。
- Dataset/Metric 在恢复前用新真实 MCP 会话重新查询；P3 verified ref 经原 Registry 只读校验。宿主须重新提供原 context_metadata，不能信任旧摘要自行恢复 scope；CLI 默认只有 SaaS 任务，没有上传数据自主 Agent 或 P3 报告桥接。
- 运行 TTL 默认一天、允许一分钟至七天；过期拒绝查询/恢复。每 Run 工件最多 96 个、16 MiB；持久事件最多 2048 条，原 Trace 的 1024 条限制仍生效。没有自动物理删除/清库；过期数据留待明确授权的后续运维保留方案。
- 上传版本由应用约束不可变；SaaS 可变表没有跨请求长事务快照。Schema/source pin 校验不等于冻结所有业务行；已提交结果原样保存，新查询读取当时的数据库。
- 单用户元数据角色具有跨 Run 的数据库 DML，owner/scope 检查在可信服务层；这不是生产租户 RLS 或防数据库管理员篡改的签名账本。
- 持久调用状态可确认后才复用；摘要、压缩、Memory 不会改变原始金额、证据或授权。P5A 历史性能与 L4 负面费用结果保留，未新增压缩算法优化。
- 记录供应商原 usage/cache 元数据、调用与过程耗时；没有账单不声明实际费用。安全字节估算、供应商 Token 和费用分开报告；缓存命中不能推导长期节省比例。

实现位置：`persistence/session.py`（官方图恢复与重授权）、`backend.py`（元数据/工件与原账本适配）、`journal.py`（外部调用边界）、`management.py`（显式部署）；`tests/test_recovery_postgres.py` / `test_recovery_versions.py` / `test_persistence_contracts.py` 为独立测试。

## P6A 兼容补充

P6A 新增显式 `rag_scope` / CLI `--rag-scope`，不改变普通 SaaS 的旧身份清单；新增 RAG DSN 不写入指纹或 Checkpoint。RAG scope、固定索引版本和经新 MCP 会话验证的 Dataset/source pin 进入持久身份；恢复仍需宿主重新提供匹配授权。原件/片段/hash 校验由 RAG MCP 和宿主 verifier 完成，再由原 Coordinator 在 Finish/Resume 复核。

真实 RAG 的暂停/新进程恢复、工具结果提交后崩溃重放沿用原 Journal；工具次数从原调用日志重建，完成响应不重复查询。`RAG_QUERY_TIMEOUT` 表示服务端已确认只读事务取消回滚，可以有界重试；未知 MCP 超时/断连仍为 uncertain，不能借此重新发出请求。详见 [P6A 链路与边界](rag-pipeline.md)。

### RAG 完成协议补强

`rag-submit-v1` 将原始宿主目标/相关性策略与完成协议绑定 manifest；缺少该协议的旧真实 RAG Run 明确 RECOVERY_IDENTITY，不修改历史记录或静默迁移。普通 SaaS 旧身份不变。真实 RAG Tools 节点在直接恢复时也从该 checkpoint 已闭合 ToolMessage 重建证据 grants，避免只在 Decide 重建导致提交重放失败。

收据必须对应同账户已提交模型响应 SHA、原生 submit_rag_result 的 call_id/参数，以及已提交工具日志。一次纠正在原 calls 中原子记账；相同触发重复返回原通知，第二次触发拒绝。提交已验证但未写入日志的故障窗口仍视为未知，禁止自动重发；已提交收据幂等恢复，不增加搜索、模型调用或扣减。仅接收检索完成，不将相关文本/哈希变成业务 verified。完整故障与语义边界见 [本轮交付](rag-completion-repair.md)。
