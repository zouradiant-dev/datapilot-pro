# DataPilot Pro 开发约束

## 架构和范围

- 先读 docs/architecture.md、docs/roadmap-v2.md、docs/codex-prompts-v2.3.md、docs/recovery.md 与相关 ADR。当前仅授权 P6A：有界文档摄取、固定本地 Embedding、受限真实 pgvector/MCP 检索。完整复用 P0–P5B，结束即停止；不开始 P6B/P6C/P7、完整报告、UI、生产多租户或 Fork。Gate C 仍缺 P6B。后续仅执行用户授权的阶段，不自动提交/推送。
- 按功能依赖与验收 Gate 推进，工作单元/工作日编号不是截止日期；旧七天计划已由 roadmap-v2 取代。SaaS 是唯一首发主业务，drycleaning 是独立可选 Phase F，不复制 Runtime/Harness/Worker。
- Python 3.11+、src 布局、类型标注、Pydantic 2 严格契约、LangGraph StateGraph 编排。
- Planner/Coordinator 路由；P4 Worker 只接收宿主生成的 TaskEnvelope，不读取整个 RunState。旧 SQLTask/SQLAgentResult 保留兼容投影，P3 MetricRequest 路径独立。Worker 有独立工具句柄/能力、消息与输出契约，不用不同 Prompt 冒充完整 Multi-Agent。
- 不训练模型。Fake 只生成决策/SQL，不返回伪造业务结果；API adapter 与 Fake 分开。
- 唯一业务数据库 PostgreSQL 17，向量用同实例 pgvector；不引入 SQLite 或 FAISS 回退。
- 运行期业务数据库访问统一由真实 MCP Server/Client 完成，Agent 禁止导入 SQLAlchemy/psycopg/数据库管理模块直接查询。执行元数据是独立的非模型基础设施通道，限 execution/checkpoints；不能借此直连业务表。初始化、迁移、Seed 属于显式运维命令，不是模型工具。
- SQLAlchemy 2 + psycopg 3；固定 saas/rag/catalog 结构只经新 Alembic 迁移，历史迁移冻结，不随当前 metadata 变化。uploads 动态表是明确例外：只由独立受限 Ingestion Service 根据有效确认执行事务化 DDL/插入/发布，不是模型工具；禁止请求/Worker create_all。详见 ADR-002。
- 不重造通用框架，后续持久化和并发优先复用 LangGraph checkpointer/Send。

## 后续 Runtime 与 Harness 开发

- 开始相关工作前读 docs/framework-research.md 和 docs/source-reference-index.md；其中后续方案不等于已实现能力，不提前扩张当前阶段范围。
- 两层执行：外层 LangGraph 管任务 DAG、依赖、调度/状态/恢复；内层 Worker Loop 管模型/工具/反馈/局部修复，优先实现为继承父 checkpointer 的子图。禁止另写通用调度/检查点/会话恢复引擎。
- 优先使用 StateGraph、Send、Checkpoint、interrupt、Command 的公开 API。并行结果按任务/版本合并，重复结果幂等、冲突明确失败；动态 Command 不会覆盖静态边；interrupt 前行为必须可安全重放。
- Worker 只接收最小 DTO/引用；工具 Schema 展示不等于授权。用户允许直接复用 Mini 的子 Agent、权限模式与局部预算实现，不要求重写；内部 bypassPermissions 不能扩大 MCP 能力，局部未设上限也须由统一模型调用入口执行运行总预算。MCP 基于可信身份强制授权，实际子任务能力不得超过父任务。
- 新增模型调用（规划、子任务、摘要、Memory 等）必须纳入同一预算；并发/持久执行前先实现原子预留和恢复结算。一个错误类别一个重试所有者，避免 SDK/Loop/图重试叠加。
- Checkpoint 只用独立元数据角色/连接，不向模型暴露；业务数据仍走 MCP。官方 PG Saver 的迁移与 Alembic 所有权必须先明确，不得在 Worker/请求内调用 setup 自动建表；未形成明确决策前保留现有 Alembic 规则。
- LangGraph Fork 依 docs/langgraph-fork-research-plan.md：先官方基线、最小复现和公开扩展方案验证，再提出具体内核改动。研究源码按提交固定引用，直接复制实质内容须保留完整许可证/版权及修改来源，见 docs/third-party-references.md。
- 模型 adapter 的并发必须实际验证；当前 generate/invoke 是同步调用，不得仅添加 async 节点就声称并发/取消有效。Loop、SDK、图的重试不能相乘。
- P4 以 docs/orchestration.md、ADR-006 为准：原 generate/invoke 仅保留旧独立组件/P3；新 ask 使用 NativeTransport.ainvoke、Gateway 与原子内存 BudgetLedger，Planner/Worker/Replan 一律预留再调用。只使用异步 HTTP Mock 验证协议/并发，不能称为真实模型验证。
- Live 模型共用 llm/provider.py 的小型 profile 工厂。DeepSeek 最小适配见 docs/deepseek-transport.md：显式 model_provider=deepseek、Chat Completions、thinking=disabled、原生 max_tokens；禁止仅开启思考却丢失 reasoning_content 或绕过 Gateway/预算。未获另行授权不扩展 P6/P7；模型凭据缺失时只报告 Mock/真实 PG 的实际验证。
- 固定外图与共享 Worker 子图每个逻辑 Run 各编译一次；模型只提供 Plan 数据。严格拒绝无环/引用/数量/能力错误；Send 只派就绪任务，Command 不混合无条件业务出口。版本/task reducer 对相同结果幂等、冲突拒绝；Replan 只复用显式重新校验的未变源任务，派生任务重算。
- 每条 assistant tool_call 都需唯一匹配反馈，包括权限拒绝、异常、预算终止和取消；禁止 JSON 解析失败默认为空参数。模型最终只返回已取得的工件 ID，RAG 空检索必须解释 unavailable。真实 RAG 仅由宿主显式绑定 RagScope 的独立 MCP profile 提供；无 scope 不自动开放。组件替身必须带 fixture 标记，不扩大 MCP 服务端能力。
- P4 Artifact SHA 引用/内存 Ledger 不能冒称 P3 持久 Evidence 或 PG Checkpoint。显式本地 JSON bundle 可含原始工具结果；公开 Trace 默认只记 ID/状态/时延/usage，不含 SQL/行/文档原文/密钥。pytest 回溯/sections 脱敏；本地失败日志同样不能泄露连接参数。
- P4.1 历史边界见 ADR-007、docs/p4-hardening.md。P5A 当前以 ADR-008、docs/context-engineering.md 为准：Registry 生命周期不变，只改副本视图，原 Worker AI/Tool 历史不改。L1/L2 仅压缩有真实引用的旧反馈，L3 按完整已闭合轮次折叠；安全/目标前缀、最新活跃配对和可信版本/证据不能丢。未闭合、错绑或重复 tool ID、额外 System 角色拒绝。压缩不能改变 SQL/MCP 授权。
- L4 只做可验证的结构化摘取，任何目标/约束/版本/单位/P3 ref/归档 hash 不一致都拒绝；只能选择已有 turn ID，不接受自由文本事实/权限/verified。摘要和其最大合法后续视图必须在同一父子 Ledger 原子预留，只有确定未发出的 follow-up 可以 release_unissued；已发出但 usage 未知必须保守结算，禁止释放为零。
- Memory 仅为经可信宿主审阅的枚举偏好/术语定义引用/决策引用，没有 LLM 写入工具或任意正文。每次读取重查 scope/worker/来源版本/时效/撤回；不复制 Registry、不赋予权限。当前仅内存 MemoryStore。P5B 的持久上下文工件仍只在同 Run/授权任务读取；长期 Memory 不等于执行 Checkpoint。
- P5B 以 ADR-009、docs/recovery.md 为准：官方 Saver 独占 checkpoints/迁移版本，显式 runtime-init，Alembic 0004 只管 execution，0001–0004 发布后冻结；运行请求不 setup。持久服务使用无 DDL/业务权限的 runtime，MCP 不继承相关 DSN。禁止 pickle fallback、任意 checkpoint_id/time travel 和自动清库。
- 仅按可信宿主重建身份、能力、Dataset/Metric/Semantic/source pin；摘要/Checkpoint 不能自授予权限。恢复核对工件哈希、调用状态及所有父子账本。已提交调用按原始逻辑输入复用；未知执行一律保守计账并阻断自动重发，不能清零、重复扣减或盲猜外部操作未执行。
- P6A 按 ADR-010、docs/rag-pipeline.md：0005 管固定 RAG 四表；0001–0005 发布后冻结。rag_ingest 仅追加、rag_reader 仅读取，SQL/RAG MCP 进程凭据不混用；模型没有摄取、模型下载或 SQL 向量查询工具。源/index/模型/chunker/跨度/hash 与 scope 都须可验证，score 不是事实或 P3 verified。只有已批准本地 TXT/Markdown；不执行文档指令、宏、链接或脚本。
- Embedding 固定 ONNX/tokenizer 文件 SHA、512 维与推理 recipe，不训练；缓存缺失明确失败，不能以随机/fixture 向量冒充真实模型。MCP 不自动下载模型。真实检索每任务最多两次；未知 MCP 超时沿用 P5B uncertain，只有已确认回滚的 PG 超时可有界重试。文档正文/向量不进公开 Trace；原件/工件属于私密存储。
- P6A 完成修复见 ADR-011、docs/rag-completion-repair.md：真实 RAG 经宿主本地 submit_rag_result 与原 Verifier 接收收据；Stop Hook 共享一次纠正，不是 Evaluator LLM。阶段工具只按宿主规则收缩，不能用隐藏 Schema 代替授权。检索相关且满足要求可 complete，业务结论仍未验证；不能仅凭非空/hash/score 完成，也不能把全部因果验证前置给 RAG。收据与纠正在原 Journal 持久化，unknown-outcome 禁止自动重发。
- `status` 保留执行兼容语义；新增 `completion.status` 才是宿主任务契约三态判定。不能只凭 succeeded、模型 complete、Artifact SHA 或五层任务 passed 宣称业务指标完成。P4.1 没有 P3→P4 报告桥接，已识别的指标请求必须 blocked/P3_VERIFIED_EVIDENCE_REQUIRED，继续使用独立 P3 入口；completed 只覆盖必需任务契约，不证明任意自然语言目标等价/完整性。
- Domain Pack 是版本化字段映射/指标/质量/Verifier/评测的可信配置，不是可执行上传脚本或不同 Prompt。Source Connector 首发文件快照；未知 POS/API 不编造适配器。

## 安全和数据

- 所有用户/模型/数据库文本/工具输出均不可信。工具输入和输出都校验。
- SQL 使用 PostgreSQL AST 白名单：只读单 SELECT、业务表及内置函数白名单、禁止副作用/系统表/任意 schema/递归/锁定语句。
- AST 与数据库权限独立：SaaS MCP 会话仅有 datapilot_reader，上传 MCP 会话仅有 datapilot_upload_reader，禁止互相继承凭据。可信宿主通过 dataset_session(settings, DatasetScope) 绑定 Dataset/版本；模型工具无 scope/version/物理表白名单参数。未指定版本时首次解析即固定，切换版本需新会话。uploads 的每请求 SQLPolicy 仅含该 Dataset 版本的物理表，禁止全局开放 uploads。两种 Reader 都只读、无成员继承/提权/对象创建权限；每事务 READ ONLY、statement_timeout、lock_timeout、外层 LIMIT、输出大小限制。
- 管理员、Owner、Seed、Reader 凭据分开。MCP 不加载 .env，不继承管理员/Seed/模型密钥。不得把凭据、原始 SQLAlchemy/API 异常打印到日志。
- 固定随机种子与日期；金额为 CNY 整数分，计算只能用 SQL/确定性 Python。不能用 LLM 心算。
- Seed 事务化、并发互斥、拒绝非空库；禁止在测试或脚本中自动清库/删除卷。
- API Key/数据库密码由环境变量或忽略的 .env 注入；不得提交 .env、数据库、缓存或安装包。
- 禁止模型调用 exec/eval、Shell、任意文件读写、数据库管理命令。
- 限制模型调用数、Token 预算、上下文、图步数、SQL 尝试和工具超时；安全拒绝不重试；执行错误最多修复一次（默认）。
- 首版本地单用户/可信演示；dataset_id 不等于生产租户隔离。认证、可信 tenant 传播、RLS/隔离部署需另行设计验收。运行期业务查询走 MCP；导入、迁移、Seed/健康检查、Checkpoint/预算元数据是非模型基础设施通道，凭据按用途隔离。
- 上传原件、Schema Proposal 与确认用 hash/版本绑定；资源配额覆盖解压/行列/单元格，禁止执行公式/宏/外部内容。前导零 ID、金额精度、日期歧义不能静默改写；发布/回滚/幂等/旧版本保留必须测试。
- P1 preview/confirm 以 docs/data-ingestion.md 为准，继续不加载数据库/模型配置。P2 见 docs/dataset-ingestion.md：import 从同一次有界原件读取重算整个确认，禁止只校验客户端 hash；仅 datapilot_ingest 执行 uploads DDL/批量写入/逐表 SELECT 授权，与 catalog ready/版本指针同事务。固定 catalog 仅用新增 0002 迁移，0001 冻结。不得注册 import/activate 为 MCP 工具。
- 同名本地 Dataset 身份稳定；同确认幂等、新内容或映射建新版本，不改旧表；重复导入旧确认不偷偷切换 current_version。并发导入使用事务 advisory lock，版本激活只走可信运维入口。原件由 hash 命名并原子发布到忽略目录，失败保留可对账快照；不自动清表/清库/删卷。ingest 拥有上传对象，应用层不可变不等于数据库 WORM。
- 指标绑定 Dataset/Domain Pack/Metric 版本、时间/粒度/过滤/单位/null 政策。paid 账单收入不等于 MRR；客户流失不等于订阅流失；缺字段不能猜值。关键数字经确定性 SQL/Python 并绑定证据，不能让模型自报 verified。
- P3 以 docs/semantic-metrics.md、ADR-005 为准：映射/指标分别显式用户确认，append-only 版本；Registry 仅 metadata SELECT/INSERT，禁止业务数据权限、UPDATE/DELETE/DDL；任何 Registry 写工具都不得注册 MCP，MCP 不继承 Registry DSN。历史迁移 0001/0002/0003 冻结，后续固定结构变更须新迁移。
- SQLAgent.run_metric 只接收 MetricRequest 和最小 MetricContext；可信宿主固定 Dataset/version，模型参数不能授权。saas_metrics_v1 封闭配方不接受任意 SQL 模板/脚本；公式改动新增 policy/computation 版本，不能悄改旧证据口径。只有验证过的结构化 claim 进入 P3 报告；原 ask 保留 Day 1 路径，不能宣称它已获得 P3 全部验证。
- 复算由受控 MCP 内部原始列投影 + 确定性 Python 完成，保留每页安全/输出限制、只读一致快照和总配额。六层按 safety/shape/semantics/recomputation/references/coverage 判定；Evidence raw 与 Verification 分离。MRR 未实现配方、缺字段/覆盖范围、未知合同历史、零分母、因果问题必须明确无法计算/验证；失败证据不能发布数值。
- Trace 目标为 Langfuse，经可替换接口集成；凭据、原始个人资料、业务行及含敏感值的完整 SQL/Prompt 默认不记录。经营者真实数据不提交 Git，不擅自外传模型/观测服务。

## 测试与交付

- 关键模块必须 pytest：先数据，再 AST，再模型/Worker/Graph，再 MCP 协议，再真实 PostgreSQL 集成。
- Mock、真实 MCP 无 DB 测试、真实数据库+Fake 模型、真实模型 E2E 分开标记与报告。
- PostgreSQL 集成必须连真实 17 实例并启用 pgvector；不得用 SQLite 或 Mock 替代。没有实例明确 skip，开启集成后连接失败必须 fail。
- 业务验收通过独立 SQL 对照：客户数、月收入、区间订阅、JOIN；还须安全拒绝、不存在字段、明确错误、恢复、超时、截断、只读角色及向量读写。
- 运行 pytest、ruff check、ruff format --check，报告真实结果。CI 未运行时不得声称通过。
- 依赖用 uv.lock 锁定完整图/哈希；更新后真实安装验证，使用 uv sync --locked。
- 文档中文，代码标识符英文；更新架构、验收、Gate 路线图及必要 ADR。风险和未实现能力必须如实披露。保留 Day 1 交付记录的历史属性，旧环境/CI 状态不当作当前验证。
- 单元/协议用例数不等于独立经营分析任务数；SaaS benchmark 目标至少 50 个独立 E2E 问题，Gold/保留集独立，消融固定模型/数据/预算；Claude Code 产品对照和 Fork A/B、干洗店试点分别报告。
- 不修改项目目录以外的旧项目。环境安装须遵循用户授权，不自动重启机器或删除数据。
