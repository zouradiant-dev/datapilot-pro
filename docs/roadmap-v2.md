# DataPilot Pro v2：按验收 Gate 推进的路线图

版本：v2.1 规划基线，2026-10-21。本文件取代现行架构中的旧七天开发计划。输入为用户提供的《DataPilot Pro v2.1 Roadmap and Codex Prompts》及本轮实际代码审计。

**不按日期排期。** 沿用约 20 个工作日的工作量参考，将其转为可独立验收的工作单元；编号不是截止时间或交付承诺。先通过 Gate 再推进，不能为对齐编号省略测试。前 17 个单元覆盖产品主线，18–20 是可选 Runtime 研究；不需要 Fork 时用于回归、失败案例和发布完善，不阻塞核心交付。

## 1. 当前起点与优先级

**当前增量 P6B**：在 P6A 已验收的真实检索与 P5B 持久恢复上，桥接原 P3 持久 Evidence/六层 Verification 和 P4 DAG/Artifact，输出有界跨来源报告、图表规格及明确业务完成状态；见 [实际链路/验证](cross-source-report.md)、[ADR-012](adr/0012-cross-source-report.md)。仅停止在 P6B；P6C/P7/P10/P11 均未实施，不自动提交或进入下一阶段。以下旧停止点保留为历史，不能作为当前实现缺口。

验收分层：P6A 最初两次真实 DeepSeek smoke 失败历史不变；定向补强后获授权的一次检索 smoke 成功，见 [历史与 Post-push 核验](rag-completion-repair.md)。P6B 的真实 PG/本地神经 Embedding/MCP/恢复测试使用明确的脚本模型决策，未新增付费模型实验。检索 smoke 与五个合成业务案例均不等于真实模型稳定成功率或完整经营分析基准。

起点为 Day 1：固定合成 SaaS 数据、PG17/pgvector、权限/Alembic、真实 MCP、Supervisor+SQL、有限编译修复、CLI。P0 审计基线为 `3a47d27a5920721b3d776d62de6b240c0a313213`，详见 [审计证据](planning-audit-v2.md)。P1–P5B 与 P6A 保留；P6B 接通可信报告桥接，Gate C 的该实现缺口已补齐，模型质量与 ≥50 任务基准留待 P7。P6C 产品化闭环未开始。

v2.2 的 **P4.1** 补工具生命周期、宿主完成判定、L0 工件/模型视图分离及故障反例，见 [交付与实际验证](p4-hardening.md)、[ADR-007](adr/0007-p4-hardening.md)。P5A（Context/Memory）与 P5B（PG 持久恢复）均已落实；v2.3 的 P6A 是当时的停止边界。本轮用户已单独授权 P6B，仍不能从路线图自动授权 P6C/P7/P11。

唯一首发业务是 SaaS。文件导入、语义/证据、Multi-Agent、产品化和独立评测服务这一主线。首版本地单用户/可信演示，不承诺生产多租户。干洗店 Phase F 与 LangGraph Fork 都是独立可选扩展。

```mermaid
flowchart LR
    P0[P0 本轮规划审计] --> A[Gate A 动态数据闭环]
    A --> B[Gate B 业务指标与证据]
    B --> C[Gate C 多 Agent 与持久恢复]
    C --> D[Gate D 产品与独立评测]
    D -. 有 Runtime 不足证据 .-> E[Gate E 可选 Fork 对照]
    D -. 获授权报表可用 .-> F[Gate F 可选干洗店试点]
```

RAG 组件测试可以先于完整 DAG；Gate C 的跨来源验收需要真实检索。P4 里 SQL/RAG 并发可先用明确标记的组件替身验证调度，不得据此声称 RAG 业务已完成。P6 必须补真实检索与报告闭环。E/F 互不依赖，不把等待 POS 样例或 Fork 当产品阻塞。

## 2. Gates、用例与风险

P5A 复用现有 Gateway 实现 L0–L4 的可校验模型视图、权威状态边界和 Memory 契约/内存实现，见 [上下文工程交付](context-engineering.md)、[ADR-008](adr/0008-context-authority-memory.md)。P5B 不调整压缩策略，只补官方 PG 父/子图 Saver、事务持久账本、完整工件、调用状态与跨进程恢复，见 [恢复与部署](recovery.md)、[ADR-009](adr/0009-durable-execution.md)、[交付](p5b-delivery.md)。真实 PG 故障测试和两次 DeepSeek 调用后的新进程恢复均验证；长期 Memory 后端未实现。下一阶段必须另行获得用户授权。

P5A 后单独授权的 DeepSeek Flash 兼容增量仅调整共享模型构造 profile，显式使用非思考 Chat Completions；不推进新 Gate，不改变 SQL/MCP 或上下文/预算架构。HTTP Mock + 真实 PG 回归通过；本地 Key 配置后补充一项真实 DeepSeek→MCP→PG 客户数 smoke，240/已完成，不替代完整业务评测，见 [接入记录](deepseek-transport.md)。

| Gate / 参考单元 | 交付边界 | 必须通过的验收 | 主要风险与前置条件 |
|---|---|---|---|
| A / 1–5 | 审计、CSV/XLSX Parser、Profile/确认、受限导入、Registry、动态 MCP | 文件→预览确认→ready Dataset/version→真实 PG→真实 MCP；多表 JOIN、回滚、跨 scope 拒绝、原 saas 回归 | 解包资源、类型失真、名称注入；新增迁移/ingest/upload_reader；健康检查不能写死 0001 |
| B / 6–8 | SaaS 语义/指标版本、受控计算、Evidence、六层 Verifier | paid 收入/订阅与客户/使用量独立核对；JOIN 双计、单位/日期、缺字段/伪证据拒绝 | 指标不明确先确认；不把形状正确当业务正确 |
| C / 9–13 | Worker Loop、任务 DAG/Send、最小上下文/Memory、预算、PG Checkpoint/恢复、真实跨来源 | 合法依赖/有界并发；SQL/RAG 证据汇合；缺证据定点补查；重启恢复/取消/预算一致 | 同步客户端、重试叠加、reducer 冲突、Saver 迁移所有权、Embedding 选择与真实凭据 |
| D / 14–17 | FastAPI/Streamlit、Langfuse、完整 Demo、≥50 独立任务、消融/产品对比 | 新用户按 README 完成两表上传到引用报告；真实状态/错误可见；可复现 E2E、Bad Case 与限制 | API Key/供应商效果、日志隐私；对照环境和人工介入差异必须披露 |
| E / 18–20，可选 | 原版问题复现、最小 Fork、回归与同条件 A/B，或发布完善 | 指定文件/函数、公开机制为何不足、正确性不变量、客观收益或明确负结果 | 当前无必须 Fork 的证据；先用公开扩展；保留原版开关/许可证/回退 |
| F / 后续可选 | Domain Pack、合法文件 Connector、干洗店映射/指标/试用 | 不复制 Runtime/Harness/Worker；授权报表与人工记录核对；saas 不回归 | POS 品牌/API/字段未知，真实数据授权/脱敏；缺文件只做 synthetic fixture |

每个 Gate 交付源码/文档、真实测试命令/产物、未通过项和风险。Mock、协议、真实 PG+Fake、真实模型 E2E 四类证据分别标注。单元用例数不等于业务任务数。

## 3. 已完成审计与未来五个工作包

以下保留 P0 拆分的五个工作包 W2–W6，不绑定日历；W1–W8 为历史 P0–P3 基线，D9–D10 / P4 与 P5A/P5B 已完成。后续仍须另行授权，不因列在本节就自动执行。

### W1：冻结基线与规划审计（历史 P0，已完成）

- 全读 README/AGENTS/架构/Day 1/pyproject、27 个应用 Python 文件和 10 个测试文件；补查冻结迁移、Compose/CI、Mini 核心源码与 autonomy 控制逻辑。
- 记录已实现/未实现、行号参考、依赖锁、环境与分类回归；保存业务源码/测试/迁移/配置哈希，防止文档工作带入业务变化。
- 更新架构/AGENTS/README，交付本路线图、审计报告、4 项 ADR；仅设计 Domain Pack/Source Connector，不建未来空壳。
- 通过条件：59 项既有测试通过、1 项 live 明确 skip，Ruff 通过，业务与依赖文件未改；实际证据见审计，不把缺凭据写成产品通过。

### W2：安全 Parser 与结构化预览（P1 的第一部分）

- 先审查本轮 ADR。选择最小 CSV/XLSX 解析依赖，验证 Python 3.11–3.13 兼容性后锁定；不提前添加 FastAPI/Langfuse/PG Saver 等无关依赖。
- 定义严格 UploadFileInfo、ParsedTable、ColumnProfile、SchemaProposal、SchemaConfirmation、ParseError；中间原始表示保留行号/原名/原始标量，避免解析即失真。
- CSV：BOM/编码/分隔符/表头与空行；XLSX：多 Sheet、空列/重复/中文表头、公式标记与安全策略。
- 配额：压缩与解包字节、entry/Sheet/行/列/单元格上限、时限；恶意包、坏 XML、伪后缀和路径异常明确拒绝，不执行外部内容。
- 输出：可复现 Table Preview 与质量提示；此包不连接管理数据库、不建表、不实现 API/UI。

### W3：类型、关系候选和确认（P1 的第二部分）

- 采样推断+全量验证；前导零、金额精度、日期/时区歧义、混合类型/缺值、重复列都保留诊断，必要时降级 TEXT。
- Profile：空值率、唯一性、重复、异常范围、候选键和关系基数。统计候选不自动成为可信主键/FK/业务口径。
- 确认配置绑定文件 hash、proposal hash、解析/映射版本与用户覆盖；覆盖类型也须全量验证，旧确认不可作用于新原件。
- 至少 12 个有独立意义的测试覆盖合法 CSV、多 Sheet XLSX、资源上限与失真反例；fixture 为可公开合成数据。
- **P1 结束条件**：生成可复现的预览与确认 JSON；无隐式丢行、无公式执行、无 PG DDL；原单元/MCP/真实 PG 回归保持通过。完成 P1 后停在该边界。

### W4：受限入库与 Registry（P2 的第一部分，已实现）

- 显式权限初始化创建 catalog/uploads 命名空间及角色，新 Alembic 迁移定义 catalog 固定结构，历史 0001 不修改；明确 ingest/upload_reader profile，不假设当前 Owner 有数据库 CREATE 权限。
- 按确认快照生成标识符和受限类型，事务中建表、插入、元数据和 SELECT 授权；只在完成后发布 ready。
- 文件保管与 DB 事务分开，记录中断/孤立文件；相同确认幂等，新映射/重导入生成新版本；失败回滚、不覆盖旧表。
- 兼容健康检查/CLI 的迁移版本：查询 Alembic head/兼容策略，不能继续硬编码 0001 后绕过检查。
- 通过条件：真实 PG 导入/并发重试/回滚/版本切换，Reader 仍无写入与建表，原 Seed/health 正常；无自动删库/卷。

### W5：动态 Query MCP（P2 的第二部分，已实现）

- 设计 list_datasets/get_dataset_schema/query_dataset；服务端解析授权、ready 状态和固定版本；模型不能提供任意物理表白名单。
- AST 改为显式 Policy/QueryScope 参数；保留 saas 固定 profile，新增 uploads 精确表集合，不将所有上传表加入全局常量。
- 保留函数/cast/语句拒绝、DB grants、READ ONLY、超时/锁超时、LIMIT、体积/截断和清理后的错误；返回版本与 Evidence/Artifact 引用。
- 通过条件：CSV/XLSX→PG→真实 MCP 查询、同 Dataset JOIN；跨 Dataset/系统表/写入拒绝；原四个业务问题独立 SQL 对照通过。
- **Gate A 通过后**才推进 P3 语义与证据，不因新文件能查询就声称完整 Multi-Agent 已完成。

### W6–W8 / D6–D8：SaaS 指标定义与六层证据链（P3，已实现）

- 基于 ready Dataset/version 建立已确认实体/字段/关系绑定，定义版本化 MetricDefinition 与 Evidence/VerificationResult，不让模型提交任意可执行指标脚本。
- 首先落实 paid_invoice_revenue：paid 过滤、invoice_date 右开窗口、整数分/精确金额、单位/空值政策、SQL/计算版本与结果 hash。
- 对客户/订阅流失、MRR/ARR 列出必要字段与分母政策，缺口明确请求确认或不可计算；不把现有最终 status 当历史状态。
- 加入漏过滤、JOIN 双计、日期边界、单位、过期版本和伪造引用负面测试，并用独立 SQL/确定性计算复核。
- 实际交付：确认映射/口径双重版本、五种可执行指标、明确不可计算的 MRR；只读 MCP 最小上下文与原始列 Python 独立复算；raw Evidence/Verification 分离持久化与引用报告。新 0003/Registry 角色，历史迁移和原 SQL 白名单不变。
- 通过条件：CSV/XLSX→真实 PG→真实 MCP→五种指标独立 Gold 与证据，六层检查及漏过滤/JOIN 双计/右开边界/单位/因果/不可回答负面测试。实际命令与结果见 p3-delivery；真实模型验证不包含在本次确定性验收中。

## 4. 后续任务边界

| 提示词/任务 | 范围 | 前置与停止点 |
|---|---|---|
| P0 | 已完成的文档审计 | 无业务实现；历史记录保留 |
| P1 | 本轮已完成 W2–W3 Parser/Profile/Preview/Confirm | 见 p1-delivery；不建表、不提前做 UI，到此停止 |
| P2 | 本轮完成 W4–W5 安全导入/版本/动态 MCP | 真实验收见 p2-delivery；到 Gate A 停止 |
| P3 | 已实现语义/指标/证据/六层 Verifier | Gate A；本轮到 Gate B 停止，见 p3-delivery |
| P4 / P4.1 | 动态 DAG、Worker Loop、工具生命周期与完成判定已实现 | 无 Fork；RAG 替身仅证明编排，见 p4-delivery / p4-hardening |
| P5A | L0–L4、上下文不变量、Memory 契约/内存实现已交付 | 保留算法与历史费用结论，见 context-engineering |
| P5B | 官方 PG Checkpoint、持久预算/Artifact、恢复与故障验证已交付 | 历史停止点；P6B 复用原 Journal/Saver，不重写恢复 |
| P6A | 授权 TXT/Markdown、固定 BGE CPU、真实 pgvector/MCP 与引用验证已实现；定向补强完成控制和恢复 | 历史停止点；检索成功与最终业务验证分开 |
| P6B | 可信 ReportScope、P3/P4 桥接、验证引用/claim/Markdown/图表、受限结果与恢复 | 当前停止点；真 PG 与脚本模型决策验收见 cross-source-report；无新增真实模型授权 |
| P6C | API、UI、Langfuse | 未开始，须独立授权 |
| P7 | 独立 E2E、消融、Claude Code 产品对比 | Gate D 完整验收资料；不可污染保留集 |
| P8 | 可选官方 Runtime 不足与 Fork A/B | 有最小复现和公开方案不足的证据 |
| P9 | 可选干洗店领域包/真实试点 | Gate D、数据授权/导出能力明确；不依赖 Fork |

## 5. 评测设计与完成判定

SaaS ≥50 个独立业务任务，开发集/保留集分离，固定 seed/数据 manifest、Gold SQL/人工口径、预期指标/拒答条件、证据规则与模型设置。覆盖单表/JOIN、上传异常、日期/单位/指标、RAG、缺证据、权限、故障、恢复与多轮。Gold 不从 Agent 轨迹反推。

分别报告：执行成功、数据/业务正确、证据覆盖、可恢复错误的恢复率及分母、p50/p95、Token/费用估算、样本数/置信区间、人工介入。目标阈值在实验前登记，未达到如实记录；原文 90%/95%/80% 等是候选目标，不是已测结果。

消融按原版 SQL→Worker Loop→语义/Verifier/Recovery→Context/Memory→Multi-Agent 比较，同模型/数据/预算。Claude Code 是端到端产品对照，披露模型、允许工具、导入准备与人工操作差异，不能直接归因 Harness。Fork 对照固定同一 Harness，负收益默认回退官方版。干洗店试点单列 5–10 个经营者问题和人工复核，不与 SaaS 测试集合并。

## 6. 当前阻塞与下一步准备

P1–P6A 保留，P3 指标入口独立；ask 保留快速 SQL/内存执行，durable 沿用官方 Saver。P6B 已通过显式 ReportScope 接通 P3→P4 的报告链，真实 RAG 和 P3 引用恢复均保持原授权与 verdict；普通 ask 未配置 ReportScope 仍不把任意查询升级为业务 verified。停止在 P6B。UI/Langfuse、长期 Memory、P11 引擎未实现；真实模型复杂分析质量、独立保留集与产品对照尚待后续授权。

### 已完成的 D9–D13 / 后续边界

- 完成严格 Plan/DAG、就绪/能力调度、Send/Command、独立 Worker 子图、确定性 Analysis/引用汇总、有界 Replan、父子预算与取消、真实异步工具协议和脱敏 Trace。
- 简单 SQL 走低成本 fast plan；复杂双 SQL 可以在真实 MCP/PG 执行。SQL/RAG 并发用显式检索组件替身验证，真实 RAG 留在 P6。
- 未变源任务可显式验证后复用；权限/预算/输入错误不重规划绕过。旧 SQL 安全链与三项历史迁移保持原状。
- D11–D13 / P5A/P5B：受限 Memory 契约、上下文压缩、官方父/子图 Checkpoint、原子持久预算与完整工件、跨进程恢复已实现；未实现永久 Memory 存储。停止，不推进 P6/P7。

DeepSeek 非思考 profile 已有真实 SQL smoke、P5A 压缩 A/B 和 P5B 恢复实测，不代表完整业务评测或产品领先。Embedding、Langfuse 和后续指标/报告集成需在对应 Gate 验证。PG Saver 迁移已由 ADR-009 明确并显式部署。POS 软件和报表未知只阻塞 Phase F，不阻塞 SaaS；不退回 SQLite/FAISS。
