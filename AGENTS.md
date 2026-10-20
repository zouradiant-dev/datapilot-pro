# DataPilot Pro 开发约束

## 架构和范围

- 先读 docs/architecture.md、docs/roadmap-v2.md、docs/planning-audit-v2.md 与相关 docs/adr/。当前授权为 P2（D4–D5/W4–W5）：受限导入、catalog Dataset/版本与动态 MCP 查询，完成后停止；不进入 P3 指标/语义/证据 Registry、多 Agent 或 UI。P1 已验收。后续仅执行用户授权的阶段，不自动推进整个路线图。
- 按功能依赖与验收 Gate 推进，工作单元/工作日编号不是截止日期；旧七天计划已由 roadmap-v2 取代。SaaS 是唯一首发主业务，drycleaning 是独立可选 Phase F，不复制 Runtime/Harness/Worker。
- Python 3.11+、src 布局、类型标注、Pydantic 2 严格契约、LangGraph StateGraph 编排。
- Supervisor 路由；SQL Worker 只接收 SQLTask，不读取整个 State。后续 Worker 独立工具权限、上下文与输出契约，不用不同 Prompt 冒充完整 Multi-Agent。
- 不训练模型。Fake 只生成决策/SQL，不返回伪造业务结果；API adapter 与 Fake 分开。
- 唯一业务数据库 PostgreSQL 17，向量用同实例 pgvector；不引入 SQLite 或 FAISS 回退。
- 运行期数据库访问统一由真实 MCP Server/Client 完成，Agent 禁止导入 SQLAlchemy/psycopg/数据库管理模块直接查询。初始化、迁移、Seed 属于显式运维命令，不是模型工具。
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
