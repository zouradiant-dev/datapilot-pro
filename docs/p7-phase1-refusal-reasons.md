# P7 Phase 1：P3 拒答原因传递修复

2026-10-25，仅完成 zero_denominator / duplicate_record_grain 的类型化原因传递，不实施其他阶段。

## 根因与修改

独立复算原来抛出无类型的 ValueError，Repository 将这两类已知业务拒答与其他计算异常统一包装为 data_not_verifiable。Proof 之后的 Evidence、MetricBridge、Report 原本能够传递 MissingRequirement，因此不需要修改这些契约或报告代码。

- `src/datapilot/semantics/recompute.py`：新增窄类型 `RecomputationUnavailable(ValueError)`，携带现有 MissingRequirement DTO；只在实际重复记录粒度及零流失分母处抛出。ValueError 兼容性和原消息保留。空/null ID 仍走原通用拒绝，不误称重复记录。
- `src/datapilot/semantics/repository.py`：先捕获该类型并保留其 DTO；其他 ValueError/ArithmeticError 仍产生 data_not_verifiable，原 AgentFailure/数据库异常仍产生 proof_query_failed，程序异常继续向上失败，不返回已验证结果。
- `tests/test_p3_refusal_reasons.py`：10 条新的公开合成输入/异常测试，使用 Repository I/O double 与真实 DTO、Evidence 构造、六层 Verifier、ReportService；不是 PG/MCP 或真实模型测试。

新增异常类只用于兼容现有 ValueError 调用方并携带严格 DTO；直接改用现有 AgentFailure 会改变调用方的异常类型，且会落入原查询失败分支。本轮没有新增通用异常框架、数据库字段或迁移，也没有按异常文本或 Case ID 判断原因。

## 行为与验证语义

修复前两个原因都变成 data_not_verifiable。修复后 Proof.missing、Evidence.missing、ReportClaim.codes/missing_requirements 与业务缺失原因保留精确代码；Proof.status、Verification.verdict 和最终报告仍为 unavailable，不发布数值 claim 或图表。

P3 六层规则没有改动：recomputation 仍为 not_applicable，层级代码仍按原规则为 data_not_verifiable；具体业务原因通过原 Evidence/Report 契约传递。没有修改计算公式、SQL 配方、口径、授权或拒答标准。正常 usage 计算和原 ValueError 调用兼容性也有定向验证。

## 实际测试

- 修复前新文件：4 failed、6 passed，失败均为精确错误码被折叠；日志/JUnit 在 `artifacts/p7/phase1-refusal-reasons/before-py311.*`。
- 最终 Python 3.11：16 passed；Python 3.13：16 passed。每次包含新文件 10 条，加原零分母/feature 和原始数据质量 6 条。
- 覆盖两类流失零分母、收入/使用量重复粒度、通用 ValueError（即使消息含已知代码）、ArithmeticError、空 ID、其他 AgentFailure、程序异常，以及 unavailable 不升级为 verified。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_p3_refusal_reasons.py tests/test_semantics.py::test_zero_cohort_not_zero_percent_and_feature_filter tests/test_semantics.py::test_raw_data_quality_is_mandatory -q
.venv-313\Scripts\python.exe -m pytest tests/test_p3_refusal_reasons.py tests/test_semantics.py::test_zero_cohort_not_zero_percent_and_feature_filter tests/test_semantics.py::test_raw_data_quality_is_mandatory -q
```

Ruff 对上述两个生产文件和新测试的 check/format --check，以及 git diff --check 均实际验证；历史文件及本轮源码 Hash 记录见本地 `artifacts/p7/phase1-refusal-reasons/validation.json`。未运行完整 pytest、PG 集成、历史 Holdout 复评或 DeepSeek；本轮没有新的效果成功率。

## 边界和剩余风险

第一次 Live、Gold Seal、Scorer v1/v2、31 条原执行及 29 条 not_run 保留。旧 Freeze 是历史快照，不能将当前修改后源码宣称为原冻结实现或据此重启原 Campaign；本轮没有更新旧 Seal/冻结记录。

目前只为这两类明确失败保留专用代码，其他原因仍使用原安全兜底。本轮验证限本地契约链，未验证新的数据库持久化执行；没有更改数据库持久化代码。未修复其他 Bad Cases，不进入 Phase 2/Gate 3，不提交或推送。
