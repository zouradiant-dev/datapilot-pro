# P7 Phase 3D：文档事实覆盖与业务完成判定

2026-10-25。**最小契约修复及双版本定向验收完成。** 原 Phase 3C“未提供年限却 completed”反例已由红转绿。RAG 完成收据不变，Report 现在单独检查宿主声明的必需事实；未确认用途或缺少事实不能自动完成业务目标。本轮没有实施原问优先，没有调用 DeepSeek、续跑 Holdout 或修改 Scorer 成绩。

## 1. 根因与修改前证据

旧 DocumentGoal 只有 question、goal_id、metric_goals。纯文档 `metric_goals=[]` 时，ReportService 的相关来源/数量检查通过即可覆盖 documents，缺少“具体事实是否已被证据支持”的契约。

修改生产代码前，用原 Phase 3C 断言及原授权 Corpus 创建全新隔离 Run：报告仍将年限问题标为 completed，原断言真实失败。另用新公开合成文本“本文未规定保存年限”运行正式新单测，也得到 `completed != unavailable`。记录：[真实 PG 红例](../artifacts/p7/phase3d-document-completion/pre-fix.log)、[合成单测红例](../artifacts/p7/phase3d-document-completion/unit-pre-fix.xml)。没有覆盖 Phase 3C 的 19/1 历史记录。

## 2. 最小契约与代码范围

生产代码只改两个文件：

| 文件/新增内容 | 必要性与边界 |
|---|---|
| [reporting/contracts.py](../src/datapilot/reporting/contracts.py)：DocumentGoal.purpose | 宿主显式选择 locate、summary、facts、conclusion；默认 None 表示未确认，不用关键词推断 |
| 同文件：required_facts / DocumentFact | 有界、唯一的事实 ID、描述，以及可选的宿主确认参考、不可变 ChunkCitation 和原文 quotation；没有证明就保持未验证 |
| 同文件：ReportClaim.fact_coverage | 每个必需事实对应真实 DocumentReference 或 None；不升级成 MetricBridge 或 P3 数值 |
| 同文件：校验与默认字段序列化 | 拒绝不完整证明/重复事实/非法用途；旧默认字段不加入旧 JSON 投影，保留历史 Pin/Artifact hash 可解析性 |
| [reporting/service.py](../src/datapilot/reporting/service.py)：fact_coverage | 只对已授权、已验证、满足原目标的实际引用核对稳定 Citation 身份及精确引文；查询分数/目标向量不是源身份 |
| 同文件：build/render | 校验宿主 DTO 与输入 Artifact 引用 hash；缺事实单列 missing_evidence，保留背景/部分事实/P3 结果，展示事实覆盖与缺失原因 |

没有新增模块、数据库字段/迁移、通用 Verifier、Scheduler 或状态机。[reporting/adapter.py](../src/datapilot/reporting/adapter.py) 复用已有 BusinessCompletion 投影，无需修改。

Required Facts 只能来自可信宿主 ReportScope，进入原 Manifest/审批 Pin；RAG Worker/工具没有写入、删减或批准它们的接口。`confirmation_ref` 是宿主确认来源的线索，**不是自动核验外部签名的凭据**，不能用模型填一个字符串冒充真实人工审批。测试使用明确标注的合成宿主契约，不宣称独立人工签署。

## 3. 实际验证能力与新旧行为

本实现只验证“宿主已确认对应关系的原文引述确实存在于匹配的授权版本/片段”。它不做任意自然语言蕴含、法律真实性或开放世界事实证明，不从相似度、非空结果、LLM 自述或检索不到数字推断事实。无可靠确定性支持时保持未验证；开放式结论仍未完成。

| 任务契约 | 新行为 |
|---|---|
| 询问具体年限，但来源未提供、必需事实无证明 | unavailable；documents 不进入 verified_goals，明确 `document_fact_unverified:retention`；可展示原文背景 |
| 已确认的引述明确写“保留七年”，Pin/原文均匹配 | 对应文档事实支持，业务 completed；仅作原文引述，不生成 P3 指标/财务图表 |
| 询问文档是否规定年限，原文明说未规定且宿主确认该解释 | 可以 completed；不把缺少数字一律等同无法回答，也不靠检索空结果证明不存在 |
| 宿主显式声明定位或描述性总结 | 沿用原授权/相关性/来源要求，无需虚构数值字段即可完成 |
| 两个必需事实只支持一个 | partial，保留已支持事实和引用；整个 documents 目标仍不算完全 verified |
| 多份来源相关，但必需事实缺失 | 来源覆盖不能清除事实缺失 |
| 需要因果证明，仅有背景 | partial，保留 `causal_conclusion_not_verified`；不会让 RAG Worker 独立证明因果 |
| causal_requested=False | 不重新做因果关键词推断；有明确总结/事实契约时可正常完成 |
| 没有声明用途的旧 DocumentGoal | `document_goal_unconfirmed`，保守返回 unavailable；已有 verified P3 指标时保留为 partial |

仅有背景时不发布所缺事实；有部分支持时保持 partial。缺失、错误版本、伪造引用/hash、无授权或不足源收据均不能被升级。原 P3 六层验证、Metric/Semantic、SQL 配方、MCP/grants、Embedding/0.55/Top-k、搜索上限、Stop Hook、预算和上下文管理均未改。

**宿主接线边界：** 当前公开 Web 请求/旧 Runner 尚未提供新用途与事实确认入口。未声明的旧文档任务会安全显示待确认，不会自动按文本猜成总结。程序化可信宿主可使用新契约；现有 API/UI 完整确认交互仍需后续接线与回归，本轮不伪称已经完成。未经确认的 P3 定义继续走原 Registry，本次文档契约不批准新指标。

## 4. 测试与真实 PostgreSQL/MCP

新增 [test_document_fact_coverage.py](../tests/test_document_fact_coverage.py) 的 **31 条**公开合成单元/契约用例，覆盖年限缺失/明确引述、文档未规定、定位/总结、部分事实、多来源、因果 True/False、开放结论、错误 Pin/引文/Artifact、非法宿主契约及历史报告冲突。检索/相关性为明确的单元替身，不作为真实模型效果。

新增 [test_document_fact_postgres.py](../tests/test_document_fact_postgres.py) 的 **7 条**真实 PG17 + pgvector + 本地 Embedding + MCP + 原 Worker/Completion/Report/Journal 用例。六种报告场景检索收据均可 complete，但业务分别 unavailable/completed/partial；重复恢复不新增模型/工具调用、不改 usage/工件，实际源引用和 hash 继续重验。

本机复用 Phase 3B Corpus；只追加一次两文档事实夹具，两个 Python 版本共用。测试在没有私有 Phase 3B 文件的新环境中可建立公开合成来源，不以私有 Gold/模型响应作输入。该新环境分支未运行完整 GitHub CI；本机验收使用已核验的隔离实例和实际 Pin。

| 最终定向集合 | Python 3.11 | Python 3.13 |
|---|---:|---:|
| 新事实契约 + Report/P3 原因传递/因果 + RAG Completion + RAG-only Web 契约 | 124 passed | 124 passed |
| 新真实 PG/MCP 事实覆盖/持久恢复/引用拒绝 | 7 passed | 7 passed |
| 既有 Phase 1/2 真实 PG/MCP 定向回归 | 3 passed | 3 passed |
| 每版本不同用例合计 | **134 passed** | **134 passed** |

Python 3.13 首次补跑中有两项 Windows 临时目录 setup 错误，原日志保留；改用原运行器允许的、事先不存在的仓库内临时目录后，两项通过。没有以 skip/xfail 或修改业务逻辑隐藏错误。历史只读检查初稿误把纯文档未确认状态预期为 partial，实际为 unavailable；只修正诊断断言并保留初稿日志，没有改变产品完成标准。

最后加固了新 PG 文件的显式 opt-in 收集守卫，避免高作用域夹具在非 PG 测试中先初始化。两个版本关闭 opt-in 时均为 7 skipped，这是安全守卫结果，不计入上表通过数；开启时真实 Pin/权限用例各 1 passed。测试体与夹具未变化，复用此前各 7 项真实通过记录，没有为收集条件改动重跑整套实验。

关键命令（日志均在本机忽略目录）：

```powershell
# 两个解释器分别执行，同一组本地用例
.venv\Scripts\python.exe -m pytest tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_cross_source_report.py tests/test_p3_refusal_reasons.py tests/test_rag_completion.py tests/test_rag_only_web.py -p no:cacheprovider -q
.venv-313\Scripts\python.exe -m pytest tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_cross_source_report.py tests/test_p3_refusal_reasons.py tests/test_rag_completion.py tests/test_rag_only_web.py -p no:cacheprovider -q
# 两个版本各执行新 PG 文件；Phase1/2 用原隔离运行器另跑
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_document_fact_postgres.py -p no:cacheprovider -q
.venv-313\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_document_fact_postgres.py -p no:cacheprovider -q
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_phase12_postgres.py --basetemp=artifacts/p7/phase12-integration/<全新目录> -p no:cacheprovider -q
```

结果：[3.11 本地 JUnit](../artifacts/p7/phase3d-document-completion/final-unit-py311.xml)、[3.13 本地 JUnit](../artifacts/p7/phase3d-document-completion/final-unit-py313.xml)、[3.11 新 PG](../artifacts/p7/phase3d-document-completion/final-core-pg-py311.xml)、[3.13 新 PG](../artifacts/p7/phase3d-document-completion/final-core-pg-py313.xml)、[3.11 Phase1/2](../artifacts/p7/phase3d-document-completion/phase12-pg-py311.xml)、[3.13 首轮及权限错误](../artifacts/p7/phase3d-document-completion/final-pg-py313.xml)、[3.13 两项补跑](../artifacts/p7/phase3d-document-completion/phase12-pg-py313-retry.xml)。没有重跑已通过且未变的整套测试来放大用例数。

原 Phase 3C 断言也在全新 Run 中直接通过，见 [真实 PG 红转绿](../artifacts/p7/phase3d-document-completion/post-fix.log)。全部模型决策为受控脚本/Fake，测试 usage 是声明值，不是 DeepSeek Token、费用或效果实测。没有运行全仓 pytest、浏览器、API/UI 全验收或 GitHub CI。

## 5. 历史兼容与完整性

bh2-024 仅只读核对原签名采集、P3/RAG 引用并重新投影，没有恢复旧任务或评分。原报告仍为 partial；当前旧宿主未声明文档用途，投影为 unavailable。其他原报告字段保持一致；`verify_report` 正确返回 `REPORT_EVIDENCE_INVALID`。持久 Inspector 仍先因 Docker/宿主 reader 端点 Pin 不同返回 `RECOVERY_IDENTITY`，未绕过 Manifest，也不把它说成完整旧端点恢复已验证。见 [只读兼容记录](../artifacts/p7/phase3d-document-completion/old-report-check.json)。

默认字段序列化保留旧 JSON/hash 可解析性，**不保留不正确的旧业务判定**；不静默迁移、重写或重新批准旧报告。没有新增运行规则兼容引擎或数据库迁移。

本轮只改上述两个生产文件、两个既有测试夹具（显式声明原本的总结目标）、新增两份测试和本报告；其余原有文件包括 Phase 1/2 核心、用户 v2.4/v2.5、Gold v1/v2 Seal、Scorer v1/v2、原采集及费用记录保持原 hash。新增字段/校验/序列化都有直接契约或历史完整性用途，无多余 Scheduler/框架逻辑可清理。

数据库前后逐行 SHA 对照确认：原 **261 Evidence、253 Verification、118 Semantic、131 Metric** 及原执行/RAG 元数据全部保留原 hash；只追加公开夹具和测试 Run，未 Seed、清库、删卷或更新旧来源。P7 首次 Live 的 31 条观测、29 not_run、Scorer v2 **26/31** 和首次调用/Token/费用均未改，本修复不追溯计入成绩。

最终源码/测试 hash、Diff 范围、逐项静态结果和数据库追加统计见 [最终验证记录](../artifacts/p7/phase3d-document-completion/validation.json)；[最终源码冻结](../artifacts/p7/phase3d-document-completion/final-source-freeze-v3.json) 保留先前冻结、测试夹具独立性及 opt-in 收集加固历史。Ruff check、修改文件 format --check、git diff --check 均通过；已有 LF/CRLF 提示保留。

## 6. 结论与下一步边界

Phase 3D 的报告层最小修复和定向验收通过，适合封存为待统一回归的开发成果。原问优先仍有后续实施价值，但本轮没有接入生产；真实模型是否遵循查询策略、是否诚实提交 insufficient、宿主确认入口及完整 API/UI/恢复兼容仍需后续独立验证。开放式事实和因果证明不在当前确定性能力内，不能靠模型自评升级。

未调用 DeepSeek、未续跑/重评分原 Holdout、未进入 Phase 4/Gate 3、未提交或推送。完成后停止。
