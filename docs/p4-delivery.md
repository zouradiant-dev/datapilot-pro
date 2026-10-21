# P4 / D9–D10 实际交付

日期：2026-10-21。基线 `a57bab9a46faa637cfa4a3795c6c820b794bd2de`。本阶段只实现 Agent 编排与双层执行，停止在 D9–D10；不声称 Gate C 全部完成。

## 实际改动

- `agents/supervisor.py` 新 Planner；`graph.py` 改为 Coordinator 入口，保留原单 SQL 的 task/result 投影。原 SQLAgent 独立接口与 P3 metric 路径未改。
- `orchestration/contracts.py`：严格 TaskSpec/Plan/TaskEnvelope/TaskResult/VerificationResult、预算、工件引用、文档与 Trace DTO；`state.py` 新 RunState/版本化冲突检测 reducer。
- `orchestration/coordinator.py`：固定外层 Planner/Scheduler/Send Worker/Verifier/Replan/Finish；依赖与能力调度、默认两路并发、源任务显式复用、有界重新规划。
- `orchestration/loop.py`：共享但任务局部的 LangGraph Worker 子图，独立消息与工具；SQL/RAG 模型→工具→反馈→再决策，失败/拒绝/取消均保持 assistant/tool 关联。
- `orchestration/model.py`：原生异步 LangChain tool calling；所有新模型调用统一 Gateway，保留明确 Fake 决策适配，未做真实推理声明。
- `orchestration/tools.py`：固定 Pydantic 工具注册与授权，SQL/RAG 不持有彼此工具句柄，无 Shell/文件/DDL；Analysis/Report 无业务工具和模型调用。
- `orchestration/budget.py` / `runtime.py`：原子父子内存预留/结算、取消、按 Run 限额 ArtifactStore、脱敏 Trace。未实现持久账本/检查点。
- `config.py` / `.env.example`：默认 8 次模型调用、20 外层步骤，8 tasks/2 并发/4 Worker 决策/1 replan；SQL 尝试仍默认 2 次。CLI JSON 可显式导出执行工件。
- 新 `tests/test_orchestration.py`、`test_orchestration_postgres.py`，原 Worker Graph 测试只更新拓扑断言，保留业务结果/修复/步数断言；conftest 增加测试输出脱敏。
- 新 `scripts/trace_orchestration_demo.py`、`docs/orchestration.md`、ADR-006、机器证据 `docs/research/p4-validation.json`；README/AGENTS/架构/路线图/ADR-001 更新到本阶段。

Mini 的 agent.py/subagent.py/tools.py 实际源码概念与本项目接口逐项对应见 [编排说明](orchestration.md)。没有复制第三方实现/Prompt 或引入 Coding Agent 高风险工具。

## 已运行命令与结果

使用 Python 3.11.16、锁定 LangGraph 1.2.16、真实 PostgreSQL 17.11 + pgvector 0.8.6。以下为本机执行，不代表本轮未推送的远端 CI：

```powershell
$env:PYTHONUTF8='1'
$env:UV_CACHE_DIR=Join-Path (Get-Location) '.cache/uv'
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_RUN_LIVE_TESTS='0'
uv run --locked --offline pytest -q --tb=short -p no:cacheprovider --basetemp=artifacts/p4/release-check --junitxml=artifacts/p4/pytest-release.xml
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
git diff --check
```

| 类别 | 真实结果 |
|---|---|
| 最终全部回归 | **284 passed, 1 skipped，81.19 秒** |
| 本阶段新增组件/合同/HTTP Mock 用例 | **28 通过**，不冒称真实模型或数据库结果 |
| 新增真实 PG/MCP DAG 测试 | **2 通过**：双 SQL、真实 SQL + 显式 RAG 替身 |
| LangChain 原生 async HTTP Mock | 单 SQL 工具消息关联通过；同一客户端两个请求互相等待的 barrier 测试通过，证明请求实际重叠；非真实模型推理 |
| 父子预算/取消/故障 | 并发原子预留、未知 usage 保守结算、model/tool 父取消、外部 task.cancel、多调用配对、安全拒绝不重规划、有界 SQL 修复、Replan 复用均通过 |
| DAG/上下文/证据 | 环、丢失/重复依赖/ID、越权字段、任务/能力配额、依赖后继、独立工具/消息、伪造引用、冲突 reducer 均通过 |
| Ruff / whitespace | check、format --check、git diff --check 通过 |
| Live LLM | **1 skipped**，未开启真实供应商推理 |
| 原基线保护 | 0001/0002/0003、SQL 安全实现、MCP server/client、依赖声明/锁文件未改；7 个已审计安装源文件仍匹配原哈希 |
| 数据健康 | migration 0003、240 客户、pgvector 0.8.6、uploads healthy |

开发中真实 PG 回归曾因 Docker 未运行而连接超时，没有把该次失败当通过。已启动原 Docker Desktop 并复查原数据库，无重 Seed/删库/删 Volume。修正 pytest 长回溯脱敏后，清理本轮失败 XML 中敏感连接参数，并更换本地 ingest 凭据；权限与业务数据保留。最终回归使用修正后的测试环境。

## 成功执行的 Trace 示例

实际命令：

```powershell
.\.venv\Scripts\python.exe -m datapilot.cli ask '查询客户总数' --mode fake --json
.\.venv\Scripts\python.exe scripts/trace_orchestration_demo.py --output artifacts/p4/final-sql-trace.json
.\.venv\Scripts\python.exe scripts/trace_orchestration_demo.py --with-rag-fixture --output artifacts/p4/final-rag-trace.json
```

| 本地工件 | 结果 | 计划任务 / 决策 / Trace 事件 |
|---|---|---|
| `artifacts/p4/simple-final.json` | succeeded，真实 MCP 查询得到 240 客户 | 1 / 2 / 10 |
| `artifacts/p4/final-sql-trace.json` | succeeded，真实并发客户数/月收入查询 + 确定性引用包 | 3 / 5 / 20 |
| `artifacts/p4/final-rag-trace.json` | succeeded，真实客户数查询 + RAG 组件替身 + 引用包 | 3 / 5 / 19 |

这些示例是 Fake 模型决策 + 真 PG/MCP，报告的真实模型 Token 为零；RAG 替身明确 `fixture=true`。完整 JSON 含计划版本、结构化任务/验证、parent 引用、实际工件、模型预算及 Trace；工件可按 SHA256 复核。公开 Trace 本身无完整 SQL、业务行或文档正文，本地显式导出包含合成数据工具结果，仍被 Git 忽略。

## 尚未实现与技术边界

- 本轮没有 LangGraph Fork、site-packages 改写或依赖升级，没有新增数据库迁移。
- RAG Loop/契约已实现，真实 Embedding/pgvector 检索与业务文档管道尚未实现，不能把组件并发测试称为完整跨来源验收。
- Analysis 仅有固定 Decimal sum/ratio；Report 仅有确定性引用汇总，没有完整业务报告 Agent。P4 任务契约验证不能替代 P3 六层指标验证；P3 入口保留且回归通过。
- 一个 Coordinator 对应一个逻辑 Run；账本/工件在进程内，显式 Trace bundle 不是 Checkpoint。PG Saver/持久预算/Memory/进程重启恢复在后续 P5，不能依靠内存结果作恢复承诺。
- Native 异步协议已用 HTTP Mock 验证，真实供应商需支持 tool calling 并另行真实 LLM 验收。自然语言计划的业务覆盖正确性不是本轮测试已经证明的通用能力。
- 未推进 UI/API、观测平台、生产鉴权/多租户、未知 POS Connector 或独立 50 任务产品评测。按本轮授权停在 D9–D10。
