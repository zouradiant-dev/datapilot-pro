# P5B 交付：PostgreSQL Checkpoint、预算与跨进程恢复

日期：2026-10-21；修改基线 `42fb6b6`。只执行 v2.2 P5B，保留 P0–P5A；没有实施 P6/P7 或 Fork，不自动提交/推送。范围按实际代码核对，不把旧 README 计划作为能力。

## 实际修改

| 文件 / 模块 | 修改与目的 |
|---|---|
| pyproject.toml / uv.lock | 固定官方 langgraph-checkpoint-postgres 3.2.0；兼容原 LangGraph 1.2.16 / checkpoint 4.3.0，不混用旧 API |
| migrations/versions/0004_durable_execution.py | execution.runs/ledger/artifacts/calls/events 与最小 grants；0001–0003 未改 |
| persistence/management.py、db/management.py、configure_local.py、.env.example、CI | 独立 runtime/checkpoint_owner 身份与 Schema；显式部署官方 setup；保留旧密码与数据 |
| persistence/session.py | 官方 AsyncPostgresSaver、父/子图恢复、受限序列化、重授权/版本/引用校验、持久取消、脱敏 Trace、Windows SelectorLoop |
| persistence/backend.py | owner/TTL/manifest/hash、Run 锁；原 BudgetLedger 的 PG 原子适配；完整有界工件、结算收据 |
| persistence/journal.py | 外部调用 issued/complete/uncertain、稳定调用身份、响应复用、未知执行保守结算、父子账本交叉核对；并非第二个调度器 |
| state.py / orchestration/coordinator.py | Plan 历史/Reuse 来源进入原图状态；实例缓存重建；接入官方 Checkpoint/interrupt |
| orchestration/model.py / tools.py / loop.py / budget.py | 接入持久适配与原始输入去重，保持原 P5A 压缩策略、工具协议和业务授权；完整工具结果按原顺序重放 |
| cli.py | 显式 runtime-init、durable start/resume/cancel；原 ask 保留内存路径 |
| tests/test_recovery_postgres.py / test_recovery_versions.py / test_persistence_contracts.py | 真实 PG 跨进程/故障/权限/版本/预算与本地契约测试，模型替身和真实数据库明确区分 |
| scripts/recovery_probe.py / measure_recovery.py | 可复现 crash/跨进程 Demo、内存/持久流程对照及 opt-in 两次真实 API 恢复实验 |
| ADR-009 / recovery.md / roadmap / architecture / context-engineering / README / AGENTS / v2.2 Prompt 状态说明 | 所有权、可恢复状态审计、部署和当前停止点 |

`context.py`、`context_contracts.py`、`memory.py` 与三项历史迁移已与 Git 基线逐文件比对，内容不变。没有重写已有 DAG/Worker/Tool Registry，持久 Ledger 仍调用原预算算法，不建立新的 Agent 框架。

## 已验证的恢复行为

- 真正关闭 Python 进程，再由新进程以同 run_id 继续；原始任务结果、证据和预算一致，重复恢复不再调用模型。
- 模型响应提交、工具结果提交后但 Checkpoint 前进程退出，复用已提交结果。发送后但无法确认完成、工件保存后但工具完成状态未提交，保守计账并拒绝自动恢复。
- 父子预算并发预留、重复结算/冲突、未知 ticket、未发出 follow-up 释放、issued ticket 禁止释放；所有父子账户与调用计数/实际用量/保守扣减交叉核对。
- 预算 hash 正确但计数不一致也拒绝；供应商 actual 超出预留/上限时保留实际扣减，禁止恢复续跑。
- 同进程 uncertain 后 Replan 也禁止新请求，不等到重启才保护；MCP 网络错误/超时不能被当成确定未执行。
- 官方 interrupt 等待可信批准、新进程 Command 恢复；持久取消；同 Run 并发锁；双 SQL 分支一个成功一个安全拒绝的状态恢复。
- 工件/hash、调用响应/hash、Ledger/hash、TTL、目标/owner/策略/能力、Dataset/source/Metric/Semantic pin 负面检查。Dataset/Metric 通过新真实 MCP 会话重查，不信任摘要的授权。
- 只终止本测试持有的 PG 锁会话进行断连注入，运行失败关闭；未确认调用保留预算，连接恢复不能清零后重发。没有停止 PostgreSQL 或删除 Volume。
- 原 P5A L4 长循环归档、最近工具配对和证据在新进程仍可校验；新响应匹配压缩前 canonical 输入，避免冷却时间导致额外摘要/调用。

正式 CLI 的 start→Worker 暂停→新进程 resume→重复 resume 另实际运行成功（示例 run_id `4d883e4d-6428-40d9-8a0c-5338ecab58e3`）：paused→succeeded/completed，240 客户，调用数一直为 2。该 UUID 只是本地合成测试线程，不作为可跨环境使用的业务标识。

## 真实命令与结果

本地 Windows、Python 3.11.16；同一个现有 PostgreSQL 17.11 / pgvector 0.8.6。没有重新 Seed，240 客户保留。

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked --offline
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot runtime-init
uv run --locked datapilot health
$env:DATAPILOT_RUN_DB_TESTS = '1'
uv run --locked pytest -q --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
git -c core.safecrlf=false diff --check
```

实际命令使用本仓库 `.venv/Scripts/python.exe -m pytest` / Ruff；uv 锁定安装也已实际运行，不能将未执行的 GitHub Actions 当本地结果。健康检查为 healthy / migration 0004 / customers 240。runtime-init 重复执行成功，官方迁移到固定版本 v9。

| 检查 | 实际输出 |
|---|---|
| 最终全量回归 | **423 passed, 1 skipped in 300.87s (0:05:00)**；JUnit 424 tests / 0 failures / 0 errors / 1 skipped |
| 第一轮完整回归 | 420 passed, 1 skipped in 306.52s；随后额外补强未知调用/超额/断连测试 |
| PG 专项早期集合 | 25 passed in 212.51s；后续三项专项 3 passed, 19 deselected in 2.56s |
| 本地持久契约 | 7 passed in 1.92s |
| Ruff / format / whitespace | 全部通过 |
| 真实 API | 独立实验 2 次 DeepSeek 决策，非 pytest Mock 成绩；见下表 |

常规回归的 live 测试因未开启 opt-in 而跳过，**不代表本阶段没有真实 API 实验**。跨进程/故障测试用 Fake 模型决策，业务查询为真实 MCP/PG，不能称为真实 LLM 故障测试。新增测试数量不是独立经营分析任务数量。

新增自动化用例 **35 项：28 项真实 PG/MCP 集成 + 7 项本地契约**，均包含在最终全量。机器记录为 [p5b-validation.json](research/p5b-validation.json)，原始 JUnit 位于忽略的 `artifacts/p5b/final.xml`。锁定依赖已实际 `uv sync --locked --offline` 安装核对，未修改 LangGraph 分发源码。

补充实际故障实验：L4 摘要提交后、follow-up 前进程以 91 退出，新进程成功完成；无故障对照也实际执行，两者均 8 次 Fake 决策、模拟 reported_tokens=120，没有新增付费 API。另从原 P3 合成验收产物读取 verified Evidence/Verification，真实 Registry/MCP 新会话核验通过，篡改 Evidence SHA 时返回 RECOVERY_VERSION；该检查不实现新的指标报告桥接。

附加 coverage 回归实际为 **422 passed, 1 skipped in 309.61s**，父 pytest 进程统计总行覆盖率 86%。跨进程脚本/MCP 服务端的行覆盖未自动合并，因此该数字不是子进程故障路径的覆盖率；相应路径以实际子进程退出、数据库状态与恢复断言验收。最终回归另包含随后补充的同进程 uncertain 拒绝用例。

## 开销与真实模型实测

运行 `python scripts/measure_recovery.py --live`；原始测量仅保存本仓库忽略的 artifacts/p5b/measurements.json。所有请求使用现有 DeepSeek 非思考 profile，未重新优化 L4，也未付费运行 crash/长上下文故障注入。

| 同一客户数任务 | 实测 |
|---|---|
| 原内存路径 + 真实 PG/MCP，Fake 决策，n=3 | 独立进程总耗时中位数 4727.03 ms |
| PG 持久路径 + 真实 PG/MCP，Fake 决策，n=3 | 独立进程总耗时中位数 5178.94 ms；比上项约增加 451.91 ms / 9.56% |
| 真实 DeepSeek 首次执行→Worker 后暂停 | 6813.46 ms；2 次调用，2306 total tokens，结果 240 |
| 新进程恢复 / 再次恢复 | 4905.50 / 5156.60 ms；两次均无新增模型请求，证据/预算与暂停时相同 |
| 真实模型分项 | 输入 2206、输出 100；provider cache_read 合计 1792；单次 elapsed 812 / 688 ms |
| 真实模型的工件/Checkpoint | 完整 Artifact 逻辑 JSON 2012 字节；官方表 12 条 Checkpoint（包含子图），不等于物理磁盘占用 |
| 压缩 / 信息丢失 / 摘要额外费用 | 简单任务未触发压缩，无摘要调用；source loss=false；不从此实验推导长任务质量或费用 |
| 实际货币费用 | 未获得供应商账单/核实价格，记录 unknown；恢复不增加本地用量不等于账单 exactly-once 保证 |

测量包含 Python/MCP 进程启动、DB 重授权与本地负载，n=3 不能外推稳定吞吐或 p95。供应商缓存命中是本次返回的元数据，不承诺跨任务或未来固定收益；未伪造费用节省比例。L4 原有负面费用结果仍保留在 P5A 实测记录。

## 未完成边界与风险

- 停止在 P5B；无 P6/P7、真实向量检索/UI/观测平台/综合业务报告，P3 指标路径仍独立，Gate C 未整体通过。
- 长期 Memory 后端仍未实现，保留原受审阅接口/内存存储；执行 Checkpoint 不是长期记忆或授权。
- 不提供供应商 exactly-once；不确定窗口选择停止，恢复率/易用性让位于预算和证据安全。人工对账/供应商账单 reconcile 与外部幂等 API 不在本轮。
- TTL 到期拒绝访问但不自动物理清除；所有检查点/工件包含私密执行内容，后续需单独设计保留、备份、加密与运维清理。没有删除旧记录/业务库/Volume。
- 元数据角色按本地可信宿主隔离，不是生产逐租户 RLS、管理员不可篡改账本或长事务业务快照。上传版本应用层不可变；SaaS 数据更新需业务层新快照/版本方案。
- 持久 Ledger/Trace 仍采用同步 SQLAlchemy 短事务，有固定 I/O 开销；已有调用/步骤/存储配额，不能据小样本声称生产扩展性。
- Python 3.13/远端 CI 本轮未执行；工作流已加入 runtime-init 与测试身份，待用户后续提交后验证，不虚构 CI 通过。
