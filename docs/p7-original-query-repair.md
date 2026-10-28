# P7 第三步：首次宿主原问策略

本轮只实施 `original-first-v1`，不实现第二次 fallback、不改变检索模型/0.55阈值/Top-k/两次上限、不调用 DeepSeek、不重跑历史 Holdout、不自动提交推送。前两步 Partial Evidence 与引用政策保留。用户“进行第三步修复”是本轮工程授权，不是付费 Live、默认网站启用或 Gate 3 的授权。

**协议/执行正确性与检索质量分别验收。** 新策略能够提供并强制首查使用宿主子目标、拒绝静默参数改写，并沿用原恢复机制；一个公开英文控制仍空召回，这是未解决的质量失败，不能因 pytest 合约检查通过而说业务已正确完成。

## 最小执行策略

1. 可信宿主显式设置 ReportScope.rag_query_policy=original-first-v1，默认 legacy。
2. Coordinator 只对 RAG Worker 传入 ReportService.rag_question，即原 DocumentGoal.question；不取 Planner 自行生成的 TaskSpec.instruction，也不拿包含多个指标的全局问题替换子目标。
3. ToolRegistry 使用原 SearchArguments 校验非空白且最多512字符，并核对原 retrieval_goal 的完整要求及 MCP 原目标 Hash。原文不翻译、裁剪、去空格或 Unicode 归一化。
4. 在模型生成工具参数之前，search_documents 的 query 参数说明提供 JSON 编码的 HOST_FIRST_QUERY_JSON。该说明在整个任务内保持不变；避免已提交工具超前于 Checkpoint 时因首查说明变化而产生不同模型调用身份。
5. 模型实际输出的第一次 query 若不完全相同，返回明确、不可自动重试的 RAG_QUERY_POLICY，Worker 失败终止。原始 assistant/tool_call、参数、ID、失败反馈与 Journal fingerprint 保留，绝不偷改成宿主参数。
6. 第二次搜索仍可由模型决定原目标内的查询；没有新增自动查询、翻译、fallback、修复回合或预算。原 MCP Scope、相关性、完成协议、事实/P3验证仍独立执行。

模型遵循工具说明、第一次返回原问后，调用正常通过；若不遵循，则安全拒绝。未实测 DeepSeek 对该说明的遵循率，不能承诺一定改善真实模型完成率。

## 必要代码与版本边界

| 既有文件 | 本轮增量 |
|---|---|
| `src/datapilot/reporting/contracts.py` | 一个可信宿主字段 rag_query_policy，枚举 legacy / original-first-v1；新模式要求非空文档目标。默认值不序列化，维持旧 Scope/Artifact/Manifest 字节。 |
| `src/datapilot/orchestration/coordinator.py` | 根据宿主策略和 Worker 能力派生 original_query，仅绑定 RAG 子目标。 |
| `src/datapilot/orchestration/tools.py` | 一个派生配置 original_query；校验绑定、提供稳定参数说明、核对首查参数。复用原 search_attempts、调用配对、Journal 与配额。 |

没有改 Worker Loop/System Prompt、Gateway、ContextManager、预算算法、Journal/Saver、权限/迁移、P3、Report 事实规则、Gold 或 Scorer。Tool Schema 说明是提示，真正约束在执行端；它不是授权机制。没有新增状态表、工具或第二套恢复引擎。

新字段随原 ReportScope 进入 Manifest 和报告授权 Hash。旧模式序列化不含该字段，旧式配置的新 Run 可复用终态；跨策略恢复返回 RECOVERY_IDENTITY。没有恢复或重算任何历史 Benchmark Run。未知 issued 调用仍保守阻断，不根据故障位置猜测它没有执行。

现有 Web task_payload/UI 不读取该新策略，**网站默认保持 legacy**。可信 Python 宿主显式构造新 Run 的例子：

```python
scope = ReportScope.model_validate_json(
    trusted_scope.model_copy(update={
        "rag_query_policy": "original-first-v1",
    }).model_dump_json()
)
# 原 run_durable(report_scope=scope, ...)；不得把模型/客户端策略字段当宿主授权。
```

前两步的 partial_evidence_policy/citation_policy 可以按原批准契约共同绑定，本轮没有自动批准新事实或新指标定义。

## 定向测试和真实执行

新增 `tests/test_original_query_policy.py`、`tests/test_original_query_postgres.py`、`scripts/original_query_probe.py`。后者只通过原 run_durable 和既有 fault hooks 验收，脚本 Fake 在返回 AIMessage 给 Gateway 之前选择 query；不是修改真实模型已登记的参数，也不是新 Runner/Scheduler。

32项新单元/协议用例覆盖中英文/混合/引号/512字符边界、空白/超长/错误目标、SQL和Scope伪造、两次上限、取消、兄弟隔离、旧 Hash、预算耗尽、Native AI/Tool配对、全局问题/Planner文本不覆盖子目标，以及公开客户端不能启用宿主策略。其中2项运行真实 LangChain/OpenAI SDK，但 HTTP 被 httpx.MockTransport 完全拦截；不是 DeepSeek API 实验。真实 HTTP JSON 中 Thinking 保持 disabled，query说明及 tool_call_id/arguments 不丢失。

真实 PG17/pgvector、本地固定 BGE ONNX 与 MCP 验证17项执行契约：公开中文 cp09/cp07/cp06/cp12/cp05、一个英文控制；Worker模型响应/工具提交/报告提交处硬退出；第二次模型自选搜索及提交反馈复用；未知结果；错误首查；权限撤回；旧策略冲突；同 call_id 改译文的 RECOVERY_CONFLICT；512中文字仍触发原 EMBEDDING_LIMIT，无静默截断。

引用/事实/P3链路真实使用前两步实现。缺少离线例外或因果证据继续 partial；缺少提升幅度继续 unavailable；P3证据及补充引述不因首查策略变为新结论。两次搜索的恢复确认使用第二次实际提交的工件，而不是丢弃它或重做检索。已完成模型调用不重新结算；首次搜索后尚未发生的提交决策允许一次正常新 Fake 调用，不误称为所有恢复均零新增决策。

新 Run 的调用、完整工件、引用、预算和 terminal report 跨进程一致。Schema新增说明的输入成本仍由原 Gateway 预留；没有增加预算额度或假装少算 Token。脚本声明的 usage 只用于账本测试，不能当实际供应商 Token/账单。

## 英文质量失败：保留与分层

最初英文控制夹具属于另一个隔离实例，MCP 正确以 DOCUMENT_NOT_AUTHORIZED 拒绝，没有复制旧 Run/旧库。随后只在当前隔离实例追加一个新的公开合成英文控制 Corpus，使用原受限 IngestionService、已固定 BGE 和一份已有公开英文 keys.md 的原字节副本；没有重新摄取或修改旧 Corpus。测试夹具曾误用 LocalEmbedding(settings)，修正为原无参接口 LocalEmbedding()，失败日志保留，产品 Embedding 代码未改。

原始英文问题固定为 `How should API keys be rotated?`，已原文通过模型参数→Journal→MCP。唯一候选在当前新增英文 Corpus 中的阈值前得分 **0.5200636541862387**，低于 **0.55**，因而 no_matches、报告 unavailable。只读诊断复用原 Dev 的受限 Reader，不向生产模型暴露阈值前候选。

这个控制的业务预期仍为 completed，**实际 unavailable，质量不正确**。不更换问题、文档、Embedding、阈值来刷通过，也不把它改成合法拒答 Gold。最初业务状态断言失败保留；最终 pytest 验证的是参数忠实、空结果不得伪造 completed、恢复一致，另写 english-quality.json 保留原业务预期与实际失败。机器报告必须独立列出这一失败，不能把17项协议测试当作17项正确业务答案。

本轮六个控制输入中五个中文输入符合各自预期，英文一项未达业务预期；重复运行是回归而非新的独立样本。没有做公平新 A/B 或稳定成功率研究；不使用这六项外推总体质量，不改变任何历史分数。这只解释本轮英文控制，不宣称定位了历史 bh2-026/030 的唯一原因。

## 验证与封存

第一批新增契约在实现前为3 failed / 1 passed。最终 Python3.11/3.13 单元、HTTP Mock及原 Context/预算定向回归各 **350 passed**。真实 PG/MCP 的最终两版本结果、耗时、质量记录与历史完整性见 [机器验收记录](research/p7-original-query-repair.json)。没有完整 pytest、浏览器、CI 或真实模型实验。

最终真实 PG/MCP/跨进程合约：Python3.11 **17 passed，280.07秒**；Python3.13 **17 passed，283.21秒**；每版本共367项合约/安全测试通过，无 skip/xfail。Ruff 通过，265个文件格式检查通过，git diff --check 返回0。**这不包含“英文业务质量正确”的结论**，该控制仍按上一节列为失败。

最终只读核验保护1859份既存文件和78377条既存数据库记录：只有三个授权源码出现差异，前两步封存原件、旧 Gold/Seal/Scorer/历史结果均未改写，既存数据库行无修改/删除。本轮新增54个脚本 Fake 测试 Run（含重复回归和故障负例，不是正式54 Runtime Campaign）、4组 P3 Evidence/Verification、对应 execution/checkpoint，以及一个新增英文 Corpus/Index/Source/Chunk。没有新增 Dataset、Schema 或权限，也未使用旧 Permit。

日志/JUnit/源码原件和实验失败位于忽略目录 `artifacts/p7/original-query-repair-v1/`。既有文件和数据库行在开始前记录 Hash，结束只读核对；有意源码差异单独列出，不能把当前工作副本宣称仍符合旧 Source Freeze。新实现快照只服务非付费验收，不是付费 Permit 或正式新 Holdout。

命令在仓库根目录执行；PG模块先核验当前隔离 Docker 身份、再加载专用角色连接。英文控制绑定只在第一次创建，之后复用；不 Seed、不清库、不删除 Volume。

```powershell
$env:PYTHONUTF8='1'
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest tests/test_original_query_policy.py tests/test_citation_policy.py tests/test_partial_evidence_report.py tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_cross_source_report.py tests/test_rag_completion.py tests/test_rag_completion_transport.py tests/test_orchestration.py tests/test_orchestration_hardening.py tests/test_persistence_contracts.py tests/test_rag_only_web.py tests/test_snapshot_requirements.py tests/test_context_engineering.py tests/test_context_boundaries.py tests/test_budget_aware_context.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/test_original_query_postgres.py -q -p no:cacheprovider
# Python3.13 换用 .venv-313\Scripts\python.exe。
.venv\Scripts\ruff.exe check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
.venv\Scripts\ruff.exe format --check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
git diff --check
```

下一步真实模型遵循率、英文召回优化、网站默认接线、完整回归或付费 Smoke 均需要另行限定任务。当前不建议仅凭脚本测试默认全量启用，更不能声称英文质量问题已修复。完成第三步的最小实现与定向验收后停止。
