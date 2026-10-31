# P7 Phase 1 + Phase 2 联合定向集成验收

2026-10-25。两阶段通过本轮真实 PG/MCP 定向验收；本轮没有改动生产代码，不代表完整回归或 Gate 2B 正式 Live 验收通过。

## 环境、范围与改动

复用受既有创建记录保护的 `datapilot-p7b-postgres-1` / `datapilot_p7b` / 55440，实际 PostgreSQL 17、pgvector 0.8.6。沿用隔离角色、现有 Ingestion/Registry、MCP、Durable Runtime、Journal 和本地固定 ONNX Embedding。没有初始化、迁移、Seed、删表/卷或扩大权限。

模型决策只使用现有 `ReportDecisions` 测试脚本，环境禁用 Live、API Key 置空，原生付费 Transport 显式阻断；旧记录检查使用原 NoModel Inspector。账本中的新测试调用不等于真实供应商调用，本轮 DeepSeek 请求数为 0，没有真实模型费用或效果结论。

仅补充测试：

- `tests/test_phase12_postgres.py`：复用原 metric_data / report_data / embedding 夹具，增加三个缺失的集成断言：两类精确业务拒答码，以及显式 False 的事实报告与只读持久引用恢复。
- `tests/test_cross_source_postgres.py`：原三条缺失数据/因果测试增加显式宿主因果参数。先复现其中因果测试失败，再补齐其 True 标记；没有修改业务判断或期望结果。

两阶段生产文件和原定向测试 Hash 与各自交付时一致；Gold、Scorer、预算、上下文、权限及既有指标定义没有改动。测试只为公开样例建立新 Dataset/Corpus/Run；重复粒度样例由公开 XLSX 衍生为新 Dataset，不改原文件或旧表，不触碰 Holdout 定义。

## 实际结果

| 检查 | Python 3.11 | Python 3.13 |
|---|---|---|
| 联合本地定向回归 | 38 passed | 38 passed |
| 真实 PG/MCP 定向集成 | 6 passed | 6 passed |

六项 PG 用例覆盖：

1. 零流失分母经真实 MCP Proof、持久 Evidence/Verification、MetricBridge、Durable Report 保留 zero_denominator。
2. 新公开重复账单数据经相同链路保留 duplicate_record_grain。
3. 上述两项仍为 unavailable、没有数值 claim/图表；原六层 recomputation 仍为 not_applicable / data_not_verifiable，没有改变规则。
4. 真实数据和文档充分时，False 下否定语境的事实报告 completed，P3 数值仍 verified；NoModel 只读检查重建报告一致、用量一致，P3 ID/Hash 不变。
5. True 的实际因果任务仍 partial、保留 causal_conclusion_not_verified。
6. 真实关联文档不匹配及不支持的 MRR 定义分别保持 partial / unavailable，不能用查询成功替代业务证据。

上表“六项”是 pytest 的六个独立参数实例；第 1–3 点为两个拒答实例的不同断言，不另凑测试分母。全部决策为测试脚本，PG、MCP、持久化和文档检索实际执行。

## 旧报告冲突和历史不可变性

只读加载原 bh2-024 的签名报告及原授权文档片段，使用真实 PG/RAG 来源校验后按当前 Report 规则独立重建。原 partial、新投影 completed，除 business_completion/Markdown 外报告字段相同；旧报告由原 verify_report 明确拒绝：REPORT_EVIDENCE_INVALID。没有写回新投影、运行任何旧节点、恢复任务或重新评分。

原 Run 整体 Inspector 从宿主读取时还遇到既有 Docker reader 端点与宿主端点不同，按原 Manifest 校验返回 RECOVERY_IDENTITY。保留该安全拒绝，没有跳过/伪造 Manifest；**不能声称已在原容器端点进入恢复后的报告节点**。同端点的新 Run 只读恢复已通过，原 Docker 端点的跨进程旧报告恢复仍需后续完整回归。

运行前后通过只读事务，对原记录逐行计算 SHA256 并比较：

- 原 245 个 Evidence、237 个 Verification、116 个 Semantic、129 个 Metric 版本均未改写。
- 原 402 个 Run 和 Ledger、1,391 个调用 Journal、1,328 个 Artifact、4,982 个事件均未改写。
- 原官方 Checkpoint 3,565 行、blob 6,393 行、writes 15,628 行及迁移记录均未改写。

本轮只追加 16 个测试 Run/账本、16 组新 Evidence/Verification 等测试记录，保留失败测试产生的记录；未清理数据库。首次 Live 的 31 条观测、29 条 not_run、原费用/Token、Scorer v1/v2 和封存文件不变。

## 命令、失败记录与静态检查

本地运行器 `artifacts/p7/phase12-integration/isolated-check.py` 只复用原隔离环境保护并调用 pytest/只读快照，不是第二套运行或恢复机制。真实 PG 用例：

```powershell
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_phase12_postgres.py tests/test_cross_source_postgres.py::test_missing_data_causality_and_nonmatching_documents_never_complete -p no:cacheprovider --basetemp=<本验收目录内全新且不存在的路径> -q
.venv-313\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_phase12_postgres.py tests/test_cross_source_postgres.py::test_missing_data_causality_and_nonmatching_documents_never_complete -p no:cacheprovider --basetemp=<另一个全新且不存在的路径> -q
```

联合本地回归为两阶段原定向集合：test_p3_refusal_reasons、test_report_causal_scope、原零队列/原数据质量测试及三条原可信报告测试。没有执行完整 pytest。

实际日志/JUnit/只读数据库指纹均在 `artifacts/p7/phase12-integration/`：`final-pg-py311.*`、`final-pg-py313.*`、`unit-py311.*`、`unit-py313.*`、`before-database.json`、`after-database.json`、`old-report-check.json`、`validation.json`。这些是本机私密验证资产，未上传。

保留的先前失败：一条旧集成夹具未设置 True，实际 completed 与旧预期 partial 不同；已仅修正测试契约。新增集成测试首次运行有三项 setup error（临时目录权限及未导入 embedding 夹具），已补齐复用依赖并改用全新工作区临时路径。旧 Inspector 审计最初错误期待在报告节点拒绝，实际先被端点 Pin 拒绝，已分层记录。上述调试失败不隐去，也不误算为最终业务回归。最终 PG 各有两条 pytest 预导入插件告警，无失败/跳过。

Ruff check/format --check 与 git diff --check 均通过。新文件没有代替全量 CI，未运行 GitHub CI、DeepSeek、历史 Holdout 重评分或其他实验。

## 是否可暂时封存

适合暂存为“Phase 1/2 已通过联合定向验收，待完整回归”的开发快照。没有发现新的业务代码回归；发现并修正了一处旧测试夹具契约兼容问题。

发布或新 Live 实现冻结前仍需要双版本完整 pytest/真实 PG/MCP/RAG、Durable/unknown-outcome 与同原端点的旧报告跨进程恢复、API/UI 浏览器及 CI 回归。旧错误报告的处理策略不能通过改写原证据或跳过 Manifest 来解决。本轮只记录这些边界，不推进恢复改造、026/031、Gate 3，也不提交/推送。
