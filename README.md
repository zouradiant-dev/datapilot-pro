# DataPilot Pro

面向 SaaS 企业的智能经营分析系统，当前仅实现 **Day 1：Supervisor + SQL Agent**。业务数据库从第一天使用 **PostgreSQL 17 + pgvector**，运行期访问全部经过真正的 MCP Server/Client。

实现：固定种子合成数据、Alembic 迁移、隔离角色、PostgreSQL AST 校验、只读事务、超时/行数限制、LangGraph 条件路由、有界 SQL 修复、严格结果契约和 CLI。RAG/Analysis/Report、多任务并发、API/UI 与完整 Trace 尚未实现。

详见 [架构与修订版七天计划](docs/architecture.md)、[开发约束](AGENTS.md)、[实际验收记录](docs/day1-delivery.md)。

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

MCP 仅注册固定数据库工具，子进程只拿 Reader 凭据；模型看不到管理员/Seed 凭据。Reader 无业务写权限、Schema CREATE、TEMP 或角色继承；AST 同时限制表、函数及语句。数据库端显式只读事务、statement_timeout 与外层 LIMIT 独立生效。默认角色只读设置本身可以被修改，因此权限 grants 不可省略。

`.env` 是本机开发配置，stdio 子进程仍受宿主 OS 信任，不是对恶意宿主进程的沙箱。pgvector 存储表已迁移，文档摄取、Embedding、索引和 RAG 逻辑在 Day 3 实现；当前不运行独立向量服务。

`docker compose stop` 暂停数据库，`docker compose start` 恢复。**不要执行带 `-v` 的 down 或自动清库脚本**，持久数据保存在项目命名卷。
