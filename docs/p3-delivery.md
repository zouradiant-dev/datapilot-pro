# P3 / D6–D8 实际交付

日期：2026-10-21。基线 `ef28c54b4ccb19c2c1bd42c3b463a0988bc54e47`。仅推进 SaaS 业务语义、指标与证据验证，停止在 Gate B。以下是本机实际执行结果，不代表尚未推送代码的 GitHub CI，也不代表真实 LLM 推理验收。

## 本阶段改动

- `semantics/contracts.py`：严格 Semantic/Metric/Evidence/Verification/Report DTO；草案与确认版本、不可计算原因、精确数值和大小/目标数限制。
- `db/semantic_schema.py`、新 `0003_semantics_and_evidence.py`：四张固定元数据表、版本/来源外键、唯一性与完整 JSON/hash。历史 0001/0002 不改。
- `semantics/registry.py`：显式审阅、幂等确认、追加版本/证据/验证、读取完整性检查；`datapilot_registry` 独立 metadata-only 身份，不能读取 saas/uploads/rag 或修改历史/DDL。
- `semantics/recipes.py`、`recompute.py`、`repository.py`：五类封闭指标、最小上下文、保守 AST 配方验证、独立原始列 Python 复算；单一只读一致快照、20,000 行/256 页/8 MiB/协作时限。
- `harness/metric_verification.py`：安全、形状、语义、复算、引用、目标覆盖六层；raw Evidence 与 Verification 分离，终态独立推导。
- `agents/sql.py`：新增 `run_metric(MetricRequest)`，只走受控 MCP；支持明确的 deterministic 编译路径或已有预算化 ModelClient 的受限提议，原 SQLTask 路径保留。
- `runtime/mcp_client.py` / `mcp_server.py`：增加 get_metric_context、recompute_metric、get_evidence 三个只读能力；宿主固定 Dataset/version，子进程无 Registry/管理员/模型凭据。
- `semantics/service.py` / `cli.py`：映射/指标分别确认、版本化请求执行、受控证据读取；只发布通过校验且带 Evidence/Verification ID 的确定性 Markdown 数字。
- `data/semantic_demo.py`、`scripts/prepare_semantic_demo.py`、`tests/fixtures/semantics/`：公开合成 CSV 和三 Sheet XLSX，固定日期/ZIP 元数据；不含生产资料。
- 新 `test_semantics.py`、`test_semantic_integration.py`；原 MCP 工具列表测试更新为九个只读工具。环境模板、初始化、CI 增加独立 Registry 配置。README/AGENTS/架构/路线图/ADR 更新到 P3；无新依赖，uv.lock 未变。

## 真实执行

环境：Windows，本地虚拟环境 Python 3.11.16，PostgreSQL 17.11（170011），pgvector 0.8.6。

在本地使用项目缓存以避免全局缓存权限；以下命令均在仓库根目录实际执行过：

```powershell
$env:PYTHONUTF8='1'
$env:UV_CACHE_DIR=Join-Path (Get-Location) '.cache/uv'
uv run --locked --offline python scripts/configure_local.py --add-registry-role
uv run --locked --offline datapilot db-init
uv run --locked --offline datapilot migrate
uv run --locked --offline datapilot health
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_RUN_LIVE_TESTS='0'
uv run --locked --offline pytest -q -p no:cacheprovider --basetemp=artifacts/p3/release-check --junitxml=artifacts/p3/pytest-release.xml
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
git diff --check
```

初始化/升级实际以 `.venv/Scripts/python.exe` 执行同一模块和脚本；完整测试以 uv 的锁定环境运行。

| 验证 | 实际结果 |
|---|---|
| 最终全量 pytest（含所有既有 P1/P2/Day 1 与真实 PG/MCP） | **254 passed, 1 skipped，88.89 秒** |
| P3 本地单元/Mock 测试 | **50 passed**；不连接数据库，未当作业务 E2E |
| P3 真实 PostgreSQL/MCP 集成 | 全量中的 **16 个用例通过**；CSV/XLSX、五类指标、MRR/因果/零分母拒答、映射缺失、版本/权限、错误 SQL、分页配额 |
| 类型/投影总字节限制调整后的针对性验证 | 当时本地 49 + 真 MCP 协议 1 + 真 PG 配额 1，共 **51 passed，5.01 秒**；另单独真 PG 配额测试 **1 passed，2.71 秒**；随后新增伪造 Verification ID 用例，已纳入上述最终全量 |
| Ruff check / format | 通过 |
| Git whitespace | 通过 |
| Live LLM | **1 skipped**；未开启真实模型、未消耗模型 Token，不能声称模型 E2E |
| GitHub Actions | 本阶段未推送/未运行，不能声称本次远端 CI 已通过 |

测试过程中曾发现并修复新 fixture 的列位置从零开始、XLSX modified 时间不固定，以及旧 AST 白名单不接受 EXISTS/CASE 子节点的问题。配方改为已允许的 FILTER/DISTINCT 算法，未扩大白名单。Registry 权限检查测试改用系统表 OID，因为无 saas Schema USAGE 时名称解析本身就会拒绝；未为测试增加权限。

真实健康检查：migration 0003、240 customers、seeded=true、uploads healthy；原数据未重 Seed，未删除数据库/Volume。合成测试数据以可追踪 Dataset/版本保留。

## 实际 CLI 示例与证据

已运行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_semantic_demo.py --reviewed-synthetic --output artifacts/p3/cli-demo
uv run --locked --offline datapilot semantics run artifacts/p3/cli-demo/requests.json
.\.venv\Scripts\python.exe -m datapilot.cli semantics confirm-mapping artifacts/p3/cli-demo/mapping.json --reviewed
.\.venv\Scripts\python.exe -m datapilot.cli semantics confirm-metric artifacts/p3/cli-demo/paid_invoice_revenue.json --reviewed
uv run --locked --offline datapilot semantics evidence d75816b0-f1ac-486c-848f-047ea5025078 --dataset 1686da64-a682-5c35-b6c3-2d1553324194 --version 1
```

Demo 为 `execution_mode=deterministic`，实际连接真实 PG/MCP。October 2025 的公开合成 Gold：

| 指标 | 结果 | 验证 |
|---|---|---|
| 已付账单收入 | 300 CNY | verified |
| 期初订阅队列流失率 | 4/6 = 0.666666666667 | verified |
| 期初客户队列期末净流失率 | 2/5 = 0.400000000000 | verified |
| October 31 时点活跃合同 | 4 | verified |
| 使用量 | 35 events；另测 dashboard=30 | verified |
| MRR | 缺经常性金额/计费周期/折扣退款等，当前无配方 | unavailable |

上表为合成验收摘要，完整数字报告及证据位于本地忽略目录 `artifacts/p3/cli-demo/`，不是任何真实企业经营结果。收入的实际 Evidence ID 如上，source hash 为 `87df9a81a06c7301c69a13e9d13fd733545eae7180fa9304c62df8ad10dd1ed7`，query hash 为 `a07fadde90e7969a581bfcdcd07e808359ff03159c11fd0dbc6ffd0957b6bed0`，result hash 为 `bc1bffdda9c05ef1e2f0ccb650a0f60c0ecd2532ad4096eda15bb75df46745c9`。这些 ID 属于本机验收库；其他环境应运行 Demo 生成自己的 ID。

未带 `--reviewed` 的映射确认实际返回 `REVIEW_REQUIRED`、退出码 2。正常查询、确认和证据读取均退出 0。证据读取只需 upload_reader，不依赖写身份；不存在/越权/未确认定义有明确错误，不合成缺失版本。

## 限制与停止点

- 首版 CNY/DATE、封闭受审查政策、单 Dataset、显式 JSON 目标；原自然语言 ask 不自动获得 P3 证据语义。不宣称任意自然语言经营问题已解决。
- MRR 可追踪定义但不计算；其他币种/FX、退款政策、复杂合同、因果识别和自动语义确认尚未实现。
- 大于复算配额的数据明确不能验证；AST 相等保守拒绝部分等价 SQL。真实文件真实性和业务完整性仍依赖操作者确认，Hash 不能证明真实。
- 本地可信单用户，Registry 的 append-only grants 不约束管理员/Owner；未实现生产认证/多租户，未保证跨工具全局快照或长期历史代码引擎回放。
- 没有推进 P4 动态 DAG/多 Agent/Memory/Checkpoint、RAG/API/UI、LangGraph Fork、干洗店或独立 50 任务产品评测。下一阶段须另行授权。
