# P7 Phase 3C：首次原问优先安全验证

2026-10-25。**候选的目标绑定、权限、工具与 Journal 兼容性检查通过；完整业务安全准入未通过，暂不实施生产修改。** 本轮发现的是既有 Report 完成状态的表达缺口，没有发现原问优先导致扩权或改写持久调用参数。最终结果为 **19 passed / 1 failed**，不是全部验收成功。

## 1. 最小候选和复用范围

仅复用 [Phase 3B](p7-phase3b-rag-query-strategy.md) 的既有 Corpus/来源/IndexVersion，选用原有中文密钥、英文密钥、缺少年限和缺少因果证据四条输入。没有新增 Dev 问题、重新摄取、创建 Corpus 或修改原标签。Embedding、模型文件 SHA、0.55、Top-k=5、原最大两次搜索保持不变。

本机 [候选函数](../artifacts/p7/phase3c-original-goal/candidate.py) 仅在首次搜索前返回宿主原始检索问题，要求与既有 `retrieval_goal` 完整绑定一致，使用原 SearchArguments 校验；后续返回 None，不翻译、不截断、不实现 fallback。输入和测试断言在真实 PG 验证前冻结，见 [计划](../artifacts/p7/phase3c-original-goal/plan.json) 与 [执行文件冻结](../artifacts/p7/phase3c-original-goal/executable-freeze.json)。

脚本化模型在创建 assistant/tool_call 前选择原问，随后走**原 Worker Loop → Gateway/预算 → ToolRegistry → MCP → Completion → Report → Journal/Checkpoint**，不拦截或静默替换模型已经生成、登记的参数。这验证接线兼容性，不代表真实 DeepSeek 会遵守原问策略。

## 2. 实测结果

| 检查 | 实际结果 |
|---|---|
| 中英文原文、跨语言/不同目标绑定反例 | 原文精确保留；错误 goal/hash 拒绝；不修改宿主目标 |
| 512 字符限制 | 513 字符及空白拒绝，不截断；另测中英文 512 字符精确保留 |
| 原 Embedding Token 上限 | 512 个中文字加既有查询前缀触发 `EMBEDDING_LIMIT`，无静默截断；字符合规不保证模型 Token 合规 |
| 原 Worker + 真实 PG/MCP 中文/英文控制 | 两条均真实召回；每 Run 一次 search，原 RAG receipt 的 `business_conclusions_verified=false` |
| 已知 Corpus 的错误 owner / 撤去 SaaS grant | 均 `DOCUMENT_NOT_AUTHORIZED`，未扩大 Scope |
| 两次检索硬上限 | 独立预算探针允许原两次调用，第三次 `RAG_ATTEMPTS_EXHAUSTED`；不构成候选 fallback |
| Journal | 实际首查 fingerprint 等于原问+Top-k；同 tool_call_id 改英文参数触发 `RECOVERY_CONFLICT`，调用行未变 |
| 跨进程重复恢复 | 原结果、报告与 usage 一致；禁止模型调用的子进程成功恢复，无重复模型/检索调用 |
| 恢复/报告目标替换 | 分别 `RECOVERY_IDENTITY`、`REPORT_SCOPE_INVALID` |
| 伪造报告内容 | 添加虚构“保存七年/随机实验证实”均被原 `verify_report` 以 `REPORT_EVIDENCE_INVALID` 拒绝 |

所有四个新隔离 Run 的 Journal 调用均 complete、无 issued/uncertain；每 Run 三次脚本化模型决策、一次真实 MCP 搜索。脚本声明的测试 usage 仅用于验证账本和恢复，不是供应商 Token/成本实测。没有改变预算或 unknown-outcome 处理，也没有新增真实供应商故障实验。

## 3. 两个证据不足场景与失败反例

**审计日志保存年限**：原问题“权限审计日志必须保留多少年？”，真实来源明确“本文没有规定审计日志保留年限”。对抗性脚本仍提交检索 complete；真实 Worker/原 Completion 接受相关背景。最终 Report 只引述原文，没有编造年数、生成图表或 P3 verified metric。但是 `business_completion.status=completed`、`verified_goals=[documents]`，`missing_evidence` 为空。

因此，预先登记的保守业务覆盖断言“缺失所请求事实时不应全量业务 completed”**实际失败**。这是完成状态过度表达的反例，不是伪造财务数字、P3 Verifier 失效，也不能冒称真实 DeepSeek 自主作出了该错误。原文能够支持“未规定年限”的诚实说明；问题在于当前状态不能区分该说明和所请求年限已获证明。

原因位于 [ReportService.build](../src/datapilot/reporting/service.py)：约 431–446 行的 `topics_match` 对纯文档路径主要检查相关来源/数量；`metric_goals=[]` 时没有具体事实存在性约束，相关背景即可覆盖 documents。约 480–485 行据 covered/missing 计算业务完成。既有 DocumentGoal 仅包含问题及关联指标，没有保存年限之类的结构化必需事实契约。**本轮没有修复或修改该契约。**

**维护安排与留存因果**：同样允许检索真实维护背景，但可信 `causal_requested=True` 使最终 Report 保持 **partial** 和 `causal_conclusion_not_verified`。没有宣称随机试验证明提高留存，没有指标/图表。两个场景中，直接以 unavailable 的源状态投影时，原 Report 均保持 unavailable，不会把不足收据升级。

检索任务完成、引用真实与业务结论充分仍分别判断：这里不要求 RAG Worker 独立证明因果，也不因其取得相关背景就判定最终答案完整。保留了 [失败断言](../artifacts/p7/phase3c-original-goal/test_safety.py)、[年限完成状态原件](../artifacts/p7/phase3c-original-goal/retention-business-coverage.json) 和全部测试日志，没有改成 xfail 或放松断言。

## 4. 验证和完整性

Python 3.11：本地输入/目标保护 **8 passed**；真实隔离 PG/MCP/Worker/Report/Journal 定向集合 **11 passed、1 failed**（33.45 秒，2 个预导入警告）。未运行完整 pytest、Python 3.13 或真实 DeepSeek。命令和记录：

```powershell
.venv\Scripts\python.exe -m pytest artifacts/p7/phase3c-original-goal/test_safety.py -k 'preserves_exact or oversized_or_empty or mismatched_host_goal' -p no:cacheprovider -q --tb=short --junitxml=artifacts/p7/phase3c-original-goal/unit.xml
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest artifacts/p7/phase3c-original-goal/test_safety.py -k 'not (preserves_exact or oversized_or_empty or mismatched_host_goal)' -p no:cacheprovider -q --tb=short --junitxml=artifacts/p7/phase3c-original-goal/integration.xml
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe check artifacts/p7/phase3c-original-goal
.venv\Scripts\ruff.exe format --check artifacts/p7/phase3c-original-goal
git diff --check
```

Ruff/局部 format/Diff 均通过，既有 LF/CRLF 提示保留。报告及本地忽略目录之外零修改，开始时记录的 **626 个既有文件 hash 均未变化**，包含 Phase 1/2/3A/3B、Gold/Seal、Scorer 和原始结果。新验证文件冻结后未改。

真实数据库前后只读 hash 对照确认：RAG 全表完全不变，原 261 条 Evidence、253 条 Verification、Semantic/Metric 定义完全不变；原 Journal、Ledger、Artifact、Checkpoint 和其他既有行均保留原 hash。只追加四个隔离测试 Run 的执行元数据，没有摄取、Seed、迁移、删除或改写旧 Run。

本地记录：[输入测试 JUnit](../artifacts/p7/phase3c-original-goal/unit.xml)、[集成 JUnit](../artifacts/p7/phase3c-original-goal/integration.xml)、[失败日志](../artifacts/p7/phase3c-original-goal/integration.log)、[512 边界探针](../artifacts/p7/phase3c-original-goal/boundary-probe.json)、[前后数据库核验](../artifacts/p7/phase3c-original-goal/after-database.log)、[最终完整性记录](../artifacts/p7/phase3c-original-goal/validation.json)。材料未上传，原文/向量未进入公开 Trace。

## 5. 实施判断与停止

**原问优先本身值得保留为最小候选，但目前不足以批准直接生产实施。** 必须先明确缺事实任务的业务完成表达；不宜通过降低召回、强迫所有背景检索 unavailable，或把因果证明全部前置给 RAG 来掩盖这个问题。

本轮没有实施生产方案。若以后另获授权并解决完成状态边界，最小方向是在原 Worker 生成首个工具调用前提供可信原问候选，复用原 ToolRegistry/Journal/预算；不得在调用已经登记后偷偷替换 query。真实模型是否遵循、能否在缺事实时选择 insufficient、混合/长目标如何安全处理仍未验证，不能用脚本化成功代替。

已停止在 Phase 3C；未调用 DeepSeek、未重跑历史 Holdout、未进入 Phase 4/Gate 3、未暂存/提交/推送。
