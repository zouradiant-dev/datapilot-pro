# DataPilot Pro

面向 SaaS 企业的智能经营分析系统，当前已实现 **Day 1：SQL 基线**、**P1：CSV/XLSX 解析确认**、**P2：受限入库与动态 MCP**、**P3：SaaS 指标/证据验证**、**P4 / D9–D10：动态任务 DAG 与双层执行**。业务数据库使用 **PostgreSQL 17 + pgvector**，运行期业务查询全部经过真正的 MCP Server/Client。

实现：固定种子、Alembic、隔离角色、AST/只读/资源限制、指标证据、LangGraph 动态 DAG/Send、独立 SQL/RAG Loop、父子预算/取消、L0–L4、脱敏 Trace 和 CLI。P5B 提供官方 PG Checkpoint、持久预算/工件和跨进程恢复；P6A 提供授权 TXT/Markdown 摄取、本地真实 BGE Embedding 与同实例 pgvector/MCP 检索。完整业务 Report Agent、API/UI 与观测平台尚未实现；旧 RAG fixture 仍只用于编排回归。

详见 [架构与目标设计](docs/architecture.md)、[v2 Gate 路线图](docs/roadmap-v2.md)、[本轮代码审计与回归](docs/planning-audit-v2.md)、[开发约束](AGENTS.md)、[Day 1 历史验收记录](docs/day1-delivery.md)。

v2 目标闭环：**CSV/XLSX 上传 → Schema 预览确认 → 受限入库/数据集版本 → 动态 MCP 查询 → 语义指标与证据验证 → 多 Agent 报告**。P4 已落实固定拓扑的外层调度与任务局部 Worker 子图；P5B 实现执行持久化。完整跨来源业务报告、长期 Memory 后端仍按后续 Gate 演进。P3 指标入口独立保留。

首发聚焦 SaaS，本地单用户/可信演示。后续干洗店等行业经 Domain Pack 复用引擎，POS 品牌/API/报表未知；LangGraph Fork 有实证必要时独立研究。两者不作为 SaaS 交付前提。旧七天安排已替换为按依赖和验收推进的 Gates，编号不构成日期承诺；当前停止在 P6A，未进入 P6B/P6C/P7，Gate C 尚缺可信跨来源业务报告桥接。

P4.1 在现有组件上增加受控工具生命周期、宿主 `completion` 三态、完整工件先保存的 L0 模型视图与上下文计量。`status=succeeded` 仍表示工具执行成功；业务指标缺少 P3 六层已验证证据时 `completion=blocked`，不能当作已验证报告。简单客户数查询仍只需两次 Fake 决策。历史记录见 [P4.1 交付](docs/p4-hardening.md)。

P5A 复用 Gateway/ArtifactStore/父子账本，实现 L1 旧工具视图裁剪、L2 引用去重、L3 完整工具轮次折叠、受预算和校验约束的 L4 摘取式摘要；原消息与证据保持完整，默认小查询不触发压缩。Memory 仅有经审阅的受限契约及内存实现，来源/版本/有效期/撤回均须校验。详见 [上下文工程与实测](docs/context-engineering.md)。P5B 只增加持久适配，不重新优化 L4。

## 持久执行与恢复（P5B）

P6A 的有界 TXT/Markdown 文档链路、固定 512 维中文 BGE 模型、独立 RAG 只读角色和可追溯引用已接入相同 Durable/MCP 边界，见 [RAG 部署与 Demo](docs/rag-pipeline.md)、[P6A 交付](docs/p6a-delivery.md)。Embedding 在本地真实推理，无需 API Key；MCP 不自动下载模型、不接收 scope/DDL/文件工具参数。模型权重缺失/hash 错误明确失败，原 fixture 不冒充真实检索。

真实 PG/本地神经 Embedding/MCP 与 Fake 决策下的恢复测试通过；两次真实 DeepSeek RAG smoke 分别因交付格式和检索次数上限失败，尚不能宣称真实模型自主 RAG 任务通过。保留错误与实际用量，不降低引用/权限校验以获取成功状态。

已有数据库先增量部署，保留旧数据：

```powershell
uv run --locked python scripts/configure_local.py --add-runtime-roles
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot runtime-init
$runId = [guid]::NewGuid().ToString()
uv run --locked datapilot durable start $runId --question '查询客户总数' --mode fake --pause-after worker
uv run --locked datapilot durable resume $runId --mode fake
```

普通 ask 保留内存模式；durable 采用官方父/子图 Checkpoint、独立元数据角色、事务预算和完整工件。已提交响应可复用，未确认执行返回 RECOVERY_UNCERTAIN 并保守保留预算；不承诺供应商 exactly-once。真实 PG 跨进程故障与真实 DeepSeek 两次调用恢复实测见 [部署/协议](docs/recovery.md)、[交付记录](docs/p5b-delivery.md)。没有自动删库、永久 Memory 后端或生产多租户实现。

补充 [DeepSeek 真实压缩 A/B](docs/p5a-live-context-ab.md)：20 次调用、75,304 tokens，受控长回放中 L3 总 Token 减少 75.12%；L4 计入摘要后减少 32.21%，但本样本估算费用和耗时增加。短查询未触发压缩。以上为小样本真实 API + 部分合成历史，不是完整 SaaS 任务基准或稳定省费承诺。

## 双层执行与 Trace（P4，需要真实 PostgreSQL）

Planner → Scheduler → Send Worker → Verifier → Finish/Replan。简单已知 SQL 意图跳过规划模型，Worker 用两次决策完成查询和引用确认；复杂任务按能力和依赖分波次执行。所有数字计算由 SQL/Decimal 完成，模型只选工具与实际证据引用。

```powershell
uv run --locked datapilot ask '查询客户总数' --mode fake --json
uv run --locked datapilot ask '查询客户总数，并计算2025-10收入' --mode fake --json
uv run --locked python scripts/trace_orchestration_demo.py --output artifacts/my-two-sql.json
uv run --locked python scripts/trace_orchestration_demo.py --with-rag-fixture --output artifacts/my-rag-fixture.json
```

Fake 只产生计划/工具决策，SQL 仍走真实 MCP/PG；RAG 示例显式标注 fixture，默认 ask 不启用替身。`--json` 可导出本地执行工件和 Trace，Trace 本身不含原始 SQL/业务行。Live 模式现在需要供应商支持原生 tool calling；本轮 HTTP Mock 证明异步协议/并发，未声称真实 LLM 通过。完整接口、源码借鉴和边界见 [编排说明](docs/orchestration.md)、[交付记录](docs/p4-delivery.md)、[ADR-006](docs/adr/0006-two-level-orchestration.md)。

## DeepSeek Flash 最小接入

在忽略的 `.env` 中配置以下内容；API Key 只写本地，不发送到聊天或提交 Git：

```dotenv
DATAPILOT_LLM_MODE=live
DATAPILOT_MODEL_PROVIDER=deepseek
DATAPILOT_BASE_URL=https://api.deepseek.com
DATAPILOT_MODEL=deepseek-flash
DATAPILOT_API_KEY=
```

填写自己的 Key 后执行 `uv run --locked datapilot ask '查询客户总数' --mode live --json`。该适配显式关闭思考模式，使用 Chat Completions/native tools，并发送 DeepSeek 的 `max_tokens`；通用供应商仍使用默认的 `openai_compatible` profile。预算、取消、工具权限与真实 MCP 不变，无 Key 时明确失败。HTTP Mock 与真实 PG/MCP 回归通过；2026-10-21 补充真实 DeepSeek 客户数 smoke：240 客户、completion=completed，2 次调用/2297 tokens。不代表复杂指标或完整业务报告已验收，详见 [接入与验证](docs/deepseek-transport.md)。

## 文件预览与确认（P1，无需数据库或 API Key）

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked
uv run --locked datapilot ingest preview tests/fixtures/ingestion/customers_utf8_bom.csv --header present
New-Item -ItemType Directory -Force artifacts | Out-Null
uv run --locked datapilot ingest preview tests/fixtures/ingestion/saas_multi_sheet.xlsx --header present --output artifacts/preview.json
uv run --locked datapilot ingest confirm tests/fixtures/ingestion/saas_multi_sheet.xlsx --proposal artifacts/preview.json --reviewed --output artifacts/confirmation.json
```

保留前导零、Decimal 精度、空列/重复列/中文原名映射，报告缺值/重复/IQR 异常及待确认关系；类型建议经全列验证。公式保留文本，宏与外部关系拒绝，ZIP/XML/行列/解码内容/预览均有配额。确认时重新读源并验证覆盖配置，输出不是入库授权；文件已存在不会覆盖。详情及限制见 [P1 使用说明](docs/data-ingestion.md) 与 [真实验收](docs/p1-delivery.md)。

框架研究：[LangGraph / Mini Claude Code 能力对照与融合方案](docs/framework-research.md)、[源码索引](docs/source-reference-index.md)、[后续 Fork 研究门槛](docs/langgraph-fork-research-plan.md)。当前保留原版 LangGraph；研究方案与已实现能力分开记录。

## 文件入库与动态查询（P2，需要真实 PostgreSQL）

已有 Day 1 环境先升级配置与 Schema，保留旧密码和数据；**不要重新 Seed**：

```powershell
uv run --locked python scripts/configure_local.py --add-upload-roles
uv run --locked python scripts/configure_local.py --add-registry-role
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot health
```

新环境按下一节一次初始化即可。P2 使用 `catalog` 四表和独立 `uploads`；P3 的 0003 增加语义/指标/证据，P5B 的 0004 增加 execution，P6A 的 0005 增加版本化文档/向量，当前 head 为 `0005`；历史 `0001`–`0004` 未修改。

```powershell
$demoDir = 'artifacts/demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Force $demoDir | Out-Null
$sourceFile = 'tests/fixtures/ingestion/invoices_semicolon.csv'
uv run --locked datapilot ingest preview $sourceFile --header present --output "$demoDir/preview.json"
uv run --locked datapilot ingest confirm $sourceFile --proposal "$demoDir/preview.json" --reviewed --output "$demoDir/confirmation.json"
uv run --locked datapilot ingest import $sourceFile --confirmation "$demoDir/confirmation.json" --name 'SaaS invoices' --output "$demoDir/import.json"
$datasetId = (Get-Content "$demoDir/import.json" -Raw | ConvertFrom-Json).dataset_id
$datasetSchema = uv run --locked datapilot datasets schema $datasetId | ConvertFrom-Json
$tableName = $datasetSchema.tables[0].physical_name
uv run --locked datapilot datasets query $datasetId "SELECT COUNT(*) AS invoices,SUM(amount) AS total FROM $tableName"
uv run --locked datapilot datasets list --dataset $datasetId
```

合成 CSV 示例结果为 3 张账单、精确金额字符串 `1213.4400`。XLSX 可用同样的 preview/confirm/import 流程，多 Sheet 表名从 schema 输出获取，可在同一 Dataset 内 JOIN。自然语言 `ask` 仍走原 SaaS 路径；P2 提供显式 SQL 查询入口，不声称完成上传数据的自主分析 Agent。

导入仅用隔离的 `datapilot_ingest`，重新验证原件/确认后事务化建表、批量写入、登记和授权。模型侧仅有 `datapilot_upload_reader`；DatasetScope 由可信宿主注入，工具参数不能扩权。重复导入相同确认复用版本，新内容/映射保留旧表并产生新版本；`datasets schema/query --version N` 在宿主固定历史版本，`datasets activate ID --version N` 只修改当前指针。详情与边界见 [P2 使用说明](docs/dataset-ingestion.md)、[P2 实际验收](docs/p2-delivery.md)。

## SaaS 指标与可复核证据（P3）

映射和口径分别经用户确认并版本化；收入、客户净流失、订阅流失、活跃合同、使用量由受控 SQL 与原始列 Python 独立复算。MRR 不用账单收入替代，缺信息/历史/覆盖范围或零分母明确不能计算。通过六层校验的报告数字均绑定 Evidence/Verification ID。

已有环境先执行上面的 Registry 角色升级、db-init 和 migrate。无需模型 Key 的合成 Demo：

```powershell
$demoDir = 'artifacts/semantic-demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
uv run --locked python scripts/prepare_semantic_demo.py --reviewed-synthetic --output $demoDir
uv run --locked datapilot semantics run "$demoDir/requests.json"
```

这是明确标记的 `deterministic` 执行；不冒充真实 LLM E2E。入口为显式版本化请求 JSON，原 `ask` 保留 Day 1 路径。完整确认/证据读取/公式/配额与限制见 [P3 使用说明](docs/semantic-metrics.md)、[P3 交付](docs/p3-delivery.md)、[ADR-005](docs/adr/0005-semantic-registry-verifier.md)。

## 本地运行

要求 Python 3.11–3.13、uv、Docker Desktop（Windows 使用 WSL 2/Linux containers）。Linux/macOS 使用 Docker Engine + Compose 亦可。

以下 PowerShell 命令在仓库根目录执行。项目采用精确 editable 导入以支持中文路径；开启 UTF-8 可保留中文输出。

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked --python 3.11
uv run --locked python scripts/configure_local.py
docker compose up -d --wait
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot seed
uv run --locked datapilot health
```

`configure_local.py` 用独立随机密码创建被忽略的 `.env`，拒绝覆盖；默认数据库绑定 `127.0.0.1:55432`。它不创建模型 API Key。也可参考 `.env.example` 自行配置；密码中特殊字符需 URL 编码。

四条数据库命令独立：`db-init` 使用管理员创建权限/扩展；`migrate` 使用 Owner 执行 Alembic 并精确授权；`seed` 仅 INSERT，非空库拒绝；`health` 使用 Reader 检查 PG17/扩展/权限/种子。初始化/迁移可重复执行，Seed 不可重复覆盖。不需要通过清卷来“重试”。

```powershell
uv run --locked datapilot ask '查询客户总数' --mode fake
uv run --locked datapilot ask '计算2025-10收入' --mode fake
uv run --locked datapilot ask '查询2025-07-01到2025-10-01新增订阅' --mode fake
uv run --locked datapilot ask '按客户分群查询活跃订阅 JOIN' --mode fake --json
```

Fake 只覆盖以上确定性问题模板，输出 SQL 后仍通过真实 MCP 查询真实 PostgreSQL；没有数据库就失败。Fake 路由/SQL 不证明真实模型推理能力。收入为 paid 账单的整数 **CNY 分**，区间右端不包含。数据固定为 2025 年，默认 240 客户。

开启真实模型：编辑本地 `.env`（不要提交）或设置环境变量：

```powershell
$env:DATAPILOT_LLM_MODE = 'live'
$env:DATAPILOT_API_KEY = '<你的 API Key>'
$env:DATAPILOT_BASE_URL = '<供应商 OpenAI-compatible v1 地址>'
$env:DATAPILOT_MODEL = '<供应商模型 ID>'
uv run --locked datapilot ask '查询客户总数' --mode live --json
```

`--json` 返回 SQL、结果、状态、错误、节点路径、时延、Token 使用。默认限制见 `.env.example`，SDK 隐式重试关闭。Qwen/DeepSeek 的供应商兼容性需真实凭据验证；HTTP Mock 测试不能替代该验证。

## 自动化验证

```powershell
# 纯生成器、AST、模型 HTTP Mock、Worker/Graph Mock、真实 MCP 无数据库协议
uv run --locked pytest -m 'not integration and not live' -q

# 必须先启动、初始化、迁移、seed 真 PostgreSQL 17 + pgvector
$env:DATAPILOT_RUN_DB_TESTS = '1'
uv run --locked pytest -m 'integration and not live' -q

# 真实模型+MCP+PG；显式 opt-in，消耗 API Token
$env:DATAPILOT_RUN_LIVE_TESTS = '1'
uv run --locked pytest -m live -q

uv run --locked ruff check .
uv run --locked ruff format --check .
```

默认没有 `DATAPILOT_RUN_DB_TESTS=1` 时数据库测试明确 skip；一旦开启，连接/权限失败必须 fail。集成验收包括独立 SQL 对照客户数、月收入、区间订阅、JOIN、安全拒绝、错误字段、修复耗尽/成功、超时/截断、Reader grants、pgvector 写入与距离。向量测试事务回滚，不残留测试文档。

CI 配置使用真实 PG17/pgvector 服务，覆盖 Python 3.11/3.13。仓库尚未发布或 CI 尚未执行时，不能将配置存在称为 CI 通过。

## 安全边界与局限

MCP 仅注册只读数据库工具，SaaS/上传会话各拿自己的 Reader 凭据；模型看不到管理员、Owner、Seed、Ingest 或 Registry 凭据。Reader 无业务写权限、Schema CREATE、TEMP 或角色继承；AST 同时限制表、函数及语句。上传策略每请求绑定精确物理表，多个 Dataset 同时被选中也不允许单次请求跨 Dataset JOIN。数据库端显式只读事务、statement_timeout 与外层 LIMIT 独立生效。默认角色只读设置本身可以被修改，因此权限 grants 不可省略。

`.env` 是本机开发配置，stdio 子进程仍受宿主 OS 信任，不是对恶意宿主进程的沙箱。pgvector 存储表已迁移，文档摄取、Embedding、索引和 RAG 逻辑属于后续 Gate C；当前不运行独立向量服务。

v2 设计决策：[双层 Runtime/Harness](docs/adr/0001-runtime-harness.md)、[动态导入与权限](docs/adr/0002-ingestion-permissions.md)、[单用户边界](docs/adr/0003-local-single-user.md)、[指标/证据与领域包](docs/adr/0004-metrics-evidence-domain.md)。固定结构由 Alembic 管理，上传动态表仅由受限 Ingestion Service 管理，模型不会取得 DDL 权限。可观测性计划采用 Langfuse，目前尚未安装或集成。

`docker compose stop` 暂停数据库，`docker compose start` 恢复。**不要执行带 `-v` 的 down 或自动清库脚本**，持久数据保存在项目命名卷。
