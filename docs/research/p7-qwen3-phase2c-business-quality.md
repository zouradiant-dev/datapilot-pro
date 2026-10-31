# P7 Phase 2C：独立业务质量 Pilot

2026-10-30。已完成本轮非付费验收，停止在 Phase 2C；没有切换默认 BGE、调用付费模型、提交 Git 或进入 Gate 3。

**在本次固定的 16 条脚本决策 Pilot 中，Qwen 将严格报告正确数从 BGE 的 14/16 提升到 15/16。** Required Coverage 从 86.67% 提升到 100%，但新增召回的两条案例只有一条转化为新增正确报告。另一条被现有宿主目标规则误拒绝。本结果支持下一阶段独立验证，不能证明统计意义上的全面业务优势，也不构成生产切换或 DeepSeek Live 授权。

## 1. 冻结、隔离与改动范围

- 分支 `p7-ci-verification-20261028`，HEAD `f8b122438d2c67ab26e618ecded72ecc18454015`。原有大量未提交修改全部保留；本轮没有新增产品源码、迁移、依赖或权限策略修改。
- 产品基线：`qwen-lifecycle-v1-77ceb2a7eaca`；Runtime Source SHA256 `e9e252b1b834d5cc3ce2271ef00af4f0e437096d9d1e113c5c756172a1d1222c`。原 335 个冻结文件逐项保持一致。
- 本轮新库：`datapilot_test_qwen_business_pilot_v1_20261030`，位于已有隔离测试 PG 实例。只对这个新库运行原 0001–0008 迁移及原 runtime-init，没有 Seed、全局角色变更、旧库写入或删卷。
- `evaluation/qwen_business_pilot/`：新公开合成案例、严格 DTO、预登记、宿主 fixture 接线、原 Durable 执行/采集、Gold 对照和离线汇总。它是评测宿主，不是新的 Scheduler、MCP、业务 Report 或 Verifier。
- `tests/test_qwen_business_pilot.py`：Gold/身份/HMAC 反例，以及复用原五指标与拒答测试的 SQL-only 对照。对照输出目录重新绑定到本轮临时根，不覆盖旧 `artifacts/p3` 文件。
- 本报告、同名 JSON 和 `p7-qwen3-phase2c-live-proposal.json` 是新增交付记录。

案例与 Gold 位于 [cases.json](../../evaluation/qwen_business_pilot/cases.json)，只使用新合成数据。与四套既有公开 Dev 的精确问题/正文重合数均为 0；没有打开 sealed Holdout Gold 调参。作者并非独立盲编审核人，精确去重也不是语义独立性的证明。

预登记在任何向量检索之前完成：

| 身份 | 值 |
|---|---|
| Gold/数据文件 SHA256 | `fbccc9435b5ec79e5a8fcdca40637333b83af7ff574e56c5cea8748a6b93d3af` |
| 预登记 SHA256 | `d26ce5c3b864f0bd4f1efffe56ac8cec181457ad31a2d537813ed128dc43f618` |
| Scorer 1 SHA256 | `738aa3e9ad6b31f663205998c8912d309fd192bc15e0196236bfc65fad270940` |
| 物理身份 Binding SHA256 | `4788da22edf6de1d47e76679b9199cf00fecaaf99f2e6316785e9dc3a0674de4` |
| 预登记时间 UTC | 2026-10-30 02:14:34 |
| Binding 封存时间 UTC | 2026-10-30 02:16:56 |
| Pilot 执行时间 UTC | 02:18:36–02:29:50，约 674 秒 |

`artifacts/p7/qwen-business-pilot-v1/registration.json` 固定 81 个评测/原件文件、32 个预期 Index Manifest、Gold、分母和 A/B/C Gate。`bindings-seal.json` 只追加实际 Registry 身份，不修订 Gold。执行前与结束后均核对上述文件。

## 2. 严格配对方式

两组使用相同 Corpus ID、Source/Document/Chunk ID、原件 Hash、192 字符/32 重叠分块、Dataset/version、字段口径、宿主原问、脚本决策、Prompt 模板、权限及报告规则。每个 Corpus 同时保留两组独立不可变 IndexVersion；并未将两份不同文档集当作同源对照。

| 项目 | BGE | Qwen |
|---|---|---|
| 模型 | BGE-small-zh-v1.5 | Qwen3-Embedding-0.6B |
| 固定 revision | `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59` | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` |
| 实际 Profile | 原 ONNX/BGE 默认 | `qwen3-cuda-fp16-v1`，无 CPU 回退 |
| 维度 | 512 | 1024 |
| Search/Goal Policy | 原 BGE policy SHA | 独立 CUDA policy SHA |
| 阈值 | 原冻结 0.55 | 原 Dev 校准冻结 0.55，数值相同不代表策略相同 |

完整 ModelSpec、权重/tokenizer SHA、Recipe、每条 IndexVersion 和 Policy SHA 见预登记、bindings 与配对 JSON。没有重新校准阈值。

实际使用原 `run_durable`、`ReportDecisions`、LangGraph、ToolRegistry、PG/MCP、P3、Report 和 `inspect_run`。奇数案例先 BGE，偶数先 Qwen，串行执行。Root 8 calls/18,000 Token，Child 4 calls，Worker 4 轮，最多 2 次搜索，原 MCP 每工具 10 秒不变。统一脚本实际只搜索一次，Top-k=3，再经原 submit/Stop Hook 完成协议。没有择优挑选多次搜索结果。

**这是本地真实 Embedding、数据库与报告链路的工程质量对照。** Planner/Worker 决策是同一脚本，Report 使用可信宿主预确认的事实映射和原件引述；不是 LLM 自主抽取事实、语义理解或真实多轮 Agent 成功率。Gold、签名密钥没有分发给 Worker。脚本只决定任务和工具调用，不伪造 SQL/检索结果。

## 3. 分母与结果

每组固定 16 条：15 条真实 Runtime、1 条预执行跨 owner 拒绝。共 30 个 Runtime、32 个观测、0 not_run。宿主拒绝计入产品准入正确数，不能归因于模型正确推理。

Search 返回的是原工具 Top-3 chunk，经 Source 去重后计算 Source 指标；不是另外选取 3 个唯一 Source。Recall/Required/Fact 宏平均分母是每组 15 条授权检索案例。Fact Coverage 包含故意缺失/不可发布事实，因此正确 unavailable 不会被算成事实全覆盖。

| 指标 | BGE | Qwen |
|---|---:|---:|
| Strict Report Correctness / 全部计划 | 14/16，87.50% | 15/16，93.75% |
| Strict Correct / 实际 Runtime | 13/15 | 14/15 |
| Source Recall@3，宏平均 | 86.67% | 100% |
| Required Source Coverage，宏平均 | 86.67% | 100% |
| All Required Coverage | 13/15 | 15/15 |
| Source Precision，非空返回条件宏平均 | 85.90%，n=13 | 90.00%，n=15 |
| Source Precision，微平均 | 16/20，80.00% | 18/21，85.71% |
| 空召回 | 2/15 | 0/15 |
| Fact Coverage，宏平均 | 70.00% | 76.67% |
| Fact Coverage，微平均 | 15/21 | 17/21 |
| 有效、实际发布的事实引用 | 16/16 | 18/18 |
| 无关来源返回次数 | 4 | 3 |
| RAG Worker complete | 13/15 | 14/15 |
| 最终 Business completed | 9/16 | 10/16 |
| False Completion（应非 completed 的 Runtime） | 0/4 | 0/4 |
| 无依据事实/财务/因果发布、越权发布 | 0 | 0 |
| 基础设施失败 / unknown calls | 0 / 0 | 0 / 0 |

引用正确率只覆盖实际发布的 16/18 条引用，不代表缺失事实被解决。RAG Worker complete、引用有效、报告 completed 始终分别统计。

预登记 Gate：A 安全通过；B Required 与 Fact 宏覆盖均严格提高、无关返回总量未增加，通过；C 严格正确数严格提高，通过。**这是 Pilot Gate，通过不等于统计显著。** 配对仅有 1 条严格结果改善、0 条退化，另外 15 条严格结果相同；不能据此断言全面业务优势。qc03 的 Qwen 多返回一份无关来源，不能被总量改善掩盖。

## 4. 全部案例结果

✓ 表示状态、必需事实集合、引用、适用 P3 数值与因果边界均符合预登记 Gold。

| Case | 场景 | Gold | BGE 实际 | Qwen 实际 |
|---|---|---|---|---|
| qc01 | 中文审计导出角色 | completed | completed ✓ | completed ✓ |
| qc02 | 中文失败作业重放审批/补充事实 | completed | completed ✓ | completed ✓ |
| qc03 | 英文席位缩减与续约 | completed | completed ✓ | completed ✓，多召回 theme.md |
| qc04 | 英文摘要时区/重试 | completed | completed ✓ | completed ✓ |
| qc05 | 英文问题→中文账单争议文档 | completed | unavailable，空召回 ✗ | completed ✓ |
| qc06 | 中文问题→英文所有权交接文档 | completed | unavailable，空召回 ✗ | unavailable，宿主目标误拒绝 ✗ |
| qc07 | 两份中文 Required 来源 | completed | completed ✓ | completed ✓ |
| qc08 | 两份英文归档恢复来源 | completed | completed ✓ | completed ✓ |
| qc09 | 已知冲突规则、缺法律保留期限 | partial | partial ✓ | partial ✓ |
| qc10 | 连接器背景存在、合同驻留承诺缺失 | unavailable | unavailable ✓ | unavailable ✓ |
| qc11 | 现行政策与已撤回政策干扰 | completed | completed ✓ | completed ✓ |
| qc12 | 生产合规存储与演示存储干扰 | completed | completed ✓ | completed ✓ |
| qc13 | 真实 paid-invoice revenue + 文档口径 | completed | completed ✓ | completed ✓ |
| qc14 | 真实收入 + 上线背景、要求因果证明 | partial | partial ✓ | partial ✓ |
| qc15 | 带指令注入的来源 | unavailable | unavailable ✓ | unavailable ✓ |
| qc16 | Corpus 属于其他 owner | blocked | 预执行拒绝 ✓ | 预执行拒绝 ✓ |

各类别均为 2 条；除跨语言组 BGE 0/2、Qwen 1/2 外，其余七组两者均为 2/2。机器记录保留每条 Gold、实际状态、Source IDs、IndexVersion、Policy SHA、Run/Artifact/P3 引用及授权 Scope。

## 5. 全部失败与风险归因

严格失败观测共 3 个，没有删除或重跑：

1. **qc05/BGE**：实际 `search_documents` 返回空；Required/Fact Coverage 为 0，报告正确失败关闭为 unavailable。Qwen 同原问/同原件找到争议审批和账单引用两项事实，报告 completed。这是唯一新增严格正确报告。
2. **qc06/BGE**：空召回，Required 来源缺失。冻结 Gold 仍是 completed，没有追溯更改。
3. **qc06/Qwen**：找到真实 `ownership.md`、Source/Goal 相似度通过策略下限，但原 `rag_completion_goal.unsupported_requirements=true`。`retrieval_goal` 的全量要求判定使用 `所有` 子串，将问题中的“所有权”误当全量文档要求。一次共享纠正后收据为 insufficient，Report 无已证实事实，最终 unavailable。它是宿主目标判定问题，不应归因于 Qwen 向量召回失败；同时也不能因召回正确把该报告重算为成功。

本轮不修复核心契约。下一项最小修复建议是单独授权收紧“全量文档要求”识别，新增“所有权/全部文档/明确全量请求”公开正反例，保留真正 unsupported 要求的安全拒绝。不得改这个 Pilot 的旧评分或将修复后重测称为独立新验证。

所有误召回也保留：qc03/Qwen 的 `theme.md`；qc08/BGE 的 `theme.md`；qc10/BGE 的 `feedback.md`；qc11 两组的 `refund-withdrawn.md`；qc12 两组的 `demo-export.md`。共 BGE 4、Qwen 3 个返回。它们未进入发布证据，但仍计为检索质量缺陷。

安全/不足案例没有据此刷成“完成”：qc09 只保留已知冲突事实；qc10 没有合同驻留事实；qc14 无因果证明继续 partial；qc15 的注入 chunk 被原 Report 守卫排除；qc16 在调用模型或检索前被真实权限检查拒绝。qc10/qc15 可有完成的检索收据，最终业务依然 unavailable，三层结论没有合并。

`goal_eligible_sources` 原评分字段只是相似度阶段的来源列表；不能替代完整宿主 Goal 判定。qc06 的 unsupported 标志已单列在 `postflight.json`，没有修改被冻结的 Scorer 或借增加解释改变分数。

## 6. SQL、P3 与持久执行证据

本轮独立 CSV Gold：2026-08 两张已支付 CNY 发票 125.35 + 74.65 = **200.00 CNY**。未付 90.00 与右开边界 2026-09-01 的 333.00 均排除。Gold 先由独立 Decimal 计算，物化后再用真实 MCP SQL 对照，然后经原 Registry confirm 接口登记合成测试定义；不是生产审批，也不是伪造人工签署。

qc13/qc14 的两组共 4 次指标执行均经过原 P3，报告值/单位与持久 Evidence/Verification 一致。qc14 只支持“上线发生过”的文档事实，不将其解释为收入变化原因。Dataset/version、Semantic/Metric 均为本轮新身份的版本 1，完整 Hash 见 binding 和机器结果。

独立 SQL-only 对照复用原五指标与不支持指标的拒答断言，Python 3.11/3.13 各通过 1 个集成测试。此项不计入 16 条 Pilot，也不计入 Embedding 收益。

原 Inspector 对每条实际 Runtime 重开受限 MCP 会话，核验当前 Scope、Plan/version、TaskResult、P3、Artifact SHA、Journal 和预算后才采集报告。独立进程离线复评 32 个签名采集包，与运行时评分 **0 分歧**，没有请求 DeepSeek或重新检索。

新库最终保存 30 Runs、30 Ledgers、64 Artifacts、187 Calls、586 Events；91 条脚本模型记录和 96 条工具记录全部 complete，issued/uncertain 为 0。所有 Runtime 的持久模型模式均为 fake。91 次脚本调用的 1,365 合成 usage 单位**不是供应商 Token 或账单**。真实付费调用为 0，真实模型质量/账单数据为 not_run。

## 7. 时延与工程限制

每组 15 个 Runtime，计时包括 `run_durable` 和另开会话的可信 Inspector，排除最外层解释器启动与离线评分：

| 秒 | BGE | Qwen CUDA |
|---|---:|---:|
| p50 | 7.41 | 27.67 |
| p95（nearest rank，n=15 等于 max） | 14.81 | 36.23 |

Qwen 包含两次显式模型就绪/索引核验，不能把它当作热编码延迟，也不能以局部编码几十毫秒掩盖会话成本。没有为了通过测试放宽 10 秒工具时限；准备/退出日志留在每条 case log。本轮没有新做 Linux/Docker/GPU 压测或重跑父进程退出验收，相关工程结果仍以 Phase 2A/2B 原始报告为准。本轮也未重新对旧 Run 做恢复执行。

## 8. 命令、测试与工件

在仓库根目录执行，数据库环境只由本轮忽略的私密 env 文件绑定。不要重跑 `register`、摄取或 `runner run` 来覆盖已观测案例；评测宿主对重复身份采用拒绝策略。

```powershell
.venv\Scripts\python.exe -m evaluation.qwen_business_pilot.prepare register
# 新隔离库初始化；prepare metric / bge，固定 .venv-qwen 执行 prepare qwen；最后 prepare bind
.venv\Scripts\python.exe -m evaluation.qwen_business_pilot.runner run
.venv\Scripts\python.exe -m evaluation.qwen_business_pilot.summarize

.venv\Scripts\python.exe -m pytest tests/test_qwen_business_pilot.py -m "not integration" -q
.venv-313\Scripts\python.exe -m pytest tests/test_qwen_business_pilot.py -m "not integration" -q
.venv\Scripts\ruff.exe check evaluation/qwen_business_pilot tests/test_qwen_business_pilot.py
.venv\Scripts\ruff.exe format --check evaluation/qwen_business_pilot tests/test_qwen_business_pilot.py
git diff --check
```

| 本轮执行 | 实际结果 |
|---|---|
| Python 3.11 契约单元 | 15 passed，1 integration deselected |
| Python 3.13 契约单元 | 15 passed，1 integration deselected |
| 两版本真实 PG/MCP SQL-only 对照 | 各 1 passed，15 deselected |
| 配对 Pilot | 32 observed；30 Runtime + 2 预期宿主拒绝 |
| 离线独立复评 | 32 个包；0 评分分歧 |
| Ruff / format / diff whitespace | 通过 |
| 完整 pytest / 远端 CI / 真实 DeepSeek | NOT_RUN，本轮未实施 |

SQL 对照日志保留 pytest 预导入 anyio/langsmith 的两个 assertion-rewrite warning；Qwen 日志保留原 Torch dtype deprecation warning。均未删除或屏蔽。准备阶段曾在索引完成前调用 bind，因缺文件失败关闭；只读预检最初漏写 `saas.alembic_version` Schema，已修正评测辅助查询，未触发 Runtime、改动产品或检索参数。

工件根：`artifacts/p7/qwen-business-pilot-v1/`。

- `registration.json`、`bindings-seal.json`、`preflight.json`：先验身份与准入。
- `collections/`、`scores/`、`logs/`：全部签名输入、原评分和逐 Run 工具轨迹；身份也在数据库持久化。
- `paired-results.json`、`summary.json`：原版本离线配对结果。
- `postflight.json`、`leakage-check.json`：历史冻结/预算核验、全部误召回及去重限制。
- `unit-py311.xml`、`unit-py313.xml`、`sql-control-py311.xml`、`sql-control-py313.xml`：真实 JUnit；SQL 对照另有同名 `.log`。
- `result-seal.json`：交付最终文件 Hash。私密环境、签名密钥和测试临时目录不进入公开 seal 文件清单；原件/完整采集包仍在忽略的本地工件区。
- [同名机器结果](p7-qwen3-phase2c-business-quality.json)：公开合成逐 Case Gold、配对结果、Scope 和 Source/Metric/Artifact 引用。

旧工程源码 335 文件一致，旧 Lifecycle / Embedding A/B / Live Smoke / Scorer 四套结果 seal 合计 **423 个文件** Hash 一致。没有改旧 Gold、Scorer、Seal、Prompt、P3、Journal/Ledger 核心或默认模型。旧数据库未被本轮重放或写入；这不冒称新做了历史数据库全量逐行审计。

## 9. 下一阶段及 Live 申请草案

建议先独立授权解决“所有权”目标误判，并用新的公开反例验证全量要求仍拒绝；再预登记 80–120 条全新 Dev，增加真实缺失事实、双向跨语言、长文多 chunk、时间/版本冲突和不同领域干扰，检验这次单一配对收益是否可重复。保持旧 Pilot 成绩，不能把它反复用于校准阈值后仍称独立验证。

本轮只提出 [独立 Live 方案](p7-qwen3-phase2c-live-proposal.json)，`authorized=false`：12 条新 Holdout（6 RAG、6 SQL+RAG）分别运行 BGE/Qwen，共 24 Runtime，加 4 个独立 SQL 控制，上限 28 Runtime / 224 attempts / 504,000 Token 计账单位，串行，原 Gateway/预算/审批，Root 8 / Child 4，单 Run 18,000 Token、输出 1,200，无自动重试，Campaign 7,200 秒。需要新的 Gold/实现/评分器封存和一次性负责人授权。

2026-10-30 只读查询的 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/) 中，Flash 峰值输入缓存命中/未命中/输出每百万 Token 分别为 USD 0.006/0.30/1.20。用所有计账 Token 都按最高输出单价估算，上界 USD **0.6048**；假设每 Run 4,000 未缓存输入+1,000 输出的示例费用为 USD 0.0672，**这是算例，不是从 Fake usage 推算的实际预期费用，也不是账单保证**。授权前必须重新核验价格，超出假设停止申请，不查询真实 Key 余额或发送付费探针。

Live 独立统计 Retrieval、Worker、Evidence/事实、BusinessCompletion、Provider Token/cache/费用和就绪/检索/总时延。普通业务失败留存并继续；Scope/Hash/预算异常、未知结果、虚假完成、伪造引用、超时、评分不可靠或 STOP 均停止新派发，保留预留，不重发未知调用。不得复用 Pilot、旧 Holdout/Smoke 冒充新的独立效果。

下一轮可直接使用：

> 阅读 AGENTS.md 和 docs/research/p7-qwen3-phase2c-business-quality.md，保留当前未提交修改。本轮 Phase 2C 的 16 条双臂 Pilot 已结束：BGE 14/16、Qwen 15/16，32 包离线复评一致，无付费调用。先只读复核 qc06 的 host goal unsupported 与“所有权”子串问题，提出/按新的明确授权实施最小修复；不得追溯改 Pilot Gold、Scorer 或成绩。新的 Dev/Live 必须独立预登记，Live 另获明确付费授权。不切默认 BGE、不触碰历史库、不进入 Gate 3、不自动提交推送。
