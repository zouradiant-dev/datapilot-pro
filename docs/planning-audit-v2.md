# v2 规划审计与实际回归记录

日期：2026-10-21（Asia/Shanghai）。范围：P0，只读代码审查、原测试回归、架构/路线图/ADR 更新；不实现新业务功能。

## 1. 审阅范围与证据位置

基线 HEAD `3a47d27a5920721b3d776d62de6b240c0a313213`，工作目录为 datapilot-pro。启动时已存在上一轮框架研究的文档/探针未提交改动，本轮保留并承接；不能把所有工作树差异都归为本轮新建。

完整审阅 README.md、AGENTS.md、docs/architecture.md、docs/day1-delivery.md、pyproject.toml、`src/datapilot/` 全部 27 个 Python 文件、`tests/` 全部 10 个 Python 文件（含 conftest）。补查两份迁移文件、Compose/CI、锁定安装版本与固定源码快照。文件数包含只声明模块说明的 __init__，不代表功能模块数。

Mini Python agent.py/tools.py/subagent.py/memory.py 延续已固定快照的实现核查，本轮补读 autonomy.py 的目标判断、循环限制、分类器输入/失败关闭机制；未运行该仓库工具或复制其实现。本轮不改 LangGraph site-packages，不创建 Fork。具体链接见 [源码索引](source-reference-index.md)。

忽略的本地原始证据：`artifacts/planning-audit-20261021/`，包含 baseline.json、四类 pytest XML/日志、Ruff 日志及最终完整性检查。提交的摘要只记录非敏感版本、命令和结果；不含 DSN/Key/真实上传数据。

## 2. 实际实现与缺口

| 模块/代码位置 | 已核实行为 | 缺口与对应 Gate |
|---|---|---|
| `data/generator.py:22,126` | 固定 seed/日期，五表相关合成现象；空库事务 Seed、互斥、拒覆盖 | 无 CSV/XLSX/版本/业务记录幂等，Gate A |
| `db/schema.py:6,109` | 五表常量，rag 无固定维度向量存储 | 无 Registry/语义/证据结构；不代表 RAG 可用，A/B/C |
| `db/management.py:25,78` | admin/owner/seed/reader 分离、精确授权、独立初始化 | 无 ingest/upload_reader；不能让 Reader 获得导入权限，A |
| `db/health.py:22`、`cli.py:47` | 健康检查/迁移输出固定 0001 | 新迁移需兼容升级，不改历史快照，A |
| `tools/sql.py:87,143,229` | PostgreSQL AST/表函数/cast 限制、Reader 验证、只读、超时/行/字节限制 | 静态 saas 白名单/固定 search_path，需按可信 QueryScope 扩展，A |
| `tools/sql.py:77` | 指标定义是固定 METRICS 文本 | 无用户确认/版本/正式客户流失口径，B |
| `runtime/mcp_server.py:10`、`mcp_client.py:29,72` | 真实 SDK stdio，固定 3 工具，最小环境、调用超时/输出校验 | 无数据集绑定/动态 Schema/检索或计算工具/身份接口，A/C |
| `agents/supervisor.py:19`、`graph.py:38,130` | route sql/unsupported，四节点链，compile 无 Saver | 无 Planner/DAG/Send/replan/interrupt/持久恢复，C |
| `agents/sql.py:23` | 独立 SQLTask、真实 Schema、可重试编译错误最多一次修复（默认） | 不是完整多工具消息 Loop；不做业务复算，B/C |
| `llm/client.py:30,37` | JSON/Pydantic；同步 LangChain invoke，SDK 重试关闭 | async 图内阻塞；无工具消息/流式取消，C |
| `harness/budget.py:9` | 每运行内存调用/Token 预留、未知 usage 保守计费 | 无并发原子性/恢复账本/工具总次数与费用模型，C |
| `harness/context.py:6` | 超长直接拒绝，安全文本不静默截断 | 无按需 Schema、ArtifactRef、分层压缩/Memory，C |
| `harness/verification.py:8`、`contracts.py` | task_id、形状、行数与终态不变量 | 无语义/独立复算/证据存在/目标覆盖，B |
| `graph.py:89,167` | Markdown 表格转义，基础节点时延/错误/usage | Answer 非 Report；宽泛异常可能误归 MCP；无完整 Trace，C/D |
| `tests/` | 60 个收集用例，含参数化、真实 MCP、10 项真实 PG、1 项 opt-in live | 不等于 60 个独立业务问题；无 v2 导入/业务/长流程 benchmark，D |
| `pyproject.toml` | 单一 uv.lock 依赖基线，CLI，pytest/Ruff | 无 openpyxl、Langfuse、PG Saver；没有 FastAPI/Streamlit 产品代码，A/C/D |

## 3. 改造冲突与依赖

| 冲突 | 处理结论 | 验收落点 |
|---|---|---|
| 固定 Alembic vs 每次导入动态表 | 固定 Schema 仍新迁移；uploads 动态表仅受限 ingest 事务 DDL | ADR-002 / A |
| BUSINESS_TABLES vs 用户表 | 显式 QueryScope/Policy；保留 saas，独立 upload profile，不全局放开 | A 越权/写入/版本测试 |
| 0001 硬编码 vs 新迁移 | 升级 health/CLI 的 head/兼容检查；历史迁移不改 | A 迁移回归 |
| 当前 Owner 无数据库 CREATE vs 新 namespace | 显式 admin 初始化 catalog/uploads 与所有权，再用 Owner 迁移固定表；不无谓扩大 Owner 权限 | ADR-002 / A |
| 同步模型调用 vs async 并发/取消 | async adapter 或受限执行器，真实并发/取消测试 | C |
| 内存预算/列表 trace vs Checkpoint 恢复 | 原子共享账本、引用/版本、稳定调用 ID、成功任务复用 | C 重启/故障注入 |
| Saver.setup 自带 DDL vs Alembic | 实施前专门迁移决策；不在 Worker/请求自动建表 | C 前置未决项 |
| Prompt 指标 vs 用户口径 | Domain/Metric 版本确认，独立复算，不以 SQL 成功当正确 | B |
| Mini 子模式/预算 vs 本项目约束 | 可复用代码，外层 MCP 与总预算不可绕过 | C |
| SQL/RAG 并发早于真实检索 | 替身只证明编排；C 完整验收补真实 pgvector 引用 | C/P6 |
| 旧计划/文档状态 vs 真实能力 | README 区分实现/目标；旧 Day 1 记录保留历史属性 | 本轮文档 |

依赖主线：安全解析/确认→Registry+受限入库→动态查询→指标/证据→自主任务与恢复→真实跨来源→产品/评测。Domain Pack/Connector 先定接口不预建空模块。Fork 与干洗店不是核心主线依赖。

## 4. 环境与本轮真实测试

实际环境：Windows、Python 3.11.16；LangGraph 1.2.16、checkpoint 4.3.0、LangChain 1.4.6、langchain-openai 1.7.2、MCP 1.30.0、SQLAlchemy 2.0.55、psycopg 3.3.6、Alembic 1.20.0、SQLGlot 30.23.0、Pydantic 2.14.1、pytest 9.1.1。锁文件/依赖未变。

命令在仓库根目录执行，设置 `PYTHONUTF8=1`。pytest 都使用 `-q -p no:cacheprovider`，并通过 `--junitxml=artifacts/planning-audit-20261021/<分类>.xml` 保留证据。

| 命令主体 | 实际结果 | 验证边界 |
|---|---|---|
| `.\.venv\Scripts\python.exe -m pytest -m 'not integration and not live and not protocol'` | **48 passed, 12 deselected in 2.28s** | 单元/Mock/Mock HTTP，不代表真实模型 |
| `.\.venv\Scripts\python.exe -m pytest -m protocol` | **1 passed, 59 deselected in 3.34s** | 真实 MCP 子进程/握手，无业务 DB |
| `.\.venv\Scripts\python.exe -m pytest -m 'integration and not live'`，`DATAPILOT_RUN_DB_TESTS=1` | **10 passed, 50 deselected in 12.52s** | 真实 PG17+pgvector，部分路径 Fake 模型+真实 MCP |
| `.\.venv\Scripts\python.exe -m pytest -m live`，DB opt-in=1、live opt-in=0 | **1 skipped, 59 deselected in 2.04s** | 无已配置真实模型凭据；未发起模型请求 |
| `.\.venv\Scripts\ruff.exe check .` | **All checks passed** | 静态检查 |
| `.\.venv\Scripts\ruff.exe format --check .` | **55 files already formatted**（最终文档写入后检查） | 格式检查 |
| `.\.venv\Scripts\python.exe -m datapilot.cli health` | **healthy；PG 170011、pgvector 0.8.6、revision 0001、customers 240** | 实际数据库可达与原角色/迁移检查 |

分类合计 **59 passed、1 skipped**，每个测试只属于上述一类；deselected 不计通过。集成测试包含初始化/迁移重入和 Seed 拒绝覆盖、独立 SQL 对照四业务问题、AST 拒绝/字段错误/修复、超时/截断、grants/FK/向量事务回滚。没有清库、删除卷或持久写入测试向量。

当前沙箱进程无法读取 Docker 用户配置/连接 Docker Engine named pipe；本轮未提升权限操作引擎。通过 TCP 的真实 PostgreSQL 健康检查及 10 项集成测试均成功，因此这不是数据库验收阻塞；不据此声称重新验证了 Docker Desktop UI/Engine 版本。GitHub CI、本机 Python 3.13 和真实模型未运行。

## 5. 完成范围与未完成

本轮交付路线图、分层目标架构、导入/权限/语义/证据/Domain Pack/Connector 契约和 4 项 ADR，更新开发约束与 README；保留上一轮源码研究成果。业务源码、测试、固定迁移、Compose、依赖及 site-packages 不修改。

本轮触及文件：

- 新增 `docs/roadmap-v2.md`、`docs/planning-audit-v2.md`、`docs/research/planning-audit-results.json`。
- 新增 `docs/adr/0001-runtime-harness.md`、`0002-ingestion-permissions.md`、`0003-local-single-user.md`、`0004-metrics-evidence-domain.md`。
- 更新 `README.md`、`AGENTS.md`、`docs/architecture.md`、`docs/day1-delivery.md`（后者仅加历史状态及现行路线指引）。
- 承接更新上一轮未提交的 `docs/framework-research.md`、`docs/source-reference-index.md`、`docs/third-party-references.md`、`docs/research/source-manifest.json`，对齐 v2 与补充 autonomy 核查。此前已有的 Fork 计划、离线探针及其原始结果不是本轮新建。

最终完整性检查：42 个业务/测试/迁移/依赖/Compose 文件哈希全部保持不变，27 个应用和 10 个测试文件完整审阅；55 个固定源码行号入口和 7 个已安装文件哈希核对成功。本轮 [机器可读摘要](research/planning-audit-results.json) 与本地原始日志可复核结果。

未实现：Parser/Profiler/Preview、动态入库/Registry、业务语义/证据存储、Worker DAG/Loop、RAG/计算/报告、持久化/Memory/恢复预算、API/UI/Langfuse、独立 benchmark、Fork 与干洗店试点。上述均是计划，不因本轮写出 ADR 就标为可用。

下一步 P1 的输入/输出、安全边界、反例和停止条件已在 [路线图 W2–W3](roadmap-v2.md) 定义；不存在必须先提供外部模型凭据的条件。尚需在 P1 内验证/锁定解析依赖和创建合成 fixture。本轮不自动进入 P1。
