# Day 1 实际交付记录

验收日期：2026-10-20（Asia/Shanghai）。项目：`D:\桌面\llm-learning\datapilot-pro`。本记录基于实际命令执行，不包含真实模型推理通过的声明。

历史记录说明：下文的 Docker/分支/CI 状态和当时下一步建议属于 Day 1 快照，不代表当前环境。2026-10-21 最新回归见 [v2 规划审计](planning-audit-v2.md)，现行阶段安排见 [Gate 路线图](roadmap-v2.md)。

## 完成范围

已按修订要求迁移到 PostgreSQL 技术栈，删除 SQLite 草稿。完成从 Supervisor、独立 SQL Worker、真实 MCP stdio Client/Server 到真实 PostgreSQL，再返回确定性 Markdown Answer 的闭环。

- 已安装独立 Python 3.11.16 和项目虚拟环境；锁定依赖图/哈希，构建后端 hatchling=1.27.0，修复 Python 3.11 中文目录 editable 导入。
- 已安装 Docker Desktop 4.95.0（当前用户），验证官方安装包 SHA256 与 Docker Inc. 签名；WSL 2.7.3/虚拟化可用，未重启 Windows。
- Docker Engine 29.8.2、Compose 5.6.0 已实际运行；容器 `datapilot-pro-postgres-1` healthy，绑定 `127.0.0.1:55432`，使用持久卷 `datapilot-pro_pgdata`。
- PostgreSQL 实际版本 17.11，pgvector 0.8.6；Compose/CI 均固定已验证镜像 digest：`sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`。
- 四类权限凭据独立，随机生成并保存在被忽略的 `.env`；初始化、迁移、Seed、健康检查均实际执行成功。Reader 无业务写权限、Schema CREATE/TEMP、角色成员关系；MCP 不接收管理和模型凭据。
- SQLGlot postgres 方言、表/函数/语句白名单、scope 感知 CTE、只读事务、服务端超时、行数/单元格/总输出限制。
- LangChain OpenAI-compatible 客户端，可配置模型/API 地址；JSON+Pydantic 严格输出、调用/Token/上下文/步数预算；SQL 编译错误有界修复，安全拒绝不重试。
- Git 仓库初始化为 main，未提交/推送；仅为该新目录添加 Windows 当前用户 Git safe.directory。`.env`、安装包、虚拟环境和运行产物均已验证被忽略。

实际锁定关键版本：LangGraph 1.2.16、LangChain 1.4.6、langchain-openai 1.7.2、MCP 1.30.0（1.x API）、SQLAlchemy 2.0.55、psycopg 3.3.6、Alembic 1.20.0、pgvector Python 0.4.2、SQLGlot 30.23.0、Pydantic 2.14.1、pytest 9.1.1。完整依赖以 `uv.lock` 为准。

## 实际创建的目录与文件

```text
datapilot-pro/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env.example
├── compose.yaml
├── alembic.ini
├── .github/workflows/test.yml
├── docs/
│   ├── architecture.md
│   └── day1-delivery.md
├── migrations/
│   ├── env.py
│   └── versions/0001_business_and_vectors.py
├── scripts/configure_local.py
├── src/datapilot/
│   ├── __init__.py
│   ├── config.py
│   ├── contracts.py
│   ├── state.py
│   ├── graph.py
│   ├── cli.py
│   ├── agents/{__init__,supervisor,sql}.py
│   ├── data/{__init__,generator}.py
│   ├── db/{__init__,schema,management,health}.py
│   ├── harness/{__init__,budget,context,verification}.py
│   ├── llm/{__init__,client,fake}.py
│   ├── runtime/{__init__,mcp_client,mcp_server}.py
│   └── tools/{__init__,sql}.py
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_data.py
    ├── test_sql_policy.py
    ├── test_harness.py
    ├── test_model_http.py
    ├── test_worker_graph.py
    ├── test_mcp_protocol.py
    ├── test_postgres_integration.py
    └── test_live_model.py
```

另有本地运行文件：`.env`、`.venv/`、`.cache/DockerDesktopInstaller.exe`、`artifacts/day1-tests.xml`、`artifacts/day1-customer-count.json`。这些文件被忽略，不属于待提交源文件；测试报告和示例 JSON 可供本地复查。独立 Python 和 uv 缓存位于工作区 `.datapilot-python`/`.datapilot-uv-cache`。

## 数据与健康检查实测

| 项目 | 实际值 |
|---|---:|
| customers | 240 |
| subscriptions | 279 |
| invoices | 2,271 |
| usage_events | 6,813 |
| customer_feedback | 279 |
| churned 订阅记录 | 45 |
| downgraded 旧订阅记录 | 39 |
| active 订阅记录 | 195 |

种子 42，固定 2025 年，逻辑内容 SHA256：`e003dadfabdb362d6bfa3739650b587fae784b37bba31dec713844e840b93029`。金额单位 CNY 分；订阅状态为该记录的生命周期状态，不等同于某个历史月的活跃快照。

应用健康结果：status=healthy、postgres_version_num=170011、pgvector=0.8.6、migration=0001、customers=240、seeded=true。

## 测试命令与真实结果

最终执行（已配置本地 `.env`，PowerShell）：

```powershell
$env:PYTHONUTF8 = '1'
$env:DATAPILOT_RUN_DB_TESTS = '1'
uv run --locked --offline pytest --cov=datapilot --cov-report=term-missing --junitxml=artifacts/day1-tests.xml -q -p no:cacheprovider
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
```

实际结果：**59 passed, 1 skipped in 16.17s**。主进程行覆盖率 **84%（783 statements，124 missed）**；真实 stdio MCP Server 子进程未合并到 coverage，因此该文件显示 0%，不能将该数值误解为子进程未实际执行，也不能声称全进程覆盖率 84%。CLI 初始化/迁移/Seed 和四条演示命令亦另行实际执行。

ruff check：All checks passed；最终 ruff format：44 files already formatted。

测试分类：

| 分类 | 证据与限制 |
|---|---|
| 单元/Mock | 生成器、AST、预算、契约、上下文隔离、Worker/Graph；不代表真实数据库/模型 |
| Mock HTTP | 真实 LangChain/SDK 经 httpx.MockTransport 验证 OpenAI-compatible 协议；不做真实推理 |
| protocol | 真实 MCP 子进程、握手、工具列表、缺失 DB 状态与权限白名单；无数据库替代物 |
| integration | 10 项真实 PG17+pgvector 测试，含 4 个独立 SQL 对照任务、角色权限、MCP 拒绝/字段错误/修复、超时/截断、FK/CTE、向量距离、初始化重入与 CLI |
| live | 1 项明确跳过：无 API 凭据且未启用 DATAPILOT_RUN_LIVE_TESTS；没有真实模型 E2E 验证 |

验收要求对应：

| 要求 | 结果 |
|---|---|
| 客户总数 | 真实 MCP+PG，独立 SQL 核对 240 |
| 指定月收入 | 真实 MCP+PG，独立 SQL 核对 2025-10 paid 账单 20,338,800 分 |
| 区间新增订阅 | 真实 MCP+PG，独立 SQL 核对 [2025-07-01,2025-10-01) 为 43 |
| JOIN 业务查询 | 真实 MCP+PG，分群活跃订阅结果一致 |
| 拒绝危险 SQL | 真实 MCP 拒绝 DELETE；AST 参数化覆盖写入/副作用/系统表等，数据库独立 grants 拒写 |
| 不存在字段 | PostgreSQL 实际编译错误映射 SQL_EXECUTION_ERROR |
| SQL 失败明确状态 | 修复耗尽 failed、无结果；修复成功 attempts=2；安全拒绝不重试 |

## 成功运行的示例

均实际执行以下 CLI，模式为 **Fake 模型 + 真实 MCP + 真实 PostgreSQL**：

```powershell
uv run --locked datapilot ask '查询客户总数' --mode fake
# mode=fake status=succeeded; customer_count=240

uv run --locked datapilot ask '计算2025-10收入' --mode fake
# mode=fake status=succeeded; revenue_cents=20338800（203,388.00 CNY）

uv run --locked datapilot ask '查询2025-07-01到2025-10-01新增订阅' --mode fake
# mode=fake status=succeeded; new_subscriptions=43

uv run --locked datapilot ask '按客户分群查询活跃订阅 JOIN' --mode fake
# mode=fake status=succeeded; enterprise=69, midmarket=69, small=57
```

Fake 只生成路由/SQL，没有把这些结果写入 Prompt 或 Fixture；数值由数据库实际执行产生。`--json` 可查看 SQL、结构化数据、路由轨迹、错误、时延与预算统计。本地 `artifacts/day1-customer-count.json` 是一次已保存的实际查询。

## 未实现功能、风险与下一阶段

未实现：RAG 摄取/Embedding/检索与引用，Analysis/Report Worker，动态任务 DAG/并发，完整确定性指标/证据一致性验证、局部重规划、持久 Checkpoint、OTel/LangSmith/回放、FastAPI、Streamlit、完整应用容器、30–50 个独立业务任务评测。现在的 SQL 安全/预算测试数量不能冒充 Day 6 的独立业务任务评测。

技术风险与边界：

1. 缺少模型 API 凭据；Qwen/DeepSeek 的 JSON 稳定性、真实任务规划、SQL 泛化和 Token 计费未验证。供应商 usage 缺失时预算是保守估算，不能保证供应商账单上限。
2. AST 是白名单策略，当前有意限制函数与查询特性；SQLGlot 版本升级需保持回归测试，数据库权限和超时不可省略。数据库管理员属于信任边界。
3. stdio 传递最小环境不等于 OS 安全沙箱；生产部署需把 MCP Reader 与运维密钥放在不同容器/Secret 边界，增加 API 身份认证与访问控制。
4. pgvector 表目前为无固定维度 VECTOR，Day 3 需先选 Embedding 模型，再迁移维度/模型隔离与 ANN 索引；当前仅验证存储和距离，未验证检索质量。
5. 当前只有节点路径/时延、结构化结果与模型计数，没有完整跨模型/工具 span、持久回放或恢复预算。
6. 本机只验证 Python 3.11.16/Windows；CI 文件覆盖 3.11/3.13，但尚未发布到 GitHub 执行，不能称 CI 已通过。部分异常路径和真实模型分支仍未覆盖。
7. 数据为合成样本，流失与反馈是人为关联，不能做真实企业因果推断；收入是现金账单口径，非 MRR。

当时建议下一步按 Day 2 实现任务 DAG/依赖，再按 Day 3 实现 pgvector RAG；该七天安排现已由 [v2 Gate 路线图](roadmap-v2.md) 取代，当前下一阶段是 P1 安全文件解析与预览确认。真实模型验证需后续在本地配置 API 环境变量，无需训练模型。
