# P7 Gate 2B v2 工程验收

**最新状态**：本轮明确授权的 [正式业务 Live](p7-gate2b-live.md) 已执行并按原规则中止于 bh2-031 的预算预留失败。60 条中观测 31、严格通过 25、未通过 6、not_run 29；保留原冻结评分和 RAG 汇总键不匹配诊断，完整 Gate 2B 未验收，不自动重跑。下面的准入、blocked、未运行及审批前段落全部为对应时刻历史快照。

**Live 前准入快照**：负责人独立授权的 [NUMERIC 序列化修复](p7-numeric-serialization-fix.md) 通过三个真实定向 P3 检查及双版本各 262 项适用回归，新实现 freeze 保留旧哈希与失败历史。当时 `ready_for_live_authorization=true`、`live_allowed=false`，随后才取得本轮独立授权。

**当前覆盖记录（2026-10-25）**：A/B 32 项已获明确批准并登记；60 条预检为 53 条常规就绪、6 条预期输入拒绝、1 条故意缺定义的负例。随后原 P3 定向核验发现 016/052 的 SQL 数值 `0E-20` 与定点解析不兼容，原 verdict 为 rejected；047 的 447.56 CNY 六层通过。详见 [只读根因分析](p7-zero-revenue-diagnosis.md)。Gate 2B 仍 blocked，`ready_for_live_authorization=false`，不重启定义审核、不改原判定。本页下文为审批前工程快照，保留其原始统计与失败记录。

2026-10-25，本轮只完成工程准备和非付费验证。正式 60 条业务候选执行与 DeepSeek 业务效果均 `not_run`，没有进入 Gate 3，没有提交或推送。

当前状态：Runner / Collector / Scorer 的非付费验收通过；`ready_for_live_authorization=false`。剩余 35 条 P3 未确认任务已去重，其中 34 条任务需要 32 个精确定义的明确业务批准；`bh2-060` 的两个故意缺失定义排除在批准范围之外。详见 [批量确认清单](p7-p3-confirmation.md)。旧审核 `pending` 不再重复阻断。

## 审核决策与封存边界

[项目负责人准入决定](p7-gate2b-owner-admission.md) 及 [结构化记录](research/p7-owner-admission.json) 已将原全量独立签署/20 条抽样要求替换为全量 AI 技术审核、确定性验证、负责人决定和已知例外修订。保留原 60 pending、失败记录及 0 个独立第三方人工签名；不追溯性宣称独立人工审核完成。Gold 审核决定不授予数据权限，也不确认 P3 业务定义。

| 对象 | SHA256 / 处理 |
|---|---|
| v1 Seal | `7af09ffe2320dfdad3535c55ed89e96124a7fd4bad0d66bc1cc898dbec464ecc`，保留原件 |
| 原 Gold | `baacca4a8e3ab2f257b24ee0f67810f64533e8fae3966f5300e278463e78362d`，v2 字节相同 |
| v2 Seal | `958ee94411d6a6b409483c5f494e09ec6792b0d2483762a201ad160d5b540e1a`，保留 parent seal / 60 条映射 |
| P3 批量请求 | `76c1e8d6ca861770e6e5c32cc9c67b7a1a2a0d1bdbebc17ae25796929ecf29c0`，未批准 |

七条 Document 子集 Pin 已通过五个去重后的精确子索引兼容：保留原 Document ID、原内容、原 Dataset/Corpus scope，不扩大授权。只在新隔离实例用固定本地 ONNX Embedding 写入新索引版本，旧索引不覆盖。`bh2-001` 增加独立真实 JOIN/账单粒度验收；`bh2-048` 在版本无效时先阻断，其文档事实只作条件性检索参考；`bh2-055` 有图时检查单位，不强制模型生成图。没有改变原数值或拒答 Gold。

## 新增工具的职责

- `p7_business_v2.py`：生成独立版本及子索引；拒绝覆盖，保留输入差异和原资产。
- `p7_campaign.py`：可信宿主做 metadata 预检、精确来源挂载和固定预算派发；复用原 PG lease，不新增 Run 状态机、Scheduler、Ledger 或恢复引擎。每次操作派发前保留 `issued` 标记，未知结果不重发。
- `p7_campaign_worker.py`：适配原 `run_durable` 和原 Collector；实际执行前重查 source/定义 hash，缺失负例必须仍返回指定错误，不能自动确认。模型仍只有原只读 MCP 工具。
- `p7_run_approved_campaign.py`：未来有新许可后逐条驱动原 start / approve / collect；许可绑定 campaign、60 个配置/任务 hash、源码 freeze、身份、模型和预算。响应丢失保留签名 unknown 记录并停止后续任务，不估造调用次数或账单。
- `p7_business_evaluator.py`：候选容器之外的签名结果评分器；复用原 `score_case`，补闭合拒答语义、P3/版本/单位、条件性图表、原文引用、JOIN 证明、检索排名及完整分母。准入和实际评分共用同一个拒答契约校验，未知语义明确阻断，不能静默删除。
- `p7_p3_confirmation_request.py`：只读去重、生成精确批准请求及逐 Case 缺失前提策略；不调用任何确认接口。
- `p7_campaign_toy.py` 和三组新测试：只使用公开合成样例检验完整工程链，不把 Toy 分数写入正式 Holdout。

清理了 Runner 中重复的缺失前提策略读取/hash 校验，保留首次完整检查。新增字段仅用于实验身份/资产/许可/异常结果及评分分母，不改变业务 DTO、数据库 Schema 或授权策略。

## 实际非付费结果

测试目标是既有 `datapilot-p7b-postgres-1` / `datapilot_p7b` / `127.0.0.1:55440`，独立卷 `datapilot-p7b_businessdata`。本轮启动原 Docker 安装及已有隔离容器；未重新初始化、迁移、Seed、删除数据库或卷，未向旧 Demo 写入。候选进程使用非 root、只读挂载、内部网络、原隔离角色。容器没有 Gold、审核包、collector key、Git、`.env` 或 Docker socket。

| 验证 | 真实结果及边界 |
|---|---|
| v2 来源/权限预检 | 60 条；6 条预期输入拒绝，35 条 P3 待确认；7 条旧 Pin 错误全部消失。只查 metadata，无候选/指标/检索执行 |
| Scorer 准入 | 60 条契约支持，三路径各 20；执行阶段和拒答条件匹配；正式业务评分 0 次 |
| 公开 Toy 全链 | SQL-only / RAG-only / SQL+RAG 共 3/3 通过；PG/MCP、真实本地 Embedding/pgvector、原 P3/Report/Checkpoint；模型为 Fake/脚本决策 |
| JOIN 证明 | Toy 经四条真实 scoped MCP 查询检验关联、账单粒度及金额；不冒称 Agent 主动生成 JOIN，不修改 P3 verdict |
| 跨进程恢复 | 三个 Toy approve / resume 之间 Evidence/Verification、报告、预算和业务完成状态相同，仅 Trace 增加 |
| 正式配置 mount probe | 001 / 021 / 054 三个只读容器；Gold/key 不可读，模型未调用；不是正式业务执行 |
| 新契约测试 Python 3.11 | 37 passed；Runner/Collector/Scorer、伪造引用/单位/版本、unknown、授权/预算、去重与缺失负例 |
| 新契约测试 Python 3.13 | 37 passed，相同范围 |
| 原有完整 pytest Python 3.11 | 741 passed、17 skipped，2360.90 秒；真实 PG/MCP + Fake/Mock |
| 原有完整 pytest Python 3.13 | 741 passed、17 skipped，2418.96 秒；相同隔离目标 |

每个版本的原有回归与最终新增契约分开执行，分别计数，不把二者说成业务任务数。17 个 skip 为 1 个未授权真实模型、2 个要求旧专用 P7 Ledger 实例、14 个要求旧专用 Provider 故障实例；没有用 Gate 2B 连接冒充这些故障实验。两个完整回归各有一个 `.pytest_cache` 权限警告，未影响测试断言。

Ruff check 通过，Git diff whitespace 检查通过。全目录 `ruff format --check .` 返回 1：唯一未格式化文件是用户受保护的 `docs/codex-prompts-v2.5.md` 中的 Python 示例块；其 SHA 与开工前一致，按要求不修改。显式排除此受保护规划文件后的格式检查通过（290 files already formatted）。这不是全工作区格式检查通过，也不影响本轮代码测试；原失败和限定范围检查分别保留记录。

命令/证据均在忽略目录 `artifacts/p7/gate2b-v2/`：

```powershell
# 本轮已执行，启动器只使用 guard 检查过的隔离 PG，清除继承模型密钥。
.venv\Scripts\python.exe artifacts/p7/gate2b-v2/run-original-full.py 311
.venv\Scripts\python.exe artifacts/p7/gate2b-v2/run-original-full.py 313
.venv\Scripts\python.exe -m pytest tests/test_p7_campaign.py tests/test_p7_business_v2.py tests/test_p7_p3_confirmation.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_p7_campaign.py tests/test_p7_business_v2.py tests/test_p7_p3_confirmation.py -q
.venv\Scripts\python.exe scripts/p7_campaign.py preflight
.venv\Scripts\python.exe scripts/p7_business_evaluator.py check
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
# 上条保留受保护规划文件的原有失败；本轮范围检查：
.venv\Scripts\ruff.exe format --check --extend-exclude docs/codex-prompts-v2.5.md .
git diff --check
```

原完整日志/JUnit 为 `original-full-py311/313.log/xml`，新增最终测试为 `final-extended-py311/313.xml`；Toy、恢复、挂载和 Registry 检查分别为 `toy-three-lanes.json`、`toy-recovery-consistency.json`、`formal-mount-probes.json`、`registry-confirmation-state.json`。源码及证据 hash 见 [最终工程 freeze](research/p7-business-v2-freeze.json)。本轮没有新 CI，不用此前 GitHub 成功替代本次验证。

## 保留的失败与限制

Scorer 曾静默忽略未知拒答条件，公开反例实际复现为 1 failed，修正后 1 passed；`refusal-counterexample-before.log/xml`、`refusal-counterexample-after.xml` 均保留。其后一个公开 preflight 测试遗漏版本拒答条件，出现 1 failed / 31 passed；补全测试定义后通过，旧 `new-contracts-final-py311.xml` 不删除。完整回归启动器首次路径错误在 pytest 启动前失败，修正后才得到上述完整结果，保留 `regression-launch-failure.txt` 和初始启动器。

正式 Live branch 只完成契约/Mock 与无模型挂载检查，没有真实 DeepSeek 或 60 条业务成功率。当前原 Runtime 对合法空窗口、局部成功等已知边界可能仍产生负结果；不为刷分改配方、Verifier、Prompt 或 Gold。未知调用可能产生费用，实际账单无法从本地日志保证 exactly-once。采集签名是可信本地主机完整性证据，不抵御掌控宿主/数据库的管理员；挂载隔离也不是生产多租户安全声明。

检索 Recall/Precision/MRR 分别按 chunk/document/source、每次真实查询计算，去重实体但不挑最好一次查询；Precision@3 分母为 3，另列返回结果精确率。RAG Worker 检索完成、P3 verified、最终业务正确独立统计。未观测样本保留 `not_run`，零观测率/置信区间为 null。Fake Token 不当 provider Token；缓存缺失为未知，费用估算与账单分开。

## 剩余准入与后续授权

1. 负责人一次决定 [精确 A/B 32 项业务定义](p7-p3-confirmation.md)，不包括 C；随后原 Registry 追加登记并重核原版本/hash。当前没有自动登记。
2. 该步骤通过后才能报告 `ready_for_live_authorization`。未解决的 P3 定义是实际阻断；旧人工 pending 已被负责人决定取代，六个预期拒绝和故意缺失的 `bh2-060` 不要求扩权/补定义。
3. 正式 DeepSeek 业务 Live 必须独立授权。计划仍保持 60 个任务、串行、每 Run 最多 8 次/18,000 Token、输出 1,200、Thinking disabled、无自动重试。6 个宿主预检负例不调用模型，最多 54 个 Runtime Run，即 432 次/972,000 Token 上界；这是预算上界，不是已发生用量。价格需在将来的授权计划中另行冻结，当前费用与成功率均不填造。

工程准备结束后停止，等待业务定义决定及未来单独 Live 授权。
