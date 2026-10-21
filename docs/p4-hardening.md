# P4.1 增量加固交付

日期：2026-10-21。实际审计基线：`1f0decd02ce9eed989c52486797bdba88ff11f46`，分支 main；开始时只有用户提供的 `docs/codex-prompts-v2.2.md` 未跟踪文件，保留原文。本阶段以该文档第 1–2 节和用户明确授权为范围，不执行 P5A/P5B/P6，也不自动提交/推送。

## 实际状态矩阵与复用接口

完整读取 AGENTS、Roadmap、P4 交付、v2.2 执行协议及 P4.1 要求，核对 README、architecture/orchestration、ADR-006、现有源码与测试。参考包中的远端 CI 声明本轮未重新查询，以下只报告本机真实执行。

| 能力 / 实际源码位置 | P4 基线已有 | 本轮必要改动 / 重复开发风险 |
|---|---|---|
| contracts.TaskSpec/Plan/TaskEnvelope/TaskResult | 严格 DAG、身份/能力/预算/引用契约 | 保留；仅补 CompletionDecision、ContextUsage、schema 工件及 payload 一致性 |
| coordinator._compile / RunState | 固定 StateGraph、Send/Command、就绪调度/冲突 reducer | 保留拓扑，Finish 加完成判定，不加第二个 Scheduler |
| loop.build_worker_loop / WorkerContext | SQL/RAG 独立消息、模型→工具→反馈 | 保留 Loop；工具守卫收敛到现有 Registry |
| tools.ToolRegistry/DEFINITIONS/CAPABILITIES | 参数 DTO、固定授权/独立句柄 | 扩展 invoke 生命周期；不再建 Registry/插件框架 |
| AIMessage/ToolMessage | 每个 call ID 对应反馈，拒绝/取消闭合 | 保留协议，补三调用部分拒绝/剩余未执行反例 |
| budget.BudgetLedger / Gateway.invoke | 父子原子 reserve/settle、未知用量保守收费 | 保留；新增上下文预检不消耗模型预算、工具尝试竞争测试 |
| runtime.Cancellation | 父子取消、等待清理 | 保留；模型/工具超时区分 reason_code |
| runtime.Trace | Run 内有序脱敏事件 | 增上下文尺寸事件，未知工具名固定标签、异常格式 call ID 哈希 |
| runtime.ArtifactStore | 同 Run 内存、hash/容量/身份校验 | 完整结果先保存，再生成 L0 模型视图；不假装持久存储 |
| coordinator.verify | identity/capability/evidence/shape/dependencies 五层 | 补派生工件不能遗漏已授权依赖，Finish 重验真实工件 |
| semantics / metric_verification | P3 独立入口、持久 Evidence/六层验证 | 不重写、不伪装已接入 DAG；指标完成判定失败关闭 |

## 具体修改文件

- 原模块修改：`orchestration/{tools,loop,model,runtime,contracts,coordinator}.py`、`config.py`、`state.py`、`graph.py`。
- 最小新模块：`orchestration/context.py`（计量/L0 视图）、`completion.py`（宿主完成判定），没有第二套运行引擎。
- 配置：`.env.example` 新增 context token/view 字符上限，原预算和 SQL 默认限制保留。
- 测试：`tests/test_orchestration_hardening.py`、`tests/test_orchestration_hardening_postgres.py`；`scripts/p41_mutation_smoke.py` 是单一引用变异复现，不是通用评测框架，也不是模型工具。
- 文档：AGENTS、README、architecture、roadmap-v2、orchestration、ADR-007、本交付及 `docs/research/p41-validation.json`。P4 历史交付不覆盖，用户提供的 v2.2 文档不改写。
- 冻结保护：历史迁移 0001/0002/0003、SQL 安全实现、MCP Server/Client、P1/P2/P3 源码、依赖声明/锁文件均未修改。

## 关键设计与可见行为

安全顺序及取舍见 [ADR-007](adr/0007-p4-hardening.md)。无用户可执行 Hook，没有拒绝改为成功的后置处理。输入中的 scope/dataset_id/allowed_tools 不能改变宿主会话；数据库仍独立执行 AST、grants、只读、超时和输出配额。

Goal Completion Gate 是宿主检查器，不调用 LLM。任务必需终态、五层记录、真实引用重新验证后，才可 completed；缺结果/截断/改变原必需任务为 incomplete，拒绝/不可回答/失效证据为 blocked。原 `status=succeeded` 是工具执行成功，调用方必须另外检查 `completion`。已识别的业务指标始终要求 P3 verified Evidence；当前没有 P6B 桥接，所以 fail closed，不把 SQL 查询结果当 verified metric。

L0 先保存完整合法查询/文档，再反馈受限摘要和 hash/ref；大 SQL 行不会发给模型，RAG 文本截取明确标出省略量。完整 Schema 保存在 schema 工件并原样传递；不可安全裁剪的消息明确 CONTEXT_LIMIT。L1/L2 是文档允许的可选项，本轮依 ADR-007 延后，未提前实现 P5A。

## 运行命令与真实结果

Python 3.11.16，uv.lock，LangGraph 1.2.16；真实 PostgreSQL 17.11 + pgvector 0.8.6。所有命令在仓库根目录运行，uv 可执行路径为 `D:\develop\Python310\Scripts\uv.exe`。测试使用隔离的仓库内 basetemp，未执行清库、重新 Seed、卷删除或权限扩张。

```powershell
$env:PYTHONUTF8='1'
$env:UV_CACHE_DIR=Join-Path (Get-Location) '.cache/uv'
uv run --locked --offline pytest -m 'not integration and not live' -q --tb=short -p no:cacheprovider --basetemp=artifacts/p41/local-release --junitxml=artifacts/p41/local-release.xml
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_RUN_LIVE_TESTS='0'
uv run --locked --offline pytest -q --tb=short -p no:cacheprovider --basetemp=artifacts/p41/release --junitxml=artifacts/p41/release.xml
uv run --locked --offline python scripts/p41_mutation_smoke.py
uv run --locked --offline pytest tests/test_orchestration_hardening.py -q --tb=short -p no:cacheprovider --basetemp=artifacts/p41/restored-final --junitxml=artifacts/p41/restored-final.xml
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
git -c core.safecrlf=false diff --check
```

| 实际执行 | 原样结果 / 说明 |
|---|---|
| 最终全量（开启真实 PG） | **325 passed, 1 skipped in 88.96s (0:01:28)** |
| 本地/协议，不含 integration/live | **277 passed, 49 deselected in 6.10s** |
| 新加固文件单独回归 | **36 passed in 2.26s** |
| 真实 PG/MCP 回归 | 全量内 **48 项通过**，其中 **5 项为本阶段新增**；与上述本地 277 项合计 325 |
| Mutation smoke | 子进程 **1 failed**、exit 1（预期红）；源文件未变，随后正常测试 36 passed；脚本仅在检测到这个预期红时 exit 0 |
| Ruff | `check .`、`format --check .` 均通过 |
| Whitespace / 冻结保护 | `git diff --check` 通过；机器核对历史迁移/SQL/MCP/P1–P3/BudgetLedger/依赖均未改 |
| Live 模型 | **1 skipped**：未开启 DATAPILOT_RUN_LIVE_TESTS；没有真实模型推理成功率 |

全量 JUnit `artifacts/p41/release.xml`：326 tests、0 failures、0 errors、1 skipped。机器证据 [p41-validation.json](research/p41-validation.json) 从实际 XML、最终源码 hash、原始 CLI 输出生成，不含 hostname/凭据/业务行。调试 XML/Mutation runner/log 均在 gitignored artifacts/ 中；预期红的故障实验与正常回归报告分开。

真实健康检查 `python -m datapilot.cli health` 返回 healthy、PostgreSQL 170011、pgvector 0.8.6、migration 0003、240 customers；uploads healthy。本轮不套用 P4 历史测试计数。

已执行 CLI 示例：

```powershell
python -m datapilot.cli ask '查询客户总数' --mode fake --json
python -m datapilot.cli ask '计算2025-10收入' --mode fake --json
```

两者均为 **真实 PG/MCP + Fake 模型决策**，各两次决策、reported_model_tokens=0，并各有两份上下文测量事件。客户数为 240，执行 succeeded、completion completed；收入查询执行 succeeded、completion blocked/P3_VERIFIED_EVIDENCE_REQUIRED。原始 JSON 保存在 `artifacts/p41/cli-count.json`、`cli-revenue.json`；未冒充 P3 verified 指标或真实模型 E2E。

## 安全、故障与有效性反例

- 已注册的兄弟工具仍拒绝；额外 scope/权限字段拒绝；缺宿主句柄不执行；并发争抢最后 SQL 尝试只允许一个。
- 一个调用拒绝后三个 ID 全部闭合，其余调用明确 NOT_EXECUTED，零 SQL、零 Replan。
- 坏 QueryResult 形状、错误文档 hash、Artifact 配额超限无成功视图；验证错误不借 Replan 绕过。
- 真超时清理挂起协程、取消不消耗查询尝试、MODEL_TIMEOUT 与 TOOL_TIMEOUT 分离；未知模型用量父子保守扣费，原重复结算/取消测试保留。
- 消息、工具 Schema、输出预留分别单独导致上下文上限；短对照可正常调用；安全消息不修改、不预扣超限调用。
- 5 篇大文档先完整保存，再生成 4096/768 字符配额视图，省略可见、hash 不变；完整 Schema 超限则明确失败。
- 缺验证、旧 plan 记录、少四层验证、删除工件、截断结果、Replan 删除原任务、Report 遗漏依赖全部不能 completed；收入/MRR/流失原始查询不能冒充 P3 验证。
- 并发 SQL/RAG fixture 上下文不串扰，Trace sequence 连续；恶意文档中的 Shell 指令只是数据，没有可执行能力。此项不等于真实模型抗注入成功率。
- Mutation smoke 在子进程内删除派生工件依赖引用守卫，真实目标测试变红；子进程退出后变异消失，源文件 SHA 不变，再跑原测试变绿。没有提交危险变异。

## 未完成项、风险与停止点

1. completed 只证明必需任务契约，不证明 Planner 完整理解任意自然语言目标。原计划改变会保守判 incomplete，暂不判断两个计划是否语义等价。
2. 业务指标关键词检测可能误报/漏报；不是语义分类器。结构化 MetricRequest/P3 Evidence 及报告桥接没有实现，属于 P6B；当前命中指标时 blocked，独立 P3 路径不变。
3. Token 按 UTF-8 字节+128 保守估算，非供应商 tokenizer/成本测量；大 Schema 仍可能超限，L0 摘要也可能不足以回答问题，不通过静默截断规避。
4. Artifact/预算/上下文仍为内存，进程重启即失去运行状态。没有 L1–L4、Memory、持久 Ledger/PG Saver/恢复、真实 RAG/业务报告、UI/遥测或 Fork。
5. 真实 LLM API 未运行，本轮不推断模型任务成功率；RAG 仍仅为 fixture。Python 3.13/远端 CI 本轮未执行，不套用历史 CI 成绩。

P4.1 完成后停止，Gate C 未完成。未来候选仅为需用户另行确认的 P5A，不自动实施。
