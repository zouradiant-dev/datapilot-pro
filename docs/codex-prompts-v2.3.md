# DataPilot Pro v2.3：P6–P7 增强与 P10 生产化专项 Codex Prompt 包

> **状态基线**：2026-10-21，`zouradiant-dev/datapilot-pro` 的 `main`，提交 `cdccf28879b11841b9ffed6605a78050a88d8f70`（P5B 已交付；本稿不代表 P6/P7 已开发）。  
> **用途**：直接放入仓库 `docs/`，给 Codex **每次发送「通用前缀 + 仅一个阶段」**；不要一次执行整包，不自动 push/main。  
> **版本关系**：在 v2.2 基础上的独立新版；完整保留 P4.1、P5A、P5B 历史 Prompt 供审计，**现在从 P6A 开始执行**。P6A/P6B 不扩范围；重点强化 P6C/P7；增加与主线解耦的 P10 生产化专项。  
> **总体目标**：SaaS 经营分析主线；LangGraph 外层编排、Mini Claude Code **风格**内层 Worker Loop、MCP 强制授权、PG17 + pgvector、经确认的业务语义与可验证证据。可选干洗店 Domain Pack、Fork 和生产级多租户工程均不阻断 SaaS 原型主线。

## 0. 已核对状态与后续范围（不要让 Codex 从头造一遍）

本版以 GitHub 已提交的 P5B 代码为基线；开始任何新阶段前，Codex 仍须重新核对 HEAD/工作区，因为后续提交可能改变实际状态。以下“完成”表示**该阶段声明范围**已交付，并非生产 SLA 或商用认证。

| 模块 | 截至基线的实际状态 | 后续执行边界 |
|---|---|---|
| P1/P2 | CSV/XLSX 预览确认、受限入库、Dataset/version、真实 PostgreSQL/MCP | 不重做数据入口和权限；保护迁移与已有数据 |
| P3 | Metric/Semantic Registry、Evidence 与独立六层 Verifier | P6B 必须桥接 verified 结果，不能让 P4 Artifact 冒充 P3 Evidence |
| P4/P4.1 | LangGraph DAG/Send、独立 Worker Loop、工具生命周期、完成判定 | 禁止再造 Scheduler/ToolRegistry/Agent Loop |
| P5A | L0–L4 分级上下文、原消息与引用保全、经审阅的内存 Memory 协议 | 不为成本结果重写压缩规则；性能优化放 P7；长期 Memory 未完成 |
| DeepSeek | 明确的非思考 profile、真实 DeepSeek→MCP→PG 客户数 smoke、真实上下文 A/B | 不把受控回放等同于复杂自主 Agent 成功率 |
| **P5B** | **官方 PostgreSQL Saver、受限持久账本/工件、调用 Journal、跨进程恢复** | `datapilot durable` 显式路径已实现；普通 CLI `ask` 保留内存路径；不要再次开发 Checkpointer |
| P6A | 尚未交付真实 RAG | 文档摄取、Embedding、受限 pgvector 检索 |
| P6B | 尚未交付可信多来源分析报告 | 跨 P3/P4 证据桥接与业务正确性 |
| P6C | 尚未交付 FastAPI/Streamlit/Langfuse | Web/API 默认走 Durable；基础隐私、安全、受控数据保留 |
| P7 | 尚未交付独立业务评测 | ≥50 任务、完整模型/故障/成本/压缩评测 |
| P10 | 尚未交付生产化专项 | 企业多租户 RLS、加密备份/运维；长期 Memory 为可选专项 |

- 最新已核对 P5B 主线提交：`cdccf28879b11841b9ffed6605a78050a88d8f70`。其 Actions 在 Python 3.11 与 3.13 均 **423 passed、1 skipped**，Ruff 通过；live 为独立 opt-in 实验，**不属于 CI 默认自动运行**。相关记录：`docs/p5b-delivery.md`、`docs/recovery.md`、`docs/adr/0009-durable-execution.md`。
- **Gate C 还缺 P6A + P6B**；Gate D 还缺 P6C + P7。无需为了 P5A 的 L4 费用负收益暂停业务主线。
- **设计目标边界**：先完成可验证的**本地可信单用户 SaaS 原型**；生产多租户/公网暴露、企业备份加密与审计须单独验收。不得把 local demo 命名为生产级 SaaS。

### 六项遗留问题的明确归属

| 遗留问题 | 必须解决的阶段 / 交付边界 | 是否原型 Gate D 阻塞 |
|---|---|---|
| Web/API 普通分析任务默认持久执行 | **P6C**：API/UI 走 P5B Durable，含刷新/进程重启/重复请求 | 是 |
| Checkpoint/Artifact 含私密数据 | **P6C**：本地权限、脱敏与不公开原始存储；**P10B**：生产静态/备份加密与密钥策略 | 基础保护是；生产加密不是 |
| TTL 过期记录未物理清理 | **P6C**：受控保留/清理运维入口、dry-run、独立维护身份、测试；**P10B**：自动化生命周期与审计 | 安全方案和本地可验证维护流程是；无人值守生产化不是 |
| 真正的租户级 RLS | **P10A**：认证、可信 tenant 传播、跨层隔离、RLS | 否，但对多客户公网商用是 |
| PG 重启 / DeepSeek 故障覆盖不充分 | **P7**：专门隔离的真实 PG 重启、供应商 HTTP 故障和恢复矩阵 | 是，按评测阶段范围 |
| 永久长期 Memory 仍为内存 | **P10C 可选**：受审阅、版本/TTL/撤回的持久提示库 | 否，业务定义由 P3 Registry 权威管理 |

### 核心源码与研究参考

- 当前代码：[P4 交付](https://github.com/zouradiant-dev/datapilot-pro/blob/main/docs/p4-delivery.md) · [P4 编排](https://github.com/zouradiant-dev/datapilot-pro/blob/main/docs/orchestration.md) · [ADR-006](https://github.com/zouradiant-dev/datapilot-pro/blob/main/docs/adr/0006-two-level-orchestration.md) · [Roadmap](https://github.com/zouradiant-dev/datapilot-pro/blob/main/docs/roadmap-v2.md)
- 对照参考：[How Claude Code Works](https://github.com/Windy3f3f3f3f/how-claude-code-works)；重点为 `docs/03-context-engineering.md`、`04-tool-system.md`、`06-hooks-extensibility.md`、`08-memory-system.md`、`09-skills-system.md`、`15-task-system.md`、`16-observability.md`、`19-dynamic-workflows.md`、`20-agent-teams.md`。
- 可运行教学参考：[Claude Code From Scratch](https://github.com/Windy3f3f3f3f/claude-code-from-scratch)；重点为 Python `mini_claude/{agent,tools,subagent,memory,skills,autonomy}.py`、`test/integration/*`、`docs/07-context.md`。
- 这些是**非官方教育研究项目**。后期对 Claude Code 的内部实现部分属黑盒观察/推断；仅借鉴经验证的机制，不将推测写成官方事实，不直接复制非必要代码/泄露材料；确需复用 MIT 源码时保留 License、版权和来源记录。

---

## 1. 所有阶段通用的 Codex「执行协议」（每次附在阶段 Prompt 前）

以下是**通用前缀**，每次执行 P6A、P6B、P6C、P7、P8、P9 或 P10A/B/C 时先附加（P4.1–P5B 历史段无需再发），或要求 Codex 严格执行：

```text
你是 DataPilot Pro 项目的高级 Agent Runtime / SaaS 数据分析系统工程师。
当前工作目录必须是仓库 zouradiant-dev/datapilot-pro；先检查 git status、分支、HEAD、现有本地未提交修改，再读取 README.md、AGENTS.md、docs/roadmap-v2.md、docs/architecture.md、docs/orchestration.md、docs/p5b-delivery.md、docs/recovery.md、docs/adr/0006-two-level-orchestration.md、docs/adr/0008-context-authority-memory.md、docs/adr/0009-durable-execution.md 和当前阶段相关源码/测试。

绝对遵循：
1. 只实施本次明确批准的阶段范围；一次任务到验收边界即停止，不自动进入下一阶段。先给出差距核查：已有/缺失/重复风险/拟修改文件，再动手实现。
2. 保护 P1–P5B：PG17+pgvector、真实 MCP SDK、SQLGlot AST、安全角色、只读事务、独立 Ingest、DatasetScope、Semantic/Metric 版本、六层业务 Verifier、TaskEnvelope/ToolRegistry/Send/Command/预算/取消等现有实现。不得为统一接口弱化验证。
3. 不能以增加第二个 Scheduler、第二个 Checkpointer、自制 LangGraph 运行时、无限通用 Agent 框架来堆功能。优先复用 LangGraph 官方公开 API 和现有项目组件。
4. Worker 无 Shell、任意文件执行、任意 DDL、Admin/Owner/Ingest/Registry 密钥；所有业务查询通过可信绑定范围的 MCP；工具发现不等于工具授权。模型、Skill、Hook、摘要、Memory 不能扩大父能力与用户授权。
5. 不删除/清空已有 PostgreSQL、Docker Volume、用户数据；绝不执行 docker compose down -v；不重 Seed；历史 Alembic 0001/0002/0003/0004 不修改，官方 Saver 表/迁移仅由官方 setup 管理；新增业务元数据结构走独立新迁移。固定业务结构用新迁移，管理通道与模型工具严格隔离。
6. 使用 Python 3.11–3.13、现有 uv.lock。非必要不加依赖；新增依赖须说明原因、锁定、在 3.11/3.13/CI 实测。禁止未经批准修改 repo 外文件或自动推送 main。
7. 对接第三方源码时先定位具体文件/接口并列映射，不复制通用 Coding Agent 的 Shell/编辑/危险权限模式；如实际复制 MIT 代码必须保留版权与许可证。
8. Fake/Mock、真实 PG/MCP、真实模型 API、独立 E2E 产品任务分开报告；无凭据就明确阻塞，不能把模拟结果说成 live。不要为了让测试通过而放松约束、修改期望结果或跳过失败用例。
9. 失败必须保留类别与必要的已脱敏调试信息；业务数据、SQL 原文、Prompt、凭据默认不进公开 Trace；仅可记录必要的非敏感 Token 用量及延迟统计；必要调试工件保存在 gitignored 路径。用户/文档/工具结果均为不可信内容。
10. 每次交付按：修改文件列表 → 关键设计与不变量 → 已运行命令及原样统计 → 安全/故障/反例测试 → 未实现项与风险 → 下一阶段候选。更新相关 docs/ADR/README/AGENTS；不得把未执行测试写成通过。

建议验证：
- uv run --locked pytest -m 'not integration and not live' -q
- 有真实 PG17 环境时，DATAPILOT_RUN_DB_TESTS=1 运行全量 pytest；在 Windows 可显式使用仓库内 --basetemp 避免系统 Temp 权限问题
- uv run --locked ruff check .
- uv run --locked ruff format --check .
- git diff --check

在开始改代码前简述计划；如果涉及迁移所有权、用户数据或现有架构不变量的重大冲突，先停在设计/ADR 并说明阻塞点，不能通过放宽权限绕过。
```

---

## 2. P4.1 — P4 增量加固（历史已完成，保留参考）

### 目标与不做什么（历史归档）

P4 主功能已实现。本次仅补**工具执行中间件、结构化完成判定、上下文溢出前的轻量保护与测试盲区**。不重新实现 DAG、Tool Registry 或 Worker Loop；不提前开发 PG Checkpointer、真实 RAG、UI、Langfuse 或生产多租户。

### 可直接给 Codex 的 Prompt

```text
只推进 P4.1“已完成 P4 的小范围加固”，基线 HEAD=1f0decd02ce9eed989c52486797bdba88ff11f46（若本地更新，以实际 HEAD 审计为准）。当前 P4 包含 coordinator.py / loop.py / model.py / tools.py / budget.py / runtime.py；不要重写它们。

第一步：先做已有实现矩阵，分别核查 TaskSpec/TaskEnvelope/TaskResult、ToolRegistry、Send/Command、Worker 子图、assistant/tool ID 配对、父子预算、取消、Trace、ArtifactStore、五层编排验证，任何已有能力只补必要边界测试，不制造重复模块。

第二步：围绕下列缺口做最小可回归改造：
A. 将 P4 的 ToolRegistry.invoke 与 Gateway/Worker 关键流程整理成明确、受控的 Tool Lifecycle 接口：输入契约 → 宿主能力/可信 DatasetScope 判定 → 预算/取消/超时 → 真实工具调用 → 输出契约 → Artifact/Trace。只增加必须的共享前后置钩子，不允许用户/Skill/外部 Hook 绕过拒绝、提权或修改授权；已有正确流程不要为了形式重写。区分工具失败、权限拒绝、取消、超时，trace 记录脱敏 reason_code。
B. 增加宿主侧任务完成判定（Goal Completion Gate）原型，不是一个会自我宣称成功的 LLM。必须以 DAG 全部必需任务终态、五层任务验证、实际 Artifact 引用和 P3 的 verified Evidence 要求（在涉及业务指标时）为条件。三态 completed / incomplete / blocked；缺证据和不可计算可产出真实受限报告而不是假成功。不得让 evaluator 绕过失败或自动无限续跑。
C. Context 基础：在 Gateway 调模型前统计当前消息、工具 Schema、输出预留、估算 Token 和可裁剪体积；增加“工具输出先保存完整 Artifact，再向模型发送受限摘要/引用”的 L0 路径，不能先截断再持久化。可选实现 L1 旧非权威工具结果裁剪、L2 重复相同工件引用去重；保留原始 AIMessage/ToolMessage 结构与 tool_call_id 对齐；任何不可安全裁剪的消息仍明确 CONTEXT_LIMIT，不可隐式截断安全规则或真实证据。若 L0–L2 会显著改 P5 状态设计，只在本阶段产出 ADR/接口和针对性测试，不强行完成。
D. 并发与故障：测试批量调用中某一 tool 被拒、其余 call ID 有明确未执行反馈；未知 usage、重复预算结算、取消、恶意 Tool 输出、错误类别与重规划所有权；同一 run 的 Trace 顺序和不同 Worker 的上下文不能互相污染。任何新限制要证明不影响原 P4 简单 SQL fast path。

验收与交付：
- 现有 P0–P4 全量回归继续通过；新增反例/故障测试必须具有独立意义。
- 人为变异一次关键权限检查或引用校验时，相关测试应失败（mutation smoke），再恢复代码；不能仅凭“tests green”证明验证有效。
- 如果实际增加 Hook，提供安全顺序与拒绝不可覆盖测试，且不将 Hook 用户脚本注册为模型可执行工具。
- 更新 docs/orchestration.md、docs/adr/ 中必要的增量 ADR、docs/p4-hardening.md 与运行实测；README 只增补真实状态。
- 本轮停止在 P4.1，不实现 P5 持久记忆、Saver、实际 RAG、报告/UI；不要提前宣布 Gate C 完成。
```

### P4.1 特别注意的已有事实

- `tools.py` 已经有 `ToolRegistry`，不能让 Codex 再生成第二份通用 Registry。
- 当前 `runtime.py` 的 `ArtifactStore` 是**内存工件容器**。可先做“先保存完整结果、再裁剪模型视图”的同一 Run 保护，但跨重启保留在 P5。
- P3 的 `metric_verification.py` 是**六层业务验证**，P4 `coordinator.verify` 是**五层编排契约验证**。两者不应合并成只有一个布尔 `verified` 的伪接口。
- ToolSearch 延迟发现目前收益有限；只在工具数量/Token 观测显示明显开销后再实现，且 discovery 与 capability 强制授权必须分离。

---

## 3. P5A — Context Engineering / Compression / Memory 基础（历史已完成）

### 原 P5 Prompt 需要怎么变

原来 P5 一口气写“Context、Memory、Checkpoint、Recovery”，容易把数据清理、摘要、KV 缓存、长期记忆和 Saver 混成一个大改动。现在建议**先把上下文分级与权威状态边界做扎实**，再发 P5B 的持久化 Prompt。

**分级策略**：L0 大工具结果先外存、后生成模型视图；L1 裁剪旧结果；L2 哈希去重；L3 折叠已完成子任务为结构化 ArtifactRefs；L4 有预算的模型摘要兜底。触发阈值先配置化并以真实 Token/延迟/正确性数据调参；不可把实验阈值当通用规律。

### 可直接给 Codex 的 Prompt

```text
只推进 P5A：ContextManager + 分级压缩 + 记忆契约；前提：当前 P4/P4.1 已通过回归。本轮不实现 PostgreSQL Checkpointer/重启恢复，不接真实 RAG/UI。

阅读：src/datapilot/orchestration/{loop,model,runtime,budget,contracts,coordinator}.py、src/datapilot/semantics/{recipes,contracts,service}.py、docs/orchestration.md、ADR-006；参考 how-claude-code-works 的上下文/记忆章节，以及 claude-code-from-scratch 的 docs/07-context.md、Python agent.py/memory.py。只独立借鉴设计。

1. 先定义权威状态与可压缩上下文的类型边界：
   - 不得丢失：当前用户目标及约束、可信 Dataset/version/Metric/Semantic 版本、授权 scope、任务依赖/未完成状态、P3 verified Evidence 与 P4 Artifact 引用、模型/工具调用关联、预算与取消语义。
   - 可压缩：过时工具输出、重复 Schema 展示、重复检索文本、已完成 Worker 非权威中间反馈。
   - 摘要/Memory 不得重新授予权限，不得改变原始 SQL 结果、货币单位、时间窗口、指标口径或 verified verdict。
2. 复用现有 Gateway（统一模型与预算入口）实现 ContextManager 适配；所有“供模型看的视图”与“可恢复完整工件”分开，最大输入先预算预留；L0 先完整存入有界 ArtifactStore 后返回预览和 ref，不静默丢行/证据；跨进程外存留到 P5B。
3. 逐层实现 L1/L2/L3；L4 只有在前三级仍不足、剩余预算充足时才调用受限 Summarizer，并记录它的模型用量。摘要必须输出结构化 Schema，保留 goals、constraints、unresolved、decisions、evidence_refs、dataset/metric versions；无法验证则拒绝摘要并退回明确上下文上限错误。
4. 保护每条 assistant/tool 调用与结果的 provider 协议：不允许删掉或改配对信息导致孤儿 tool_call；被折叠的历史保留可读取的完整 Artifact ref。压缩后自动再注入当前任务、关键业务定义、最近活跃证据引用，不模仿“恢复最近 5 个代码文件”。
5. 将长期 Memory 与 Execution Checkpoint 分离：Memory 仅保存可复用偏好/已审查的业务术语提示/决策线索及来源，不复制整个 Dataset/Metric Registry，不保存原始业务行或凭据；对 memory 设置 created_at、source_ref、source_version、scope、validity、invalidation，并在读取时校验新鲜度。真正的持久 Memory 存储/恢复可以留到 P5B，但接口必须明确。
6. Prompt 组装采用静态 Worker 约束 + 动态任务上下文 + 已验证工具引用的分层结构；检查 Prefix Cache 是否由当前供应商支持，未实测不要承诺节省费用。根据任务能力裁剪工具 Schema，禁止让“隐藏工具”成为权限机制。

新增测试：
- 10+ 轮工具反馈/超大工具输出/重复 Schema/冷却上下文/断档摘要/错误引用；相同任务压缩前后结果与 Evidence 引用一致。
- 触发压缩但不删除未结算 tool call；不损失安全 Prompt 或目标约束；多 Agent 上下文不串扰；摘要中冒充权限/版本/verified 的内容拒绝。
- 输出成本/Token 输入规模/压缩次数/是否发生不可逆信息损失/额外摘要成本，采用 Mock 与必要的真实 API 实验分别报告。

交付 docs/context-engineering.md、可测的 L0–L4 策略与测试、上下文不变量和风险。不得为达到压缩率而牺牲业务验证。停在 P5A。
```

---

## 4. P5B — Durable PG Checkpoint / Budget / Recovery（历史已完成）

### 当时的核心缺口（现由 P5B 解决）

P4 `Coordinator` 的 `self.plans`、`self.store`、`self.transcripts`、`self.reused`、`self.ledger` 和取消状态中有大量**进程内权威或运行中状态**。即使给 `StateGraph.compile()` 传入 PostgresSaver，也不能自动推断这些对象如何在另一个进程中重建。**P5 必须明确重构状态边界和恢复协议**，而不是“安装 Saver 就算完成”。

### 可直接给 Codex 的 Prompt

```text
只推进 P5B：真实 PostgreSQL 持久 Checkpointer、可恢复的 Budget/Artifact/Ledger、Interrupt/Resume 与故障测试。前提：P5A 审批通过；不实现真实 RAG/UI/多租户。

开始前进行“可恢复状态审计”：列出 RunState 和 Coordinator 实例上的 plans/store/transcripts/reused/ledger/cancellation/events 等字段；将各字段分类为权威状态、可重建缓存、敏感运行句柄或仅 Debug 信息。对每个权威字段给出持久存储与恢复来源、幂等/冲突策略，明确不序列化 SQLAlchemy Engine、MCP 连接、模型 API Key、Token 或凭据。

A. 先提交 Checkpoint 迁移 ADR（先解释，再编码）：官方 LangGraph PostgresSaver 与 Alembic 历史迁移谁拥有 Schema/版本；在独立的执行元数据命名空间及受限角色上显式部署初始化。不得在每个 request/Worker 内调用 Saver.setup() 隐式 DDL；不得修改 0001/0002/0003，不能让 MCP Reader 拥有 Saver 写权限。校验 LangGraph 当前锁定版本和 PG Saver 的实际版本兼容、事务/并发/官方 Setup 要求。
B. 以 LangGraph 官方 Checkpointer + thread_id/run_id 恢复为唯一外层状态机器；避免平行自建调度或重放框架。让 Plan/version/task results/verifications/ready-pending、重要 Artifact 引用、摘要引用等可恢复，恢复时按可信宿主重新建立工具/数据库连接与 capability，不从 Checkpoint 内容自授予权限。
C. 设计受限持久 ArtifactStore 和预算 Ledger：按 run/task/version/id/hash 检索，有 TTL、存储上限与 owner；父子 reserve/settle 必须并发原子、重复事件幂等。崩溃时未结算的模型 API 请求 conservatively charged / unknown_usage，不得恢复为 0，也不能重复扣费或借重试超限。
D. Checkpoint、模型外部请求、MCP 查询、Artifact 写入不具备天然单一全局事务。明确 at-least-once 执行语义与幂等键、恢复边界；只可重放经过证明安全的只读查询或可幂等工件操作。对不可确认完成的外部调用标记 uncertain，不虚构 exactly-once。重启后检查 Dataset、Semantic、Metric、source hash/scope 是否变化，变更后需拒绝或重新确认而非继续旧上下文。
E. 支持正常 interrupt、进程被杀、部分 Worker 已完、重复恢复、并行分支一成一败、取消后重启、等待用户确认、PG 断连重试。安全/预算拒绝不进入无限 Replan；最大重试/超时按单层负责人执行。
F. Trace 提供恢复/重放的相关 ID 与脱敏事件，不泄露业务行、SQL 或私密 Prompt；持久会话信息与长期 Memory 分离。可在持久层实现已审查 Memory 的可靠存储和基于 scope/version 的按需召回，仍不得覆盖 P3 Registry。

必须真实验证：
1) PG17+pgvector 上固定 thread_id 首次执行→持久化→关闭进程→新 Python 进程恢复，最终目标/证据/预算一致。
2) 在模型调用已经发出但未 settle、工具结果写入与 checkpoint 之间等多个 cut-point 模拟 crash，不能双计、不能不计或伪称已完成。
3) 多 Worker 并发账本、冲突 reducer、重复恢复、版本不一致、越权 scope、意外重跑写入均有反例测试。
4) 对照现有 P4 无持久实现，列出新增资源/延迟；Mock、真 PG/Fake、真实模型分别标注。

交付迁移 ADR、独立部署说明、可复现 cross-process demo、docs/recovery.md、故障测试与真实结果。只有重启恢复通过才宣称 P5 通过；停止在 P5，不做 P6。
```

---

## 5. P6A — 真实 RAG（替换 P4 组件 fixture，不重做 Worker Loop）

### 可直接给 Codex 的 Prompt

```text
只推进 P6A：在 P4 已存在的 RAG Worker/ToolRegistry/MCP 接口下落地真实文档摄取、Embedding、PG17+pgvector 检索。前提是 P5B 持久恢复完成；先阅读 docs/recovery.md，保持原 Durable/MCP/Artifact 引用边界。不实现 UI、完整报告或生产多租户。

先审计现有 RetrievalTools/Document/SearchResult、orchestration/loop.py、tools.py、P2 DatasetScope、安全 MCP Server/Client、P3 Evidence。原 RAG fixture 只能作为回归，必须新增真实检索端到端数据流：经用户授权的来源文件→有界解析/切块→可信基础设施写入 pgvector→受限 reader 检索 MCP→RAG Worker 获取带版本引用的候选文本→可信验证。仅对用户授权的数据集/文档摄取和检索；文档正文与向量不得泄露到公开 Trace。

1. 用现有 PostgreSQL 17 同实例 pgvector，固定 embedding model 名称、维度、版本、chunker 配置、source/document/chunk ID、hash、span/页码/行号和索引版本；索引重建与旧版保留要明确。先用合成小文档/本地向量测试；Embedding 凭据缺失时不得冒充真模型。
2. RAG 文档授权与数据集 scope 从可信宿主绑定，不接受模型参数扩权。禁止用返回的文档文本、模型幻觉或摘要作为权限来源；导入/更新仅走受限可信服务，MCP 查询只有只读工具。SQL Worker 不获得 RAG 私有凭据，RAG Worker 不获得 SQL 查询句柄。
3. 文档摄取要限制源格式、字节、数量、解析时间、chunk 长度；宏、外部 URL/脚本/恶意文档指令不得执行。明确是否支持 PDF/HTML 并选择必要依赖，不新增无法验收的万能解析器。
4. 检索返回必须可追溯：source_id、version、chunk_id、offset/页码、hash、检索器版本、可解释的 top_k 与 score。单纯近似召回分数不是证据真实性；空检索与越权明确 unavailable，不捏造引用。
5. 保持 P4 既有 Agent Loop、工具 ID、预算/取消/超时与上下文裁剪；上下文只注入授权片段的必要摘要/引用。模型出错后仅允许受限重检索，不新增无限 ToolLoop。

验收：真实 PG+pgvector 的多文档同义问答、精确源定位、更新版本、空召回、跨数据集越权拒绝、恶意 Prompt Injection 文档与可恢复超时；相同查询能从原件定位 chunk/hash。禁止把 fixture 测试说成真实 RAG。输出 docs/rag-pipeline.md 和真 PG 测试、停止在 P6A。
```

---

## 6. P6B — 可信跨来源 Analysis / Report（连接 P3 与 P4）

### 核心新增验收

P4 引用包与 P3 `Evidence/VerificationRecord` 现在是两种不同对象。P6B 必须建立**显式桥接契约**：Report 读取和验证 P3 已确认指标结果，再结合 P6A 可追溯文档片段；不能把 P4 五层通过当作指标六层通过。

### 可直接给 Codex 的 Prompt

```text
只推进 P6B：跨来源可验证的 SaaS 分析与报告 Agent；前提 P6A 真实 RAG + P5B 恢复链已验收，不实现 UI/Langfuse；同时验证跨节点持久工件/引用恢复不改变 P3 Verified 状态。

先绘制两条实际链路：P3 semantics service → MetricExecution → persisted Evidence/Verification；P4 Coordinator → TaskResult/Artifact/EvidenceRef → deterministic report。定义最小桥接 DTO/adapter，不丢 dataset/version/semantic/metric/source hash、时间窗口、金额单位与 verification verdict。

1. 用户自然语言目标经可信 Planner 生成有界 Task DAG，但模型不能私自确认字段或业务指标、不能生成任意指标脚本/SQL 绕过 P3 受审查配方；缺映射/单位/业务口径先要求确认或 unavailable。
2. SQL 数字经受控计算和 P3 六层规则或等价已审查业务 Verifier，Report 只发布真实 verified 的数字；P4 五层编排检查保证任务身份、依赖与权限，不替代六层业务检验。拒绝将 raw Evidence、普通查询结果、未核实图表当作 verified metric。
3. RAG 文档引用与 SQL 指标须分别验证对应的 source/version/hash，跨来源 claim 要求两类引用正确对应；描述性相关性不等于因果结论。缺证据时只补缺失的就绪任务，不能不断全量 Replan。
4. Analysis Agent 使用受控 deterministic SQL/Decimal/统计工具；LLM 可解释但不凭空心算数字。Report 产生结构化 claim + 对应 evidence/verification IDs + 可显示 Markdown/图表规格，图表数据的单位/日期/来源必须可审计。
5. 设置完成判定：必需 goals 覆盖、引用有效、指标验证已通过，或明确给出 unavailable/blocked。任何确认或审批应停在可信 UI/宿主决策，模型不得自批准。
6. 保留小问题快速单 SQL 路径，不用无必要 DAG 消耗高额 token；复杂 SQL + 文档问题执行真实 MCP 查询和真实检索，输出对应 Trace 与案例。

验收：至少 5 个独立业务案例，覆盖收入、流失、使用量、跨来源解释、缺失数据/过度因果/错误来源；对抗注入、错误单位、错误版本、伪造 Evidence、非匹配文档引用均不得出 verified 报告。与现有 P3 Gold 独立对照；给出真实 PG+真实检索测试与额外真实模型（若有授权）的统计，不用 Fake 冒充。输出 docs/cross-source-report.md、真实结果，并停止在 P6B。
```

---

## 7. P6C — FastAPI / Streamlit / Langfuse、默认持久执行与基础数据生命周期

### 本版变更（相对 v2.2）

此阶段的新增要求是**产品入口默认 Durable**、保密边界和**保守的数据保留/清理运维能力**，但仍定位为“可信本地单用户 Demo”，**不提前实现生产多租户/RLS**。注意普通 CLI `ask` 可继续保留历史内存模式；不能因此认为 API/UI 的任务也可以默默使用内存路径。

### 可直接给 Codex 的 Prompt

```text
本次只授权 P6C：在已验收 P1–P6B 基础上实现可运行的可信本地单用户 SaaS Demo（FastAPI + Streamlit + 可选 Langfuse/OTel），并完成 Web/API 默认 Durable、数据访问保护和最小可操作的保留/清理方案。本次禁止 P7 Benchmark 调优、P8 Fork、P9 干洗店、多租户生产认证/RLS 及 P10 生产级加固。

【预检】
1. 核对 git status/HEAD、AGENTS、docs/codex-prompts-v2.3*（若已加入仓库）、docs/recovery.md、docs/p5b-delivery.md、docs/rag-pipeline.md、docs/cross-source-report.md；确认 P6A/B 实际通过才开始。审阅 cli.py、persistence/session.py、persistence/{backend,journal,management}.py、orchestration/coordinator.py、P3 Registry/Verifier 及官方 Saver 版本。列出复用接口和拟新增文件，禁止第二套任务调度/恢复框架。
2. 明确可信部署模型：默认 127.0.0.1 本地单用户，浏览器入口不是授权来源；所有 owner、DatasetScope、Metric/Schema 确认与危险管理操作由宿主建立/检查。禁止以可伪造的 run_id 或客户端提交的 owner/token 直接越权读取别人的任务。不可宣称生产公网多租户安全。

【必须实现】
A. 最薄 FastAPI：受限上传/预览/确认/入库、Dataset/version 选择、可信语义与指标确认、创建任务、查询真实进度、展示经过权限和 Evidence 校验的报告、按可信请求执行 review/approve、取消和恢复。定义稳定的 request/response、错误码和 TaskStatus DTO，不把原始管理 DSN、全量 Checkpoint、Artifact JSON、模型 Prompt 或私密行数据直接返回浏览器。
B. **API/UI 发起的每个正常经营分析任务默认调用 P5B `run_durable`（官方 LangGraph PG Saver 路径）**，而不是普通内存 `ask`。从现有真实进度/Checkpoint 映射 UI 状态：pending/running/paused/awaiting_review/partial/unavailable/blocked/failed/completed/cancelled（用实际合同支持的精确枚举）。刷新页面、浏览器断开、API 进程重启后以授权 run_id 恢复进度；未确认外部调用遇 RECOVERY_UNCERTAIN 明示待人工对账，不能强行重发。保留旧 CLI `ask --mode fake/live` 作为显式无持久兼容入口，不必修改其默认行为。
C. POST/create/resume/approve/cancel 使用宿主绑定 idempotency key、run_id、请求体哈希与身份。相同键+相同操作重复提交复用结果；相同键+不同目标/owner/权限/载荷必须拒绝。并发不能双开同一 run；API Worker 的关闭/取消不能将已完成任务回退为 running。不能把未经监管的 FastAPI BackgroundTasks 当成跨进程可靠调度器；如使用本地后台执行器，必须有有界并发、重启恢复和状态一致性测试，尽量直接复用已实现 P5B 生命周期。
D. Streamlit 展示真正的 upload/preview/confirm/metric-policy/analysis/report/review 流程；Pending 与 Awaiting Review 不是已成功完成，succeeded execution 与 completed business goal 区分。错误要显示安全原因和可重试/需人工处理提示，禁止伪造“任务已完成”动画。高风险确认由可信 UI/宿主执行，模型不得自批准。
E. Langfuse/OTel：统一 run_id、plan_version、task_id、tool_call_id、model_call、Artifact/P3 Evidence 的脱敏关联及真实 latency/usage/cache 命中统计；费用仅在价格来源/实际 usage 可信时标注估算，并与账单成本分开。默认绝不公开记录明文客户行、原 SQL、Prompt、文档正文、API Key/DSN、持久状态原文；明确如何禁用远程遥测/限制本地导出。遥测失败不能造成主任务失败或提升权限。
F. 私密数据与边界：明确 Data Map（上传原件、数据表、P3 Evidence、P4 Artifact、PG Checkpoint/Blobs、Langfuse、日志、前端缓存）和存储/访问主体。对任意 run_id 和任意 EvidenceRef 做宿主 owner/scope/版本校验；未授权/过期/变更返回拒绝。即使是单用户 Demo，也要有安全反例，不把公开文件 URL/错误回溯泄露内部内容。PostgreSQL 与 checkpoint 密码继续仅在独立基础设施身份中出现。生产静态加密/备份 KMS/租户隔离留给 P10。
G. **TTL/物理清理：**先写保留策略 ADR 与数据依赖图（execution.runs、ledger、calls、artifacts、events、官方 checkpoints 相关表、可能的审计保留要求）；实现最小、独立、可信维护入口（CLI/maintenance job），支持 `dry-run` 列出受影响 run/工件/行数，执行模式须显式确认且由专用维护身份授权。必须双重校验 TTL 与终态/无活动锁、无待确认外部调用、无人工审批/保全标记，确保同 run 的 Checkpoint/子图引用、账本/工件一致删除；不得删除 P3 Registry、业务表、Dataset 版本或还被引用的工件。运行时 `datapilot_runtime`、MCP reader 和模型工具依然**没有 DELETE/DDL/维护权限**。如官方 Saver 表清理语义/权限无法安全证明，禁止静默“先删一部分”，先交 ADR+dry-run+独立失败测试说明阻塞，不能宣称已自动清理。不要在开发期间删除用户已有运行记录或 Docker Volume；仅在隔离测试库里构造过期运行验证删除。默认不自动运行不可逆清理，生产保留与自动化调度留 P10B。
H. 部署与契约：锁定此阶段必须的 FastAPI/Streamlit/Langfuse（确有必要才添加）等依赖；保留 PostgreSQL 17+pgvector，新增迁移必须采用 0005 以后版本，冻结 0001–0004；官方 Saver 的 schema/迁移由既定 owner/setup 管理。提供 Windows PowerShell 与 Docker/uv 启动、健康检查、离线/无模型 Key 时的有限演示和可选真实 DeepSeek smoke，不重 Seed、不 drop Volume、不在 HTTP 请求中 setup/migrate。

【前后端必须严格分离】
1. Streamlit 仅作为 UI 客户端，所有业务操作必须通过FastAPI 提供的 HTTP API 完成。
2. 禁止 Streamlit 直接导入或调用 LangGraph、Agent Runtime、MCP、数据库 Repository、Dataset Service 等业务模块。
3. 上传、分析、报告、任务状态、审批、取消、恢复等操作统一由 FastAPI 提供接口。
4. FastAPI 使用稳定的 Pydantic 请求/响应契约，并提供 OpenAPI 文档。
5. Streamlit 只负责页面布局、交互、状态展示和 API 请求，不承担业务逻辑和权限判定。
6. 增加 API 独立测试，保证不启动 Streamlit也能完成全部核心业务流程。
7. 架构必须允许未来用 React + TypeScript替换 Streamlit，而无须修改核心业务逻辑。

【独立验收与交付】
1. API contract 与负面权限测试：客户端猜 run_id、错 scope、过期 Evidence、重复 idempotency key（同载荷/异载荷）、伪造批准、上传注入和遥测脱敏。
2. 独立真实 PG/MCP 跨进程测试：Web 创建任务→Worker 暂停/运行→杀掉 API 进程→新进程恢复→报告显示 completed + P3 verified refs；重复提交不增加模型请求或重复任务。模拟 429/失败时前端保留准确错误与预算状态。
3. 受控清理测试必须只使用隔离创建的记录：dry-run 不改变状态；执行前活动/审批/uncertain 挡住；合法过期终态清理后无残余可读 Checkpoint/Artifact/预算，审计/保留规则遵守；无法安全自动清理时明确 fail-closed 与未达成事项。
4. 完整本地产品 Smoke：真实 CSV/XLSX → Preview → 人工 Confirm → 受限 PG 入库 → Dataset/Metric version → 自然语言 SQL + 真 RAG → P3 verified Report → Trace → cancel/review/resume。Mock/Fake 与真实 DeepSeek 分开报；不以系统启动或 UI 演示冒充真业务正确。
5. 至少交付 docs/product-demo.md、docs/data-retention.md、API 文档、可复现命令及实际测试/CI 统计，更新 README、AGENTS、roadmap、必要 ADR，注明 P10 生产化缺口。

【补充：P6C 验收边界与恢复一致性】
1. **严格前置条件**：P6A 真实 RAG 与 P6B 跨来源可信报告必须已通过独立验收。如果缺少对应实现、文档或真实测试证据，本轮只输出阻塞清单并停止，不允许用 Fixture/Mock 代替前置交付。
2. **故障恢复分类验收**：将“已提交结果可安全恢复”和“外部调用状态未确认”分成独立测试。前者要求复用已提交结果、避免重复模型请求及重复结算；后者必须保留 `RECOVERY_UNCERTAIN` 和预算状态，等待可信人工对账，不能强行要求自动恢复到 completed。
3. **API 任务生命周期**：服务重启后必须依据 PostgreSQL 权威状态及现有持久调用日志重新核对任务。不得依赖进程内字典、孤立 asyncio Task 或 FastAPI BackgroundTasks 作为唯一运行状态。允许可信用户显式恢复安全的暂停任务；不得将状态未知的执行直接标为成功，也不得无依据自动重发外部请求。
4. **Checkpoint 清理边界**：先核实当前锁定的 LangGraph PostgreSQL Saver 是否提供适用的线程删除接口及其子图覆盖语义，优先使用受支持的接口。清理必须由专用维护身份执行，具有并发隔离、幂等性和中途失败后的可核查状态。无法证明完整安全删除时，保留 fail-closed 的 dry-run 与 ADR，并明确将物理清理标为未完成，不得宣称已实现自动清理。
5. **业务完成与证据**：执行状态和业务目标完成状态分开返回。涉及 P3 业务指标的报告必须使用真实、未过期、版本匹配的 verified Evidence；其他任务依照各自已定义的完成契约验证，不能强制制造无关的 Metric Evidence。前端不得把单纯 execution succeeded 映射成 business completed。
6. **本地 Web 安全**：FastAPI 和 Streamlit 默认只监听 `127.0.0.1`，校验 Host/Origin 并为修改状态的请求提供适当的会话与 CSRF 保护。浏览器提交的 run_id、owner、scope 和批准参数不能作为独立授权依据。
7. **交付范围**：未经用户另行批准，不执行 git commit、push 或修改远程 main。交付变更列表、测试结果、未完成项和风险，等待验收。

只在 P6C 独立 Gate 验收通过后停止；不要自动推进 P7，也不要自动提交/推送 main。

```

---

## 8. P7 — 独立 E2E、真实故障矩阵、消融与成本评测

### 本版变更（相对 v2.2）

保留 ≥50 任务与隔离 holdout；显式增加 **PostgreSQL 真实重启（仅隔离测试实例）**、供应商网络/HTTP 故障、Durable 入口、跨进程恢复与 L1–L4 的真实费用/缓存/语义保真评测。不要把故障注入等同于随意中断用户正在使用的 PostgreSQL。

### 可直接给 Codex 的 Prompt

```text
本次只授权 P7：对 P0–P6C 已实现的 DataPilot Pro 做独立、可复现的 SaaS 业务评测、故障注入和消融。不是借评测名义修改 Prompt/模型刷 holdout；不推进 P8/P9/P10，也不改动生产 Schema/权限以获取更高分数。

【评测协议先冻结】
1. 至少 50 个独立 SaaS 经营分析任务，dev/sealed holdout 严格隔离，冻结 seed、数据/文档 manifest 与 SHA、Dataset/Metric/Semantic/embedding 版本、报告 Gold/拒答条件。Gold 经独立 SQL/Decimal/经审阅业务口径/人工定义产生，绝不以被测 Agent 输出反推标准答案。覆盖单表/JOIN、日期/货币/时区、收入/流失/使用量、CSV/XLSX 异常、RAG 来源、跨来源因果误判、权限、缺证据、人工审批、长上下文与恢复。
2. 预注册指标、分母、阈值和禁调优规则：执行成功率、**业务答案/单位/口径正确率**、P3 Verified Evidence/引用覆盖、合法拒答率、安全拒绝率、重复外部调用率、确定恢复率与 blocked/uncertain 分母、p50/p95、实际模型 Token 和 provider cache 命中、价格估算/真实账单（不可混）、人工介入次数、CI/置信区间；负结果不能删除。
3. 分层报告 Unit/Contract → 真实 PG/MCP+Fake → 真实 HTTP SDK Mock → 显式 opt-in 真实 DeepSeek 端到端。真实 API 预算、Key 和用量事先授权；离线就标记 not_run。不拿 Fake/预录历史回放当真实自主多轮推理。

【可靠性/故障注入矩阵，必须可核对】
4. 在**新建、可销毁的隔离 PG17+pgvector CI/临时测试实例**中实际重启 PostgreSQL；验证中断前/断连期间/恢复后的 Checkpoint、调用日志、父子预算、Artifact SHA、review/cancel/status、一条 running+一条完成任务的恢复行为。禁止停用、删卷或故意损坏开发者/用户现有数据库。`docker compose down -v` 仅可针对明确创建的一次性测试项目且事先获授权，否则禁用。不能仅以 `pg_terminate_backend` 冒充 PG 全实例重启。
5. 对 DeepSeek/provider API 做 HTTP 层故障注入：401/403（鉴权拒绝）、429（限流）、500/502/503/504、连接失败、读超时、取消、返回畸形 usage、null content/不完整 tool calls、请求已发出但响应/Checkpoint 未提交。对每个 cut-point 写清楚是否允许重试、唯一重试所有者、是否会重新计费、ledger 保守扣减与 RECOVERY_UNCERTAIN；未核实的已发出调用绝不强行再发。真实供应商故障实验只能 opt-in，不能向真实端点制造无界故障/费用。
6. 覆盖并发两 Worker、review interrupt、重复 resume/approve/cancel、跨进程进出、TTL 即将过期、API 任务重试/idempotency、部分成功/部分失败、P3 来源/Metric 版本变化、损坏 Artifact/ledger，以及生产端不会因为遥测失败泄露数据或扩大权限。P6C 维护清理流程只用隔离记录做 dry-run/执行安全反例。
7. 上述故障逐项列出预期结局：安全成功/复用已提交结果、可拒绝/需人工对账、明确失败；并统计“任务层可靠性”与“供应商端 exactly-once 不可保证”的边界，不给出零数据的百分比或伪造供应商扣费。

【压缩、性能、消融】
8. 比较 L0/L1/L2/L3/L4 对相同任务的可观测模型输入、**真实 provider 报告 input/output/cache-hit/cache-miss**、输出 Token、额外摘要调用、总费用估算、端到端延迟与最终语义正确性。L4 的摘要成本和恢复调用成本必须全部计入；对各等级冻结输入历史、模型/温度、预算、时序、压缩阈值，披露 Provider Cache 不可隔离等混杂因素。上轮 75% 压缩率是受控场景结论，不自动外推产品成功率。此阶段可识别改进点，但不能为增加收益而牺牲权威 refs/原始 AI/Tool 配对。
9. 公平消融按“Base SQL → +Worker Loop/Planner → +P3 Verifier → +Context Compression → +Memory/Recovery → +真实 RAG/多 Agent Report”，同模型、数据、工具权限与资源。无有效安全基线的消融明确标注不可运行；如果外部模型变更或产线缓存不可控，按混杂因素报告。
10. Mutation Testing：临时分支/临时变体中破坏角色检查、DatasetScope、metric_version、tool_call_id、Artifact SHA、单位/时间右开、预算结算、恢复一致性、P3 verified 守卫，预先要求相关反例变红；执行后恢复干净代码且不推送危险变体。
11. 可选与 Claude Code 产品层对照：对双方使用同一经授权源文件与业务问题，披露供应商模型、可用工具/权限、手工准备、后端、Token/价格、是否允许 shell；不能归因错误，也不强行宣称比 Claude Code 更好。

【验收与停止】
交付 docs/evaluation.md、docs/reliability-matrix.md、可复现 JSONL/summary、sealed holdout manifest、故障注入脚本、至少 5–10 个详细 bad cases 与独立的 PG 重启/供应商故障结果。每个结果给真实次数、分母、失败分布、成本来源与环境说明。已修复缺陷必须在 dev/新封存集验证，不污染 holdout；如某故障或 Live 未执行必须标明 not_run。达到明确验收后停止在 P7，等待用户独立授权下一阶段。
```

---

## 9. P8 — 条件触发的 LangGraph Fork（默认不做）

```text
P8 是可选 Runtime 科研线。只有 P7 提供可复现证据表明锁定的官方 LangGraph API 在当前需求上有无法通过公开扩展解决的机制缺口时，才开始这轮。没有实证缺口立即停止，输出不 Fork 的 ADR。

先定位具体官方版本、函数/模块与最小失败复现：Send/Command、Pregel 并发、RetryPolicy、Checkpoint、Interrupt、reducer、恢复。证明公开扩展为何不足，且要写出现有业务不变量。

如确需 Fork：单独分支/仓库、最小 Diff、保留上游许可证/版权、开关可回退。运行上游适用测试与自己的最小反例，以及在**相同 DataPilot Harness、模型、数据、并发、预算**上的 A/B。衡量 p50/p95、吞吐、恢复一致性、错误率、额外开销和维护成本；无明显收益回退官方实现。不得把 Fork 作为进入 P9 的前提。

只输出真实实验与 ADR，不在没有验证的情况下声称比 Claude Code/LangGraph 更强。
```

---

## 10. P9 — 可选 Domain Pack 与干洗店试点（独立于 P8）

```text
P9 仅在 SaaS 主线成熟、经营者授权且真实 POS 导出能力明确时推进。用户家庭干洗店现有第三方收银/会员软件，但品牌/API/导出字段不明确；未获得数据前只能用明确 synthetic fixture。严禁编造 Connector 或未经允许上传真实门店数据。

在不复制 LangGraph/Harness/Worker 的前提下实现 versioned DomainPack：可信的字段映射、实体/粒度、指标/质量政策、权限约束、Verification Gold 与评测。SaaS Pack 完全回归，干洗店仅为独立扩展。

从已授权 CSV/XLSX 报表开始，按实际数据确定 orders/order_items/payments/customers/member_transactions/pickup_records 的存在性；区分订单金额、实收、充值、会员消费、退款、收/取衣时间。缺成本数据不报准确利润，缺交付时间不报超时率；任何前提缺失都给出不可计算。

完整覆盖导入幂等、跨月交易、重复订单、部分退款、多方式支付、客户 ID 缺失、币种/时间差异、来源有效性与人工确认。最终经营者试点 5–10 个真实问题按授权和脱敏规则独立报告，不与 SaaS Benchmark 混合，不上传未经授权的真实数据至第三方模型和日志。

输出 DomainPack 源码/业务文档/独立 Gold/安全约束/店主反馈；P8 Fork 不作为前置条件。
```

---

## 11. P10 — 生产化专项（不阻断 P6/P7；按子阶段分别授权）

**重要**：P10 面向“允许真实多企业同时使用、对私密数据负正式责任”的生产化目标。P6/P7 完成可以形成成熟的**本地单用户原型**，但不意味着可以将服务暴露公网或宣称多租户隔离。P10A/B/C 每次只批准一个，**P10C 长期 Memory 可完全不做**；P8 Fork/P9 干洗店与 P10 无强制依赖。

### P10A — 生产多租户身份、授权与 RLS（需要时单独发送）

```text
只推进 P10A：生产多租户身份、可信 tenant 传播、数据库 RLS 和跨层隔离。此阶段要先证明目前 P6C 的单用户可信假设在哪里失效，不得把 run_id/dataset_id 当身份凭据；禁止为了赶进度粗暴给 runtime/Reader 角色大权限。

1. 审查完整数据流与身份映射：HTTP 身份验证→组织/租户→owner/用户授权→DatasetScope/source/Metric/P3 Registry→SQL/RAG MCP→P4/P5B Checkpoint、ledger、calls、artifacts、events→Langfuse/Streamlit/对象存储/后台队列。定义业务 tenant_id 与 run_id、dataset_id、source ID 不可互换的契约；模型输入/工具返回不得指定租户授权。
2. 选择并说明组织、用户、角色、租户管理边界；设计可信 token/session 验证、服务身份、最小授权、审计与撤权传播，不在前端提交 owner 字符串作为授权。定义旧单用户数据的显式迁移/回退策略，按风险独立审批迁移方案。
3. 采用 PostgreSQL 行级安全 RLS 或等效可严格证明的数据库隔离，并覆盖所有跨租户内容表、版本引用、元数据访问和检索；设定服务角色与 BYPASSRLS/Owner 权限不变量，连接池复用/SET LOCAL tenant context 防串线。无法用 RLS 覆盖的 Saver 元数据需要强等价的硬隔离和测试，不能假装拥有 RLS。
4. 构造至少两个独立租户同时运行的端到端测试：数据上传/检索、Schema/metric、Artifact/ref/run_id 猜测、报告、Checkpoint/resume、Memory（如存在）、Trace、跨租户审批/取消、缓存与故障重连；任何跨租户读写/引用/恢复必须被拒绝，已发出的数据库查询不得跨权界复用。独立威胁建模与高风险复核。
5. 交付 docs/tenant-isolation.md、架构/迁移 ADR、最小权限清单、真实 PG RLS/负面测试和清晰的可回滚部署方案。先在隔离部署验证，不直接上线；不要改 P10B/C。
```

### P10B — 生产数据保护、密钥、备份/恢复与保留合规（需要时单独发送）

```text
只推进 P10B：Checkpoint/Artifact/业务文档的生产级数据保护与运维，不重做 P5B 图恢复算法，不进入 P10A 多租户逻辑（如尚未授权）或 P10C 长期 Memory。

1. 基于 P6C Data Map 建立敏感等级、数据最小化、静态/传输加密（包括 PG 数据目录、备份、归档、对象存储、遥测）、密钥托管/轮换、凭据分离与访问审计。不能将“数据库角色受限”误写成静态加密；每一项标示已实现/待部署/测试方式。
2. 设计自动化 TTL/物理清理调度：使用 P6C 经验证的专用维护接口，保留 dry-run、预览、明确批准或运维策略授权，优先校验 active/paused/review/uncertain/hold；按可靠顺序清理 execution 与**官方 Checkpointer 父子图**，不在执行中途删引用、不清业务表/P3 Evidence。审计保全/法律保留优先，清理失败必须失败关闭且可安全续做。
3. 制定 Postgres backup/PITR、checkpoint 与 Artifact/ledger/call journal 的一致性恢复方案，实测整库恢复和业务正确性（不仅单 Python 进程恢复）。定义 RPO/RTO 目标和客观测量，不宣称未经验证的 SLA。
4. 做安全部署与渗透负面测试：管理端口不可公网访问、最小 DB/Checkpoint owner、日志和 Langfuse 隐私、API Key 轮换/吊销、错误脱敏、请求大小/速率和多租户场景（若 P10A 已完成）。运维回滚、恢复演练与灾备步骤要可复现。
5. 交付 docs/production-security.md、docs/backup-retention.md、部署审计表、真 PG 备份恢复/清理测试与风险清单。任何清理或演练只对专用测试环境执行；不得删除当前用户数据库/Volume。
```

### P10C — 可选持久长期 Memory（产品确有需求才发送）

```text
本轮仅在确认真实业务需要跨任务长期偏好/术语线索时实施 P10C；不把它当作 P5B Checkpoint、P3 Metric Registry 或生产多租户的替代品。

1. 沿用 P5A 经审阅 MemoryEntry/MemoryStore 协议，明确是提示而非权威事实。存储仅允许枚举偏好、带 source_ref+version 的术语/决策引用；不得存任意行/支付信息/完整 Prompt/API Key。
2. 对持久 Memory 增加 owner（如已实现 P10A 则为 tenant/user）、scope/worker、TTL、来源/定义版本与撤回标记。每次 recall 重新校验撤权/版本/上下文身份，不能仅在插入时检查；改 Registry 或数据集版本后陈旧 Memory 必须自动失效或拒绝召回。
3. 模型不能自动自批准永久记忆；增删改由可信宿主显式 review/撤销，具有配额、审计和可彻底清除的数据主体操作。隔离测试跨用户/租户串扰、版本更替、过期、记忆注入、进程重启与清理。
4. 加入同业务任务“无长期 Memory vs 已审阅 Memory”的真实效果/成本对照；若无增益可不启用。交付 docs/persistent-memory.md、负面测试及明确边界，不自动扩展为自由知识库。
```

---

## 12. 推荐发送顺序与验收关卡

| 发送顺序 | 发哪段 Prompt | 对应 Gate | 必须看到的证据才能继续 |
|---|---|---|---|
| 历史已完成 | **P4.1**（不要再发） | Gate C 前置加固 | 现有 P4 回归、权限/证据反例、轻量上下文措施或有理有据的延后 |
| 历史已完成 | **P5A**（不要再发） | Gate C | 结构化上下文/分级压缩，不丢版本/目标/证据，Token 实测 |
| 历史已完成 | **P5B**（不要再发） | Gate C | **真实 PG 跨进程恢复**、持久预算与工件一致性、故障注入 |
| **①（现在）** | 通用前缀 + **P6A** | Gate C | 真正 pgvector 检索、文档版本/引用、权限/空检索与注入测试 |
| **②** | 通用前缀 + **P6B** | Gate C | P3 验证证据接入多 Agent、真 SQL+真 RAG 联合业务报告 |
| **③** | 通用前缀 + **P6C** | Gate D 产品基础 | **Web 默认 Durable**、隐私边界、TTL 安全维护，真实上传→报告+恢复闭环 |
| **④** | 通用前缀 + **P7** | Gate D 独立评测 | ≥50 个独立任务、**隔离 PG 真重启/DeepSeek 故障**、holdout、消融、费用与正确性对照 |
| 可选 | **P8** | Gate E | 必须有官方 Runtime 缺口的最小复现 |
| 可选 | **P9** | Gate F | SaaS 主线稳定，干洗店导出/授权条件明确 |
| 独立生产化 | **P10A** | 生产租户 Gate | 身份链、真实租户隔离/RLS、安全反例 |
| 独立生产化 | **P10B** | 生产运维 Gate | 备份/恢复、加密/密钥、TTL 安全清理与演练 |
| 可选 | **P10C** | 长期 Memory（需求驱动） | 审阅、scope、版本、TTL、撤销及跨进程验证 |

### Gate 口径再确认

- **Gate A**：P1/P2 文件到安全数据库/动态 MCP。
- **Gate B**：P3 语义指标与六层证据验证。
- **Gate C**：P4 多 Agent、P5 持久恢复、P6A 真 RAG、P6B 可信跨来源业务分析均通过；不能把 P4 的 fixture 充当完成。
- **Gate D**：P6C 可用产品与 P7 独立 E2E/消融交付后验收。
- **Gate E/F**：P8/P9 可选独立，不互相阻断。
- **生产化 Gate（P10）**：仅在计划真实对外多企业商用时单独授权，含安全评审、隔离测试与运维验收；不是原型 Gate D 的必要条件。长期 Memory 可选。

## 13. 两条最重要的审查原则

**原则 1：最小新增、优先修补。** P4 已有 `TaskSpec/Plan/TaskEnvelope/TaskResult`、`ToolRegistry`、`BudgetLedger`、`ArtifactStore`、`Trace`、LangGraph `Send/Command`，Codex 在每阶段必须先列出这些模块的可复用接口；不要照搬 Mini 再造一整套。

**原则 2：所有“Agent 很智能”的主张都要有正确性证据。** 上下文压缩省 Token 不能丢用户约束；Planner 成功不能等于业务验证成功；RAG 召回不能等于引用真实；Mock 工具调用成功不能等于真实模型 E2E；代码行覆盖率不能等于业务任务成功率。

---

**当前第一次执行建议（P5B 已完成）**：将**第 1 节通用前缀 + 第 5 节 P6A Prompt** 拼在同一条消息发给 Codex；完成真实 pgvector 检索验收后再发送 P6B，依次推进 P6C/P7。**不要把历史 P4.1–P5B 重发，也不要一次性发完整文档要求全部完成。**

**版本说明**：本 v2.3 是独立文件，原 v2.2 保留。P6C/P7 增量依据 2026-10-21 已验证的 P5B 代码和已披露的剩余风险制定；若仓库新提交改变条件，Codex 必须报告实际差异而不是照抄过时结论。
