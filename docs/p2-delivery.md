# P2 / D4–D5 实际交付与验收

日期：2026-10-21，Windows / Python 3.11.16。前置为已验收 P1，代码基线为 `b599edee7fe22233f89dae141a71570c25bbac56`。本轮止于 Gate A：上传文件确认→受限 PostgreSQL 入库→Dataset 版本→真实 MCP 查询，不推进 P3 或多 Agent/UI。

## 文件与实现

新增：

- `migrations/versions/0002_dataset_catalog.py`：冻结的四表 catalog 快照；历史 `0001_business_and_vectors.py` 未改。
- `src/datapilot/db/catalog.py`：datasets/versions/tables/columns 元数据；动态 uploads 表不放进 Alembic metadata。
- `src/datapilot/ingestion/service.py`：原件与确认重验、hash 快照原子发布、受限类型/标识符、事务锁/DDL/批量插入/元数据/GRANT/ready、幂等与版本激活。
- `src/datapilot/datasets/{__init__,contracts,repository,cli}.py`：可信作用域 DTO、版本固定/元数据、每请求 SQLPolicy 与查询入口。
- `tests/test_dataset_policy.py`：32 项本地/Mock 边界测试；`tests/test_dataset_integration.py`：15 项真实 PostgreSQL/MCP 测试。
- `docs/dataset-ingestion.md`、本记录和 `docs/research/p2-results.json`。

修改：

- `db/management.py`、`db/health.py`、`migrations/env.py`：两种新角色/catalog/uploads、精确 grants、动态 head、双 Reader 健康检查；autogenerate 排除动态 uploads。
- `tools/sql.py`：保留 SaaS 默认五表，新增不可变 per-request SQLPolicy、上传 Reader 权限检查；继续 AST/READ ONLY/timeout/LIMIT/体积限制。QueryResult 增加明确 BOOLEAN 值支持，NUMERIC 仍作为精确字符串返回。
- `runtime/mcp_server.py`、`mcp_client.py`：新增三个只读 Dataset 工具、作用域/版本绑定与输出验证、严格环境隔离；正常领域异常在 SDK TaskGroup 正常关闭后重新抛出，不包装为不可识别的 ExceptionGroup。
- `cli.py`、`config.py`、`ingestion/cli.py`、`scripts/configure_local.py`、`.env.example`：operator-only 导入/版本激活与可信 Dataset 选择，配置升级不改旧密码；P1 preview/confirm 仍无数据库/模型配置依赖。
- `.github/workflows/test.yml` 增加两种 CI 专用身份；`tests/test_mcp_protocol.py` 只更新只读工具清单并断言无 DDL/文件工具。其余原测试未改。
- README、AGENTS、架构、路线图、ADR-002 与 P1 使用说明更新 P2 状态。未新增依赖，pyproject.toml 与 uv.lock 未变。

## 实际环境变更

对项目内被忽略的 `.env` 执行 `configure_local.py --add-upload-roles`，保留旧配置并补充两种独立随机凭据；未输出密码。实际 `db-init`、`migrate` 成功，既有库从 `0001` 升至 `0002`，未清库/删除 Volume/修改项目外文件。Health：PG `170011`、pgvector `0.8.6`、customers `240`、catalog 四表与上传 Reader healthy。

Snapshot 在忽略目录，数据库故障后保留用于对账；成功测试会保留独立合成 Dataset 版本，不删除旧业务数据。原件不是模型工具输入路径。

## 真实测试命令和结果

```powershell
$env:PYTHONUTF8 = '1'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/uv'
$env:DATAPILOT_RUN_DB_TESTS = '1'
$env:DATAPILOT_RUN_LIVE_TESTS = '0'
uv run --locked --offline pytest -q -p no:cacheprovider --basetemp=artifacts/p2/pytest-tmp-verified --cov=datapilot --cov-report=term-missing --cov-report=json:artifacts/p2/coverage-verified.json --junitxml=artifacts/p2/pytest-verified.xml
uv run --locked --offline ruff check . --output-format concise
uv run --locked --offline ruff format --check .
git diff --check
```

全量 **188 passed、1 skipped in 49.30s**。分类：

| 类别 | 结果 |
|---|---:|
| 既有单元/HTTP Mock/Worker/Graph | 48 passed |
| P1 本地解析/画像/确认 | 82 passed |
| P2 本地策略/确认/Mock 协议输出反例 | 32 passed |
| 既有真实 MCP stdio（无 DB） | 1 passed |
| 既有真实 PG17+pgvector / Fake 决策回归 | 10 passed |
| P2 真实 PostgreSQL+MCP | 15 passed |
| 真实模型 E2E | 1 skipped（没有 API 凭据且未 opt-in） |

真实 PG 覆盖 CSV/XLSX→确认→导入→MCP、同 Dataset JOIN、前导零/精确金额/布尔/时区、伪造 scope/跨 Dataset SQL、危险语句、角色写入/DDL/TEMP/提权拒绝、字段错误/空结果、完整事务回滚（新 Dataset 和已有版本）、并发幂等与首次快照、版本切换/会话固定、行截断/单元格体积/查询超时、真实 CLI 错误状态、原始表头注入与标识符引用。原 SaaS 客户数/月收入/区间订阅/JOIN 的独立 SQL 对照全部保留。

历史迁移另有固定 SHA256 回归。总用例数是工程测试，不等于独立业务 benchmark 数量。覆盖率是主 pytest 进程统计，MCP Server 子进程未纳入覆盖，不声称服务器代码未执行或分支全覆盖。

中间失败如实记录：驱动 SQL 中未转义的百分号已改为确定性字符串前缀比较；XLSX 源 XML 实为 `89.98999999999999`，测试改为对照原始精确值而不改数据/取整；真实 SDK 的部分响应只有 JSON 文本，测试采用协议规定的双格式；注入样例的 CSV 分隔符有歧义，按 P1 规则显式选择逗号。所有修复后重新跑完整回归，未删除失败用例或降低安全断言。

## 实际示例

按 README 使用 `invoices_semicolon.csv` 实际执行 preview→confirm→import→schema→query→list→重复 import→activate。结果：Dataset `2a25ca5c-937e-5667-8a87-e8f0e3b8dbbf`、version=1；`COUNT(*)=3`、`SUM(amount)="1213.4400"`；重复导入 reused=true，版本不增加。原 `ask 查询客户总数 --mode fake --json` 经原 MCP/PG 返回 240。CLI 不依赖真实 LLM。

机器摘要：[p2-results.json](research/p2-results.json)。原始 JUnit、coverage、基线哈希、CLI 命令/结果位于被忽略的 `artifacts/p2/`，原件位于 `artifacts/uploads/sources/`。

## 未完成与边界

- 未执行本轮 GitHub Actions 或 Python 3.13；CI 配置已保留真实 PG17 和双 Python 矩阵，本机结果不冒充云端通过。
- 未执行真实模型，上传数据目前经显式 Dataset SQL 查询；原自然语言 ask 仍针对 SaaS 固定表。
- 不包含 P3 的 Semantic Catalog、Metric/Evidence Registry、业务语义 Verifier、多 Agent、RAG 检索或 UI。
- 本地单用户、可信宿主；upload_reader 的数据库 SELECT 覆盖所有已发布上传表，逐 Dataset 边界由 Server scope+AST 实施，未实现生产 RLS/认证。可信 Ingest 是对象 Owner，应用不可变不是 WORM。
- 仅表头/无数据表遵循 P1 策略拒绝确认/导入；正常零行查询可用。累计磁盘配额、自动清理、跨文件系统事务、完整故障事件索引不在本阶段；快照发布依赖硬链接支持。旧版本和孤立快照均保留。

P2 到此停止。
