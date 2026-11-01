# DataPilot Pro 架构概览（可维护 Mermaid 源）

本页是面向 GitHub 读者与面试官的**当前实现**架构速览；详细设计、阶段边界与历史演进仍以 [architecture.md](architecture.md) 为准。两者冲突时，以源码、冻结验收记录和最新已验收证据为准。

阅读顺序建议：本页图 1 → 图 3 → [README 快速开始](../README.md#本地运行安全合成数据) → [一次可信证据链](showcase.md)。

> 图例：`实线` = 数据/调用流；`虚线` = 控制/审批/状态流；`子图分界` = 信任边界（身份与授权在边界处校验）。图中所有组件均在 `src/datapilot/` 中存在对应实现；未实现能力集中列在本页末节，不画进已实现链路。

## 图 1：系统总览（分层、数据流与控制流）

```mermaid
flowchart LR
  subgraph L1["交互层（已实现）"]
    UI["Streamlit Chat-first UI<br/>web/ui.py · ui_chat.py · ui_management.py"]
    API["FastAPI Host/API<br/>web/app.py · Session · Origin · CSRF"]
  end

  subgraph L2["可信宿主与授权（已实现）"]
    CONV["Conversation / Message 索引<br/>0007 · 有界私密元数据"]
    GOAL["Goal v4 有限范围确认<br/>reporting/contracts.py"]
    OUT["Web Outbox + 本地进程派发<br/>web/store.py · web/worker.py"]
    REV["Journal 执行审批<br/>interrupt review 节点"]
  end

  subgraph L3["编排 Runtime（已实现）"]
    COORD["LangGraph Coordinator<br/>planner · scheduler · verifier · replan · finish"]
    LOOP["Worker Loop 子图<br/>decide → tools → decide"]
    WK["SQL / RAG / Analysis / Report 任务"]
  end

  subgraph L4["工具与数据（已实现）"]
    MCPS["MCP SQL Gateway<br/>reader / upload_reader 会话"]
    MCPR["MCP RAG Gateway<br/>rag_reader 会话"]
    PG[("PostgreSQL 17 + pgvector<br/>saas · uploads · catalog · rag")]
    EX[("execution + 官方 Checkpoints<br/>runs · journal · ledger · artifacts")]
  end

  subgraph L5["模型边界（可替换）"]
    LIVE["Live Provider<br/>DeepSeek / openai_compatible"]
    FAKE["Fake / 脚本 Worker<br/>仅决策，不伪造业务结果"]
  end

  UI -->|HTTP only| API
  API --> CONV
  API --> GOAL
  API --> OUT
  OUT -.->|拉起独立 worker 进程| COORD
  COORD -.->|到达 review 节点时 await| REV
  REV -.->|批准后续跑| COORD
  COORD --> LOOP
  LOOP --> WK
  WK -->|仅经宿主 ToolRegistry 授权| MCPS
  WK -->|授权检索| MCPR
  MCPS --> PG
  MCPR --> PG
  COORD -.->|写入/读取 Checkpoint、Journal、Ledger| EX
  EX -.->|状态与用量投影| COORD
  GOAL -.->|Scope / Attestation| COORD
  LIVE -.->|模型决策| LOOP
  FAKE -.->|脚本决策| LOOP
```

要点：

- 模型不直连数据库；所有业务读取经独立 MCP 子进程，凭据按用途隔离（见 [图 4](#图-4信任边界持久化与恢复)）。
- UI 只通过 `/api/v1` 调用 Host，不导入 Runtime/MCP/Repository；`session_state`、`run_id`、客户端 owner 都不是授权。
- Conversation/Message 只是有界交互索引，不是 Checkpoint、Memory 或权限来源。

## 图 2：双环执行（外层 DAG 与内层 Worker Loop）

```mermaid
flowchart TD
  Q["可信 Host 绑定：owner · Dataset/version · MetricRequest · RagScope"] --> P["Planner<br/>fast intent 或异步模型 Plan"]
  P --> D{"Plan 校验<br/>唯一 ID · 无环 · 能力 · 数量"}
  D -->|非法| F["Finish：引用式确定性输出"]
  D -->|通过| S["Scheduler<br/>只派发就绪且已授权任务"]
  S -->|Send TaskEnvelope| W["Worker 子图<br/>模型多轮决策 + 工具反馈"]
  W --> V["Verifier<br/>identity → capability → evidence → shape → dependencies"]
  V -->|仍有就绪任务| S
  V -->|有界暂时性失败| R["Replan<br/>新 Plan 重新完整校验"]
  R --> V
  V -->|全部终态| F
  F --> C["CompletionDecision<br/>completed / incomplete / blocked"]
```

内层 Loop 的不变量（实现见 `orchestration/tools.py`、`orchestration/loop.py`）：

- 每条 assistant `tool_call` 必须有唯一匹配反馈，包括权限拒绝、异常、预算终止与取消；JSON 解析失败不允许退化为空参数。
- 工具契约、宿主能力、已绑定 MCP 句柄、取消、超时、输出校验、完整工件与 Trace 统一由 `ToolRegistry.invoke` 收敛。
- 模型最终只返回本次实际取得的工件引用；数值由 SQL/Decimal 计算，模型不参与心算。

## 图 3：一次可信分析端到端时序

```mermaid
sequenceDiagram
  autonumber
  actor U as 用户
  participant UI as Streamlit UI
  participant API as FastAPI Host
  participant CH as ChatService
  participant DB as PostgreSQL
  participant DP as Dispatcher
  participant DG as Durable Run
  participant CO as Coordinator
  participant MC as MCP Server
  participant P3 as P3 Registry

  U->>UI: 提问 / 上传合成文件
  UI->>API: POST /api/v1/conversations/.../messages
  API->>CH: 生成有界候选（规则/受限意图）
  CH->>DB: 追加 Message（不可变 payload + hash）
  CH-->>UI: 候选卡片 + 待确认合同
  U->>UI: 显式确认完整目标/有限范围/已解决前提
  UI->>API: POST .../launch（仅乐观前置条件）
  API->>CH: launch：事务内创建 Outbox Run 并关联 Message
  CH->>DB: 同事务写入 Run 引用
  DP->>DG: 拉起独立 worker 进程
  DG->>DG: Checkpoint 初始化 + Journal 记录
  DG-->>U: awaiting_review（零模型调用）
  U->>UI: 点击执行审批
  UI->>API: POST /api/v1/tasks/{id}/approve
  API->>DB: Journal 审批事件
  DG->>CO: 续跑原图
  CO->>CO: Planner → Scheduler → Send
  CO->>MC: 唯一允许的业务读取
  MC-->>CO: 结构化结果 + 引用 hash
  CO->>P3: 六层验证（安全/形状/语义/复算/引用/覆盖）
  P3-->>CO: Evidence / Verification ID + verdict
  CO->>CO: Report 独立重建 claims / 图表
  CO-->>DB: artifacts + ledger 结算 + 终态
  API-->>UI: 只读投影：报告 / 引用 / execution_status / business_completion
```

关键分离：

- **任务确认**（Goal v4 有限范围）与**执行审批**（Journal）是两个独立动作：确认不等于批准执行，批准也不扩大数据范围。
- **execution_status**（执行状态）与 **business_completion**（业务完成）分开；部分结果不能冒充完整分析。
- 报告只使用经 scoped MCP 重新读取并核对的 P3 verified 数值；文档引用另验原件/跨度/版本/hash，不把相关性写成因果。

## 图 4：信任边界、持久化与恢复

```mermaid
flowchart TB
  subgraph MODEL["模型可见（不可信输入源）"]
    LLM["Live / Fake 模型决策"]
    CALL["LLM Tool Call<br/>工具名 + 参数"]
  end

  subgraph HOST["可信宿主区（服务端）"]
    AUTH["Session · Owner · CSRF · Host/Origin"]
    SCOPE["RagScope · ReportScope · DatasetScope<br/>只由宿主绑定"]
    TR["ToolRegistry<br/>能力 / 参数 / 预算 / 取消校验"]
    POLICY["SQLPolicy 白名单 + SQLGlot AST"]
    VER["P3 六层 Verifier"]
    COMP["CompletionDecision"]
  end

  subgraph PROC["独立 MCP 子进程（最小只读凭据）"]
    SQLMCP["SQL MCP<br/>datapilot_reader / upload_reader"]
    RAGMCP["RAG MCP<br/>datapilot_rag_reader"]
    ING["Ingestion / Registry<br/>仅显式运维入口"]
  end

  subgraph DATA["PostgreSQL 17 + pgvector"]
    BIZ[("saas / uploads 业务表")]
    META[("catalog / rag 元数据与向量")]
    EXEC[("execution：runs · journal · ledger · artifacts")]
    CP[("官方 checkpoints")]
  end

  LLM -->|生成| CALL
  CALL -->|唯一工具入口| TR
  TR -.->|拒绝 / 参数错误 / 超预算反馈| LLM
  AUTH --> SCOPE --> TR
  TR --> POLICY
  POLICY -->|授权 SQL| SQLMCP
  TR -->|授权检索| RAGMCP
  SQLMCP -->|只读事务 + LIMIT/超时| BIZ
  RAGMCP -->|只读 + 精确 cosine| META
  ING -->|append-only 写入| META
  SQLMCP -.->|结果 hash| VER --> COMP
  EXEC <-->|issued / committed / uncertain| VER
  CP <-->|thread_id = run_id| COMP
```

模型不持有 MCP 地址、DSN 或可直接调用的工具句柄；它只能生成 `tool call`，由宿主 `ToolRegistry` 完成能力、参数、预算与取消校验后，才转成对独立 MCP 子进程的调用。**工具 Schema 展示不等于授权**，图中不存在模型到 MCP 的直达边。

持久化与恢复的三条硬规则（详见 [recovery.md](recovery.md)）：

1. 官方 Saver 独占 `checkpoints` 及其迁移；`runtime-init` 是显式运维入口，请求内从不 setup。
2. Journal 区分 `issued` / `committed` / `uncertain`；已发出但结果未知的调用保守计账并阻断自动重发，不假定外部操作未执行。
3. 恢复由可信宿主重新提供身份与 scope，并重查 Dataset/version、Metric/Semantic、source hash 与原 P3 verdict；摘要、Memory、Checkpoint 不能自授予权限。

## 模块对照（当前源码）

| 层 | 目录/模块 | 职责 | 边界 |
|---|---|---|---|
| 交互 | `web/ui.py`、`web/ui_chat.py`、`web/ui_management.py`、`web/ui_components.py` | Chat-first 工作台与管理页；只渲染 HTTP 结果 | 不导入 Runtime/MCP/Repository |
| Host/API | `web/app.py`、`web/chat_routes.py`、`web/body_limit.py` | 版本化 `/api/v1`；Host/Origin/Session/CSRF；请求体限制 | 只回环监听；无模型工具可调用的维护端点 |
| 会话与确认 | `web/chat.py`、`web/chat_contracts.py`、`web/goal_confirmation.py`、`web/intent.py` | 有界候选、Goal v4 确认事件、追问新 Run | 消息不存业务原始行/文档正文/Prompt |
| 派发 | `web/store.py`、`web/worker.py` | PG Outbox、幂等、宿主进程槽、看门狗 | 不实现第二套 Scheduler/Checkpoint |
| 编排 | `orchestration/coordinator.py`、`orchestration/loop.py`、`orchestration/contracts.py` | StateGraph、Send、Verifier、有界 Replan | 模型只产出 Plan 数据 |
| Worker | `agents/sql.py`、`orchestration/tools.py`、`reporting/adapter.py` | SQL/RAG/Analysis/Report 任务与工具注册表 | 能力最小化，空能力即空 |
| 工具网关 | `runtime/mcp_server.py`、`runtime/mcp_client.py`、`tools/sql.py` | 真实 MCP、AST、白名单、只读事务、配额 | 模型无 DSN、无 DDL、无文件/Shell 工具 |
| 指标 | `semantics/service.py`、`semantics/recipes.py`、`semantics/recompute.py`、`harness/metric_verification.py` | 封闭配方、独立复算、六层验证 | 不训练模型；不猜 MRR 或账单口径 |
| RAG | `rag/parsing.py`、`rag/models.py`、`rag/storage.py`、`rag/mcp.py` | 授权 TXT/MD、固定 BGE ONNX、pgvector 精确检索 | 不自动下载模型；不接受任意路径/URL |
| 报告 | `reporting/service.py`、`reporting/contracts.py`、`reporting/adapter.py` | MetricBridge、claims、图表、跨来源状态 | 只投影已验证证据 |
| 持久化 | `persistence/session.py`、`persistence/journal.py`、`persistence/backend.py`、`persistence/management.py` | 官方 Checkpoint、Journal、Ledger、Artifact | 元数据通道不向模型暴露 |
| 模型 | `llm/provider.py`、`llm/client.py`、`orchestration/model.py`、`llm/fake.py` | 异步 NativeTransport、profile 工厂、Fake 决策 | Fake 不返回业务结果 |
| 数据 | `db/schema.py`、`db/catalog.py`、`db/management.py`、`ingestion/service.py` | 固定结构与受限上传入库 | 上传 DDL 只由 ingest 服务执行 |

## 明确不存在的组件

以下能力未实现，不得在文档、演示或面试中描述为已有：

- 远程 Langfuse 集成（仅有默认关闭的本地 OTel 投影，且不含 Prompt/SQL/业务行）。
- HNSW/ANN 近似检索、独立向量服务（FAISS/Qdrant）；当前是同实例 pgvector 精确 cosine。
- 生产多租户、RLS、KMS、跨主机认证或生产级 SLA。
- DeepSeek 自主完成业务质量验收；Live Business Gate 仍为 PENDING。
- 主动 Agent、通用 Scheduler 或第二套恢复引擎、P11 缓存/降级引擎。
- Qwen3 Embedding 的 CUDA/生产切换验收；默认仍是 BGE 512/ONNX。
