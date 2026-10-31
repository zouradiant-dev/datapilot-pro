# P7 Phase 4：预算感知上下文与快照语义

本轮只完成 Phase 4 最小修复与定向验收。当前开发基线 HEAD 为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`；包含前几阶段尚未提交的修改，本报告不把整个工作区 Diff 都归为 Phase 4。不续跑原 Campaign，不调用 DeepSeek，不重评分历史 Holdout，不提交或推送。

## 1. 历史根因复核

bh2-031 原问题为：“复核员需要四月生效的账单更正规则，请使用已经固定的最新文档快照，不能引用第一季度的旧规则替代。”只读核验原签名采集、已有上下文审计及账本副本，没有再次执行该任务。

| 原账本/下一次预留 | Root | `1:documents` Child |
|---|---:|---:|
| Token 上限 | 18,000 | 18,000 |
| 已用 Token | 6,482 | 5,866 |
| 剩余 Token | 11,518 | 12,134 |
| 下一次估算输入 + 输出预留 | 11,897 + 1,200 | 11,897 + 1,200 |
| 若放行后的累计 | 19,579 | 18,963 |

原 Root 已有四次调用，Child 三次，pending=0。原 `BUDGET_EXCEEDED` 是正确保护；下一次请求没有发出。原视图约 11,371 字符，未触发 16,000 字符 × 0.8 的窗口阈值；估算输入加输出 13,097 也未触发 18,000 × 0.8 的上下文阈值。窗口够用与剩余预算够用是两个条件。

原 `unsupported_requirements=true` 则是独立的业务限制。已有 Dataset/version、Corpus/index 和 Document/source hash Pin，但没有可信的“截至某时点最新”或跨来源共同快照证明。不能把固定内容版本改解释成最新上传、最近创建、模型声称最新，或多个来源各自最新。本轮仍不支持该类快照，预算整理成功也不能消除这项限制。

历史复核证据：[只读审计](../artifacts/p7/phase4-budget-snapshot/historical-audit.json)。原问题、Pin、旧 unsupported 和拒绝状态均保留；本报告不是新的 bh2-031 成绩。

## 2. 最小生产修改

| 文件 | 必要改动与边界 |
|---|---|
| [budget.py](../src/datapilot/orchestration/budget.py) | 增加只读 `remaining(account)`，在原锁内取同一祖先链最小剩余调用数与 Token；已预留的兄弟任务额度也计入。它不授予调用权限。 |
| [backend.py](../src/datapilot/persistence/backend.py) | `DurableLedger.remaining` 复用原事务、行锁和账本校验，读取最新持久额度；不增加表、状态或第二套账本。 |
| [context.py](../src/datapilot/orchestration/context.py) | 在原 Gateway 预留前，同时检查窗口与剩余预算；只使用已有 L1/L2/L3。有预算压力但无窗口压力时也可整理，仍不足则明确拒绝。 |
| [rag_completion.py](../src/datapilot/orchestration/rag_completion.py) | 对最新/全局/同一时点快照目标保守标记 `snapshot_not_attested`，仍走原 unsupported/Completion/Stop Hook；只拒绝，不生成 Snapshot ID。普通固定索引读取和字面定位不因此获得“最新”能力。 |
| [service.py](../src/datapilot/reporting/service.py) | 将上述宿主拒绝原因传到原 Report 缺失证据契约，避免折叠为泛化缺文档。Phase 3D Required Facts/用途/引用验证不改。 |

流程从“窗口/冷却触发整理 → 原预留”变为“窗口/冷却或父子预算压力 → 一次有界 L1–L3 → 重估 → 原原子预留”。没有可整理的闭合历史、没有剩余调用数或关闭压缩时，不制造新的调用。仍不足时不提高上限，不循环尝试，不释放在途票据，也不把预算失败改成 completed。

预算独有压力不额外启动收费 L4；真正窗口压力下原 L4 的摘要/后续调用成对预留、验证与保守结算继续保留。`remaining` 是预判：并发期间额度可能变化，最终 `reserve/reserve_batch` 仍是唯一原子准入点，不能凭较早读到的余额越过它。

完整原消息先经原 ArtifactStore 归档，整理只修改模型视图。可信前缀、原目标/授权、Dataset/Source/IndexVersion、Required Facts/ReportScope、Evidence/Citation、未结算工具配对与原 Journal 输入不被摘要重新授权或改写。归档失败仍先拒绝；工具参数不在登记后被替换。没有第二套 ContextManager、Scheduler、恢复引擎或预算 DTO。

## 3. Token 与供应商输入审计

生产估算器保持原公式：完整 LangChain carrier 与工具 Schema 的 JSON UTF-8 字节数 + 128，再加输出预留。这是保守预算单位，不是真实 tokenizer 结果。

检查锁定 SDK 的消息转换，并通过真实 SDK + HTTP Mock 抓取请求，确认 `response_metadata`、`usage_metadata` 和宿主 `message.id` 不在该 Chat Completions 消息体中；实际 `tool_call_id` 关联继续发送。原 carrier 共 11,769 字节；仅消息的 SDK 转换投影为 5,921 字节，后者不包含完整工具 Schema/供应商模板，不能直接当成请求 Token 或“可节省量”。

本轮不凭少量样本降低估算系数，也不替换各供应商输入边界。宿主元数据有重复估入的保守开销，仍是已知限制；没有声称完成全局校准。Mock 返回 input=20、output=10、total=30、cache-hit=6、cache-miss=14，只证明接线；原 Gateway 只按 `usage_metadata.total_tokens` 结算一次，不再叠加 metadata 副本或从逻辑 Token 中减去缓存命中。

历史可读的三次 RAG 调用分别为 1,371 / 2,045 / 2,450 Token，合计 5,866；对应输入命中/未命中分别为 0/1,293、1,280/616、1,920/397。这些是旧 provider 记录，没有新增 API 测量。无 usage、超时或已发出未提交仍保守保留预算，恢复不能假设未执行。

## 4. 定向验证

新增正式测试仅三份：[预算视图](../tests/test_budget_aware_context.py)、[快照拒绝](../tests/test_snapshot_requirements.py)、[真实 PG/MCP/Durable](../tests/test_phase4_postgres.py)。复用原夹具、Registry、MCP、Worker、Report 和恢复接口；隔离诊断/跨进程脚本不提供模型工具或新的业务运行入口。

修复前真实执行得到 **4 failed**：Root、Child、兄弟 pending 预算不足但窗口未满时都没有整理；分析型“最新快照”目标缺少保守能力判断。修复后同一反例均通过，见 [修复前 JUnit](../artifacts/p7/phase4-budget-snapshot/pre-fix.xml)。

2026-10-25 最终定向结果如下。两个版本使用同一生产源码与断言；[定向源码快照 v3](../artifacts/p7/phase4-budget-snapshot/final-targeted-source-freeze-v3.json) 仅用于本轮验证，不是新的 Live Campaign Implementation Freeze。

| 集合（按测试身份去重） | Python 3.11 | Python 3.13 |
|---|---:|---:|
| 本地单元/契约/HTTP SDK Mock | 203 passed | 203 passed |
| 真实隔离 PG/MCP/Embedding/Durable | 21 passed | 21 passed |
| 每版本不同用例合计 | **224 passed** | **224 passed** |

本地首批各 201 passed、1 个 PG 用例显式 deselected；随后只对新增测试文件做必要补跑：快照 import 排版修正后各 11 passed，预算文件增加负数/非整数 usage 后各 18 passed。去重得到 203，不能将补跑重复相加。其余未变断言沿用本轮通过记录，未为凑次数重跑整套。新增正式用例为本地 29 项、PG 7 项。

PG 最终各 21 passed、无失败/跳过，耗时分别 215.60 / 216.24 秒；各有两条 pytest 预导入插件告警。首轮 PG 2 项开发对照及 7 项初测同样通过，但不重复计入上表。Ruff 初次发现两条新增测试 import 排版错误，原日志保留；修正后 `ruff check .`、8 个修改代码/测试文件的 `ruff format --check`、`git diff --check` 均通过，LF/CRLF 提示不作失败。

证据：[本地 3.11](../artifacts/p7/phase4-budget-snapshot/final-unit-py311.xml)、[本地 3.13](../artifacts/p7/phase4-budget-snapshot/final-unit-py313.xml)、[快照补跑 3.11](../artifacts/p7/phase4-budget-snapshot/final-snapshot-py311.xml)、[快照补跑 3.13](../artifacts/p7/phase4-budget-snapshot/final-snapshot-py313.xml)、[预算补跑 3.11](../artifacts/p7/phase4-budget-snapshot/final-budget-py311.xml)、[预算补跑 3.13](../artifacts/p7/phase4-budget-snapshot/final-budget-py313.xml)、[PG 3.11](../artifacts/p7/phase4-budget-snapshot/final-pg-py311.xml)、[PG 3.13](../artifacts/p7/phase4-budget-snapshot/final-pg-py313.xml)。这些是本地忽略目录内的私密验证记录，不作为公开 Trace 上传。

本地定向集合包含：L0–L4/Memory/摘要防伪、父子/兄弟预留、并发余额变化、重复整理、超时/未知用量、SDK HTTP Mock、Phase 1 精确拒答原因、Phase 2 因果 True/False、Phase 3D 事实覆盖与 RAG Completion。缺少版本/来源标识或模型额外 snapshot 参数被拒绝。

真实隔离 PG17 + pgvector（`datapilot-p7b-postgres-1`、`datapilot_p7b`）复用已摄取公开 Dev Corpus 和本地 Embedding。测试模型决策/usage 全部为脚本化 Fake，绝不计作 DeepSeek 效果。压缩开关对照均保持 Root 8 calls/18,000 Token、Child 4 calls/18,000 Token；只扩大测试用窗口以独立制造“窗口足够、预算不足”，没有修改生产默认值或放大账本。

已观察的脚本化对照：关闭整理预算拒绝；开启后 L1/L2/L3 一次，估算输入 12,312 → 8,481，额外摘要调用 0；完成五次模型决策、声明 usage 8,700，Required Fact 仍由真实文档定位。模型视图有损，完整来源无不可逆损失。这不是供应商 Token 节省率或业务成功率实验。

跨进程故障点覆盖：Worker 暂停、`submit_rag_result` 工具已提交、整理后模型响应已返回但未提交。已提交调用按原 Journal 复用；最后一种必须 `RECOVERY_UNCERTAIN`，反复恢复不能重发。恢复时改变 index Pin 被拒绝；重复恢复已完成 Run 使用相同 report hash/usage，不增加模型/工具账。另复用原版本测试检查 Dataset/source/Metric/scope/capability 变化，真实文档 hash/version/source/owner 错误拒绝，以及 Phase 1/2 的持久 P3→Evidence→Report 链路。

主要复现命令（各 Python 版本使用不同的全新临时目录；不运行全仓 pytest）：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_budget_aware_context.py tests/test_snapshot_requirements.py tests/test_context_engineering.py tests/test_context_boundaries.py tests/test_persistence_contracts.py tests/test_deepseek_transport.py tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_cross_source_report.py tests/test_p3_refusal_reasons.py tests/test_rag_completion.py -m 'not integration' -p no:cacheprovider -q
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_phase4_postgres.py tests/test_recovery_versions.py::test_fresh_dataset_metric_and_authority_are_checked_before_resume tests/test_document_fact_postgres.py tests/test_phase12_postgres.py -p no:cacheprovider --basetemp=artifacts/p7/phase12-integration/<全新目录> -q
# 换为 .venv-313\Scripts\python.exe 执行相同集合
.venv\Scripts\ruff.exe check .
git diff --check
```

## 5. 历史保护、限制与后续 Gate

以本阶段开始时的 740 份文件 SHA 为保护基线，最终只有上述五个已有生产文件变化，无文件丢失；Phase 3D `reporting/contracts.py`、前几阶段修复、用户 v2.4/v2.5、Gold v1/v2、Seal、Scorer v1/v2 和原采集/费用文件均保持原 SHA。新增三份正式测试与本报告。五个生产文件合计增加 79 / 删除 13 行；都用于余额接线、已有整理策略的准入条件或拒绝原因，无新增通用框架。私有验证文件在忽略目录，不覆盖旧失败记录。

真实数据库前后逐行 SHA/多重集合核对确认：原 **267 Evidence、259 Verification、120 Semantic、133 Metric、454 Run/Ledger、1,681 calls、1,443 Artifact、5,998 event、4,331 Checkpoint、18,892 checkpoint_writes** 及其余原 checkpoint/RAG/Web 元数据全部未改写或删除。只追加公开夹具/测试 Run；没有重 Seed、清库、删卷或修改旧文档。[数据库完整性日志](../artifacts/p7/phase4-budget-snapshot/final-database.log)、[文件范围](../artifacts/p7/phase4-budget-snapshot/final-file-scope.json) 与 [汇总验证](../artifacts/p7/phase4-budget-snapshot/validation.json) 保留具体计数、SHA、测试与静态检查结果。

首次 Live 仍为 31 条观测 / 60 条分母、29 not_run；Scorer v1 25/31、只读修订 v2 26/31、61 次真实调用 / 77,897 Token 和原费用估算均保留，未生成新的 Campaign/Live 分数。

明确边界：

- **真实基础设施链路**：限定源版本/授权、PG/MCP 检索、归档引用与持久账本/恢复；模型行为为 Fake。
- **HTTP Mock**：实际 SDK 组装和 usage/工具关联；无新增真实供应商 Token、费用或缓存效果。
- **尚不支持**：最新/共同时间点跨来源快照。识别只用于保守拒绝，有限语句模式不是完整自然语言语义解析器；不能据此授予支持能力。
- **仍有局限**：保守字节估算可能提前拒绝；下一次输入+必需输出准入不保证整张 DAG 此后都能完成。未来成本未知时继续有界拒绝，不虚构全任务预算保证。没有 ContextManager 的规划调用仍由原 Gateway 直接保守预留。
- **尚未运行**：P7 统一完整 pytest/真实 PG 全套、API/UI 浏览器、CI、新实现 Campaign Freeze 和任何新的 DeepSeek Smoke。旧端点历史报告的完整恢复限制沿用前几阶段记录，未绕过 Manifest 追认旧报告。

**结论：Phase 4 Passed with documented limitations。** 预算感知整理与快照拒绝原因已通过上述定向验收，适合进入另行授权的 P7 统一完整回归。它不代表完整 P7 或最新快照能力已验收，也不保证历史 bh2-031 在新版本能完成。

后续顺序为 `P7 Unified Regression → New Implementation Freeze → separately authorized DeepSeek Live Smoke`。统一回归通过后才能建立新的实验冻结；新的付费 Smoke 仍需单独授权。本轮到此停止，不自动执行其中任何一步。
