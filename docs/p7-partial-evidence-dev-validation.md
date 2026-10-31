# P7 Partial Evidence 独立 Dev 验证

结论：**Dev 受限视图验证通过；生产实现与新 Candidate 持久恢复仍未实施。** 没有改动 `src/`、v3/v4 Scorer、历史 Gold/Seal、Prompt、检索/预算/P3 规则，没有付费模型或旧 Campaign 恢复。

## 已确认根因与实际链路

029 已取得可信非空片段、minimum_sources=1，但模型提交 insufficient。原提交 Verifier 对该 insufficient 本身合法；它不证明所有业务事实。030 只有两份必需来源之一，第二次中英改写空召回，第三次搜索被正确限额拒绝；不能将其改成 complete。

实际代码路径：`loop.py`/ToolRegistry 提交→`rag_completion.validate_submission`→持久 Receipt→`Coordinator.execute` 保留 refs，并把 insufficient 映射为 unavailable→原五层编排核验→`Coordinator.envelope` 对报告排除非 succeeded 的 RAG refs→`ReportService.build` 再按 source_statuses 过滤→先检查来源数量/主题/指标，再做 `fact_coverage`→BusinessCompletion。

丢失发生在 Coordinator 的报告依赖过滤与 Report 的 source_ready/来源数量前置门控。原 TaskResult/Artifact 已经保留片段；无需让 Worker 冒充 succeeded，也不需要新检索器或第二套 Verifier。历史 029/030 的判定不变，本轮不重新执行或重评分。

## Dev 候选数据流与权威边界

`evaluation/p7_citation_dev/candidate.py` 的 LimitedView 只存在于独立 Dev 层，`mode=dev_projection_only`。它不是 CrossSourceReport，不写回 Worker、P3、Journal verdict 或官方 Checkpoint。

1. 可信宿主提供原 ReportScope、Dataset/Source/Index Pin、已确认字面 Fact 与必需 Source 集合。
2. 通过原 `validate_submission` 检查 receipt IDs、任务/版本、工件归属、原授权/hash；所有 retained refs 必须与提交集合相同。
3. 原 MCP `validate_result` 再核对来源；原 `qualifying_documents` 只保留宿主目标相关片段。
4. 原 `fact_coverage` 核对预先定义的引述，不从非空、相似度或模型声明推断事实。
5. 已证明事实、缺失事实、来源覆盖、收据状态与 P3 verdict 分别输出。insufficient 永远不在候选中变成 completed；来源不足仍显式 missing；因果仍未验证。
6. P3 数字单独走原 `verify_metric`、六层验证与持久引用；文档背景不成为财务数值或图表。

本轮没有新增生产 DTO/数据库字段。现有 DocumentReference、EvidenceRef、DocumentGoal/DocumentFact、MetricBridge、BusinessCompletion 已能表达大部分内容。Dev 的 LimitedView 只是可测设计载体。

## 12 个新场景

所有内容、数字、来源、问题与 Gold 为全新公开合成 Dev；不是重命名旧029/030。源内容与期望在查询前保存 `dev-spec-before-observation.json`，物化后固定 Dataset/Corpus/Index/model manifest。新语料没有写入任何旧 Holdout Corpus。

| Dev | 业务/边界 | 原路径 | Dev 候选 | 事实与收据 |
|---|---|---|---|---|
| cp01 | 研讨会席位锁定 | completed | completed | 单来源完整，18小时引述有证明 |
| cp02 | 域名验证与复核 | completed | completed | TXT 与两个工作日复核，两来源完整 |
| cp03 | 储值券退款与地区例外 | partial | partial | 三个工作日已证明，地区例外未知 |
| cp04 | 供应商验收与赔付 | unavailable | partial | 负责人签署已证明；第二份合同缺失；insufficient 不变 |
| cp05 | 短信对续费提升 | unavailable | unavailable | 有背景，无提升数值/试验证明 |
| cp06 | 打印水印与离线例外 | unavailable | partial | 身份水印已证明，离线例外未知；insufficient 不变 |
| cp07 | 新账单收入与补寄承诺 | partial | partial | 原 P3 verified 637.45 CNY；送达保证未知 |
| cp08 | 回调签名与混合授权 | blocked | blocked | 对相同非法 scope/混合来源，原验证器与候选均拒绝 |
| cp09 | 配额单位与舍入补充 | completed | completed | 主事实与补充 Claim 分开核验；政策仍待裁决 |
| cp10 | 工单计时与果园背景 | completed | completed | 工单事实有证明；另查到的无关背景未发布 |
| cp11 | 客服排班新旧版本 | blocked | blocked | 正常新版本对照可完成；混入旧 Index 后双方均拒绝 |
| cp12 | 新手卡片与因果 | partial | partial | 三步骤已证明；激活率因果未验证 |

cp08/cp11 的正常原始控制报告保留为 completed，但不拿正常输入与损坏输入比较收益；表格的 blocked 指相同负面输入的原验证器与候选结果。真实旧版本混入、跨 Corpus 混合、错误 hash/version/span 身份分别验证，没有将合法来源的正常控制误写成越权事故。

## 结果与分母

| 指标 | 原路径 | Dev 候选 | 分母/含义 |
|---|---:|---:|---|
| 正常场景状态符合独立 Dev 期望 | 8/10 | 10/10 | 另有两项安全负例，不混为普通业务题 |
| 支持的必需文档事实 | 7/15 | 9/15 | 包含故意缺失的事实；不是所有目标已完成 |
| partial 场景中已有文档事实保留 | 2/4 | 4/4 | cp03/04/06/12；P3 单独计算 |
| partial/unavailable 状态正确 | 4/6 | 6/6 | 五个 partial 加一个 unavailable |
| False Completed | 0 | 0/4 | 候选发布 completed 的4项，无缺失事实或来源 |
| 混合授权/旧版本负例 | 拒绝 | 拒绝 | 2/2；引用真实性没有放宽 |
| 独立 P3 账单指标 | 1/1 | 1/1 | 新63745分已付、1199分未付；63745/100=637.45 CNY |

每个场景的 Required Source Coverage、Fact IDs、missing、Artifact SHA 与 Source Index 在[结构化结果](research/p7-partial-evidence-dev-results.json)。cp04 来源覆盖仍为1/2；候选保留签署事实，没有补建合同。未授权引用、非法引用、未经证明事实泄漏均未在这些固定场景出现；不据此声称总体风险为零。

## 真实基础设施、恢复与测试

使用已核验隔离容器 `datapilot-p7-unified-postgres-1`（PG17+pgvector）、新 owner/Corpus 范围、本地 BGE ONNX、原 MCP Reader/Tool 参数校验、原0.55/Top-k5/两次搜索。仅追加新 Dev；没有迁移、Seed 或旧表清理。cp07 通过原受限 Ingestion/Registry 接口创建玩具数据与显式测试宿主定义；`reviewed=True` 是合成夹具宿主决策，不是替用户审批生产口径或虚构人工签名。

新建一个 cp06 Run 实际经过原 LangGraph Worker、ToolRegistry、MCP、Stop Hook/提交、Verifier、Report、Journal/Checkpoint。3次模型决策均为明确脚本 Fake，3条工具/宿主日志已 complete，无真实供应商调用。两个独立 Python 进程用 NoModel 恢复终态：原工件、收据、报告、usage/调用指纹相同；从同一持久工件重建 Dev view 哈希也相同。

**没有把 Dev view 写入生产 Checkpoint，也没有验证新候选的崩溃恢复/unknown-outcome 新行为。** 原终态复用通过，不等于新的 Partial Evidence 持久产品链路已经验收；这些仍是后续实施必测项。

Python3.11/3.13 各 **117 passed**（103单元/契约及原 Report/RAG 定向回归，12项真实 PG/MCP 场景，2项真实轨迹/跨进程记录核对）。额外真实 MCP Claim-policy 探针验证补充引述、伪造引述、Required 缺失、无关背景过滤与混合越权拒绝。未运行完整985项、CI 或付费模型。

保留工程失败：初次 Docker 未启动；新 Dev 首轮将定点字符串直接与637.45比较中止，改为 Decimal 后通过；新 Run 已提交但导出 helper 未将 Artifact DTO 转 JSON，随后仅用 NoModel 复用终态补采，未重发模型/搜索；两个新反例的异常捕获边界曾写错，修正测试后通过。原日志/JUnit/新增 P3 Evidence 均保留。

## 最小生产改动候选与禁止范围

| 位置 | 已复现/现状 | 后续最小方案与测试 |
|---|---|---|
| RAG Submission/Receipt | insufficient 合法保留真实 refs | 不改 outcome/verdict；新增测试非空 insufficient、两来源不足与已提交收据重放 |
| Artifact / TaskResult | 数据已保留，无需另存来源 | 复用原 refs/hash/owner；拒绝非提交工件、跨任务/版本和重复 Chunk 计数 |
| Coordinator.envelope | 报告排除 unavailable RAG refs | 新宿主版本策略下只传经原验证器接受的部分 refs，不伪造 succeeded；测依赖失败/撤权/取消 |
| ReportService.build | source_ready 与 minimum_sources 阻止已知事实 | 将“受限事实展示”与“整个文档目标已覆盖”分开；来源不足保留missing，绝不completed |
| BusinessCompletion | 现 DTO 可表达 partial、缺失与受限结果 | 复用 fact_coverage；已验证P3与文档事实分别计，不新增第二业务 Verifier |
| DocumentGoal | 现可信引述已能核验部分事实 | 不改解释/事实证明标准；补 source不足、无证据、因果与同Source多Chunk测试 |
| Citation/Scorer | 来源标签政策问题与产品不同 | 先负责人裁决；新版本协议/Gold；不改冻结v3/v4或Required Source门控 |
| Durable/Journal | 原refs恢复与预算幂等已验证 | 如改变报告行为，用可选且默认旧行为的宿主策略/Manifest版本隔离；旧Run按旧策略重验；新策略不同拒绝恢复 |
| Authorization | 原 MCP 与 hash/version 负例正常 | 不改 Reader/grants/Scope；新生产测试需同Dataset/外Dataset/旧Index/撤权/损坏Artifact |

建议另行授权最小 Partial Evidence 产品修复，但不能把本轮当作已实现。可能需要的唯一新宿主字段是显式版本化的 partial-view policy（默认旧行为），用于避免历史报告恢复被新 build 规则误判；具体形式须先审计 Manifest/序列化兼容，不需要新表。应修改的候选文件主要为 `orchestration/coordinator.py`、`reporting/service.py` 与必要宿主契约/manifest 接线；不能改 P3、检索阈值/配方、预算、Journal 扣账/unknown 判定或冻结评分器。

实施前需补新策略跨节点/跨进程、工具提交前后崩溃、未知结果保守停止、旧报告/新规则冲突、预算与撤权测试。没有这些证据，不建议直接部署或启动新 Live。政策选择仍为 PENDING_OWNER_ADJUDICATION。

## 执行命令与完整性

在仓库根目录、已物化的新 Dev 与已核验隔离实例上执行：

```powershell
$env:PYTHONUTF8='1'
$env:DATAPILOT_RUN_DB_TESTS='1'
.venv\Scripts\python.exe -m pytest evaluation/p7_citation_dev/test_contracts.py tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_rag_completion.py evaluation/p7_citation_dev/test_postgres.py -q -p no:cacheprovider
.venv-313\Scripts\python.exe -m pytest evaluation/p7_citation_dev/test_contracts.py tests/test_document_fact_coverage.py tests/test_report_causal_scope.py tests/test_rag_completion.py evaluation/p7_citation_dev/test_postgres.py -q -p no:cacheprovider
.venv\Scripts\ruff.exe check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
.venv\Scripts\ruff.exe format --check src scripts tests evaluation/p7_v3 evaluation/p7_v4 evaluation/p7_citation_dev
git diff --check
```

JUnit/日志：`artifacts/p7/citation-partial-dev-v1/final311.xml`、`final313.xml` 及对应 `.log`。本机已有实验禁止重新 `prepare`/重新摄取；重建实验需新命名范围及隔离环境，不覆盖现有工件。首次流程的显式入口依次为 `dev.py prepare/observe`、`language_probe.py`、`policy_probe.py`、`durable_probe.py start` 和两个新进程 `resume`，最后 `summarize.py`；这些是 Dev 作者工具，不是生产模型工具。输出使用排他创建，避免覆盖实验原件。

最终 Ruff/format/Diff 均通过。[完整性证明](research/p7-citation-partial-integrity.json) 对照1406份既存文件和69582条既存数据库记录：没有旧文件/记录改写或删除；v4交付Seal的239份文件再次匹配。新增仅为本轮12个Corpus、13个索引版本（含旧版负例）、17个Source/Chunk、一个两行玩具Dataset/P3记录和一个新Durable Run。旧Live仍29 observed/31 not_run、20/29、81次/116059 Token/估算USD0.02674572、正式状态INVALID；v4诊断仍20/29，历史Smoke不变。

新候选/测试/作者脚本位于 `evaluation/p7_citation_dev/`，未添加 Scheduler、恢复引擎或预算账本。最终实验源码哈希与结果封存在忽略目录 `artifacts/p7/citation-partial-dev-v1/RESULT-SEAL.json`。未提交、推送或触发CI，完成后停止。
