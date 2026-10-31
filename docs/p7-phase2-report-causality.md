# P7 Phase 2：Report 因果否定误判修复

2026-10-25，仅完成本阶段，不处理召回、预算或后续阶段。

## 根因与最小修改

原 `ReportService.build` 使用 `scope.causal_requested OR 问题关键词匹配`。即使可信宿主明确给 False，否定语境中的“证明/导致/因果”仍会强制添加 causal_conclusion_not_verified，使事实已覆盖的报告错误变为 partial。

- `src/datapilot/reporting/service.py`：因果未验证标记只来自原宿主 `causal_requested` 布尔字段。新增入口检查，缺失 ReportScope 或非布尔字段返回 REPORT_SCOPE_INVALID；没有关键词回退、LLM、解析器或新数据库字段。
- `tests/test_report_causal_scope.py`：19 条公开合成输入/契约测试，使用明确标注的本地检索 double，覆盖事实、肯定/否定因果、证据缺失、无效/缺失 Scope、相冲突的文本及报告篡改。
- `tests/test_cross_source_report.py`：原肯定因果测试补齐宿主 causal_requested=True，不再依赖 Report 自行从文本推断。

ReportScope 字段/默认值/序列化不改。True 即使遇到否定文本也继续保守标记因果未验证；False 只完成原 Scope 下已覆盖的描述性目标，不产生“因果已证实”claim。文档仅作背景、不证明因果的固定限制说明保留，源引用和报告独立重建验证均保留。

## 实际验证

修复前有效基线 18 条为 7 failed / 11 passed：包括三条中英文否定语境误判，以及缺失/非法 Scope 的明确拒绝反例。最初两份 fixture 漏填必需字段的调试日志也保留，不将其作为产品缺陷证据；以 valid-baseline-py311 为复现记录。随后补一条“数值已验证但文档事实缺失仍 partial”测试。

最终 Python 3.11 / 3.13 各 **22 passed**：19 条新增测试 + 3 条现有可信报告/因果/未验证数据定向测试。日志/JUnit 在 `artifacts/p7/phase2-report-causality/after-py311.*`、`after-py313.*`。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_report_causal_scope.py tests/test_cross_source_report.py::test_bridge_report_chart_and_cache_prerequisites_are_explicit tests/test_cross_source_report.py::test_causality_is_unconfirmed_while_verified_descriptive_metric_remains_visible tests/test_cross_source_report.py::test_raw_query_artifact_does_not_become_a_verified_metric -q
.venv-313\Scripts\python.exe -m pytest tests/test_report_causal_scope.py tests/test_cross_source_report.py::test_bridge_report_chart_and_cache_prerequisites_are_explicit tests/test_cross_source_report.py::test_causality_is_unconfirmed_while_verified_descriptive_metric_remains_visible tests/test_cross_source_report.py::test_raw_query_artifact_does_not_become_a_verified_metric -q
```

Ruff check/format --check 覆盖上述三个源码/测试文件，git diff --check 检查工作区；具体 Hash 和历史完整性收据见本地 `artifacts/p7/phase2-report-causality/validation.json`。不运行完整 pytest、PG/浏览器或历史 Holdout 复评，不冒称这些验证已执行。

## 安全边界与风险

真实因果请求必须由可信宿主设置 True，Report 不允许文档/模型改写该字段；True 下无论描述性事实多充分，仍不能宣称因果结论已验证。事实不足时维持 partial/unavailable，错误类型或缺失 Scope 失败关闭；报告若与当前 Scope 标记矛盾，原独立重建检查拒绝。

现有 DTO 中省略 causal_requested 仍沿用原默认 False，不能将省略字段自动解释为新授权。本阶段不猜测宿主布尔字段与任意自然语言是否等价；仍依赖宿主正确组装 Scope，错误的宿主意图分类不属于本次修复。旧报告按新代码重建时可能与旧错误判定不同，应安全拒绝不一致结果，不能静默覆盖历史；本轮未进行持久恢复实验。

P3、RAG、Gold、Scorer、权限、预算、上下文和业务指标未修改；Phase 1 工作、首次 Live/Scorer v1/v2/Seal/31 条记录及 29 条 not_run 保留。未调用 DeepSeek、创建 Campaign、进入 Phase 3/Gate 3 或提交推送。
