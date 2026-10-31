# P7 Phase 3A：RAG 召回失败诊断

2026-10-25。本轮只诊断，未修复产品。**独立 Dev 复现了“英文改写对中文文档评分下降，相关候选被 0.55 过滤”的机制；不能据此确定 bh2-026 的唯一根因。** 原案例没有阈值前排名，本轮未重跑、重评分或修改原 60 条 Holdout。

## 1. 实现与实验边界

审阅 [Scorer 审计](scorer-audit.md)、`rag/storage.py::Repository.search`、`rag/mcp.py`、`orchestration/tools.py`、`rag_completion.py` 和 Worker Loop。原流程先校验 Corpus/Source/IndexVersion，再以 `1 - cosine_distance` 排序、取 Top-k、按 Scope 的 0.55 过滤；返回引用另有原始宿主目标的 `goal_score` 校验。查询分数和目标相关性是两次不同检查，后者不能挽回已被前者过滤的片段。

复用既有隔离容器 `datapilot-p7b-postgres-1`（55440 / `datapilot_p7b`，PG17 + pgvector 0.8.6），没有迁移、重新 Seed、重启或清理数据库。可信摄取流程只追加两个新 Dev Corpus；授权回归夹具另追加一个新测试 Corpus。中文来源复用公开合成 `tests/fixtures/rag/*.md`，英文为独立编写的翻译，均包含 onboarding、billing、release 三份文档。

模型仍为本地 `BAAI/bge-small-zh-v1.5/Qdrant-onnx`，revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，512 维；验证既有 ONNX/tokenizer SHA，使用原推理 recipe 和查询前缀，没有下载或更换模型。Chunker 未改，中文 3 chunks、英文 10 chunks。固定 `top_k=5`、阈值 0.55；九条查询与相关来源在编码、查询前写入 [Dev 计划](../artifacts/p7/phase3a-rag-diagnosis/dev-plan.json)。它是作者构造的少量非盲诊断样本，不是新的正式 Holdout。

可信 [诊断脚本](../artifacts/p7/phase3a-rag-diagnosis/diagnose.py) 仅用 `datapilot_rag_reader`、READ ONLY、原超时及精确新 Dev Pin，最多检查 64 个候选；真实 MCP 仍只返回原工具允许的结果。脚本没有数据库写入，不注册新工具，不扩大模型可见数据或权限。向量和正文仅在本地私密进程内复算，诊断 JSON 不输出正文或向量。

## 2. 查询与对照结果

A 为中文原问→中文文档；B 为同一问题的英文改写→中文文档；C 为中文改写→中文文档；D 为英文问题→英文文档。A/B/C 每个主题的宿主原目标、Scope、Corpus 和 IndexVersion 完全一致；D 的目标与 B 的英文查询一致。

| 主题 | A 原问 | B / D 英文查询 | C 中文改写 |
|---|---|---|---|
| 入门 | 哪些办法能够帮助新用户尽快掌握产品并体会价值？ | What steps help new users learn the product and experience its value sooner? | 新客户上手时可以获得哪些引导，以更快感受到软件的价值？ |
| 账单 | 已付款账单收入与按月订阅合同金额有什么不同？ | What is the difference between paid invoice revenue and monthly recurring subscription revenue? | 已支付收款和订阅的经常性月收入应如何分别核对？ |

下表分数为最佳相关 chunk 的真实查询余弦分数；“来源数”按 Source 去重，不能以 chunk 数代替。

| 主题 / 变体 | 相关候选原排名 | 相关分数 | MCP 返回 chunks / 全部来源 | 过滤后相关来源 |
|---|---:|---:|---:|---:|
| 入门 A | 1 | 0.56672 | 1 / 1 | 1 |
| 入门 B | 1 | 0.47476 | 0 / 0（no_matches） | 0 |
| 入门 C | 1 | 0.60298 | 1 / 1 | 1 |
| 入门 D | 1 | 0.67726 | 3 / 1 | 1 |
| 账单 A | 1 | 0.74118 | 1 / 1 | 1 |
| 账单 B | 2 | 0.40413 | 0 / 0（no_matches） | 0 |
| 账单 C | 1 | 0.78656 | 1 / 1 | 1 |
| 账单 D | 1 | 0.70688 | 5 / 2 | 1 |

两个 B 的相关文档已在阈值前 Top-5，随后被 0.55 过滤，并非文档不存在。账单 B 的第一名是干扰 release 文档（0.42592），相关账单文档第二（0.40413），两者均不过阈值。对应相关中文文档与原中文宿主目标的分数仍为 0.56672 / 0.74118：本例丢失发生在查询评分过滤阶段。Dev 翻译保留了问题主题，但不能替原模型证明历史改写没有偏离业务目标。

另一个固定双来源控制查询“客户入门培训与已付款账单收入口径”，要求入门与账单两份来源：原排名 1/2、分数 0.61761/0.56727，MCP 返回两份，相关来源覆盖 2/2。未在此小样本观察到必需 Source 覆盖不足。入门 D 的三个 chunk 全来自同一 Source；账单 D 的第二个 Source 是非目标 release 干扰项（0.62737），虽超过查询及目标相关性阈值，也不能作为所需账单事实。**分数、来源数量和宿主检索完成检查均不等于最终业务事实充分或结论正确。**

## 3. 排名、身份与完成协议诊断

所有候选均核对新 Dev 的 owner、Corpus、精确 Source/Document Pin、IndexVersion、原件 hash、chunk span/hash 与向量 hash。A/B/C 的 Pin 未变化；真实 MCP 的结果 ID、排序和分数与诊断的原 Top-k + 0.55 过滤一致。PG `<=>` 与独立 NumPy 余弦复算的最大绝对误差为 `1.263722023692182e-07`，符合浮点精度差异，没有发现距离方向或相似度公式的确定性错误。

原完成逻辑按相关 Source 去重，而非将多个 chunk 当多个 Source；需要目标绑定、有效引用及满足检索要求，不仅检查非空/hash。Dev 对返回工件调用原 `validate_submission`：七条非空对照通过检索完成前置检查，两个空检索明确证据不足。这不是运行真实 LLM Worker，更不是七次业务分析成功。

原 Worker 仍最多两次检索并共享一次 Stop Hook 纠正。相关定向回归通过；本轮没有真实模型，**不能判定模型是否错误地提前终止或如何自主改写**。原 bh2-026 已使用两次检索额度，仅凭其 unavailable 不能认定提前停止。

## 4. 判断与最小后续建议

没有确认需要立即修复的通用确定性代码 Bug。已观察到跨语言查询的排序/阈值风险，以及 chunk 重复和高分干扰来源；现有安全边界按配置执行。样本仅两个主题，英文翻译长度与 chunk 数不同、没有盲审，也没有历史阈值前分数，因此不能将语言因素认定为 bh2-026 的唯一原因，或估计总体错误拒答率。

值得在另行授权的下一阶段做最小 Dev 查询策略对照：保持模型、0.55、权限、完成协议和原两次检索预算，比较“优先原目标语言 / 空召回后的同语言改写”与当前策略；不得静默截断超过工具 512 字符限制的目标。预期可减少这类语言诱发的空召回，但收益及业务正确性需要新 Dev 和新冻结评测验证。目前没有依据直接降低全局阈值、换模型、加次数或 Reranker。**本轮未修改 RAG Agent 或实施该建议。**

## 5. 实际验证与留存

Python 3.11 定向 pytest：**8 passed，2 个预导入警告，0 failed / skipped**（6.32 秒）。其中真实本地 Embedding/PG/MCP 的维度、相似度和 owner/伪造 index 拒绝测试 2 项；模型提交时机、阶段工具收缩、空/非空证据不足与 Stop Hook 的 6 项为原脚本化组件测试，不能称为真实模型质量测试。

执行命令：

```powershell
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_rag_postgres.py::test_real_neural_embedding_dimensions_no_truncation_and_similarity tests/test_rag_postgres.py::test_document_owner_scope_and_forged_index_are_denied tests/test_rag_completion.py::test_model_selects_when_to_submit_and_stops_without_extra_model tests/test_rag_completion.py::test_search_phase_shrinks_but_keeps_read_and_submission tests/test_rag_completion.py::test_empty_and_nonempty_insufficiency_have_distinct_terminal_reasons tests/test_rag_completion.py::test_stop_hook_corrects_plain_response_once -p no:cacheprovider -q --tb=short --junitxml=artifacts/p7/phase3a-rag-diagnosis/targeted.xml
.venv\Scripts\ruff.exe check artifacts/p7/phase3a-rag-diagnosis/prepare-dev.py artifacts/p7/phase3a-rag-diagnosis/diagnose.py
.venv\Scripts\ruff.exe format --check artifacts/p7/phase3a-rag-diagnosis/prepare-dev.py artifacts/p7/phase3a-rag-diagnosis/diagnose.py
git diff --check
```

两份诊断脚本 Ruff/format 均通过，Diff 检查通过（既有文件的 LF/CRLF 提示保留）。诊断脚本只用于本机新 Dev，固定计划、绑定与结果已经留存；摄取脚本只追加新对象，不应为复现随意重复摄取。

本地材料：[全部九条排名与 MCP 结果](../artifacts/p7/phase3a-rag-diagnosis/diagnosis.json)、[版本/来源绑定](../artifacts/p7/phase3a-rag-diagnosis/dev-bindings.json)、[JUnit](../artifacts/p7/phase3a-rag-diagnosis/targeted.xml)、[测试日志](../artifacts/p7/phase3a-rag-diagnosis/targeted.log)、[完整性检查](../artifacts/p7/phase3a-rag-diagnosis/validation.json)。这些材料处于忽略目录，未上传，不能宣称外部可下载。

本轮只新增本报告和本地诊断材料；开始时记录的 434 个既有源码/测试/脚本/锁文件/历史实验与评分文件字节 hash 均保持不变，包括 Phase 1/2 修复。没有修改 P3、Scorer、Gold、原 Seal 或历史成绩；原 31 条已观测、29 条 not_run 和全部失败记录保留。未运行完整 pytest、未调用 DeepSeek、未进入修复或 Gate 3、未暂存/提交/推送。
