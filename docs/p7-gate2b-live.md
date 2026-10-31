# P7 Gate 2B Business Holdout Live：中止交付记录

2026-10-25 15:41 +08:00 完成账本及原件核验。本次确实调用 DeepSeek，使用真实隔离 PostgreSQL 17 / pgvector、MCP、P3 和 RAG；**执行在 bh2-031 的预算预留失败后安全停止，未完成全部 60 条，Gate 2B 正式 Live 不予验收**。没有继续调参、重跑、进入 Gate 3 或提交/推送。

## 授权、冻结与执行边界

本轮直接用户授权涵盖 60 条案例，SQL-only / RAG-only / SQL+RAG 各 20 条；最多 54 个 Runtime、每 Run 8 次调用 / 18,000 Token / 单次最多 1,200 输出 Token，全局 432 次 / 972,000 Token。沿用原 `p7_run_approved_campaign.py`，串行、SDK 自动重试 0，`deepseek-flash`、Thinking disabled、温度 0；61 个实际响应的模型名均为 `deepseek-flash`。旧意图 Live 授权没有挪用。

| 冻结对象 | SHA256 |
|---|---|
| NUMERIC 修复后 Implementation Freeze（152 文件） | `0094ab595c62b2fadef192728399300855754a97455b19a35d4bb24ffc0ed18f` |
| v1 Seal | `7af09ffe2320dfdad3535c55ed89e96124a7fd4bad0d66bc1cc898dbec464ecc` |
| v2 Seal | `958ee94411d6a6b409483c5f494e09ec6792b0d2483762a201ad160d5b540e1a` |
| v1/v2 字节相同的 Gold | `baacca4a8e3ab2f257b24ee0f67810f64533e8fae3966f5300e278463e78362d` |

运行前和停止后均核对源码、输入、授权与 Seal；本轮没有修改冻结候选、Prompt、配方、P3 Verifier、Gold、Scorer 或阈值。使用原隔离实例 `datapilot_p7b` / 55440，没有重建数据库、Seed、修改 grants 或删除卷。A/B 32 项原确认及 Hash 保持，C 两项和故意不存在的版本未补建。既有 rejected Evidence/Verification 保留。

原许可校验器的 `max_runs=60` 表示计划案例数量；本轮许可另明确 `max_runtime_runs=54`，六个预检拒绝没有 Runtime/模型调用。实际创建 28 个 Runtime 和 3 条宿主预检拒绝记录。许可及完整配置属于本地私有资产；公开的 [授权摘要](research/p7-gate2b-live-authorization.json) 不包含密钥。

## 停止原因与预算一致性

Run `8af538a1-9aa4-5212-a56b-f78207b6d1cc`（bh2-031）的 RAG `documents` 任务返回 `BUDGET_EXCEEDED`、`retryable=false`，Run 为 failed，报告业务状态为 blocked。原 Runner 的停止条件随即终止后续派发；第五次请求未发送。

- 已结算 4 次模型调用，供应商报告 6,482 Token；不存在 pending reservation 或 unknown-outcome。
- 下一次输入估算为 11,897 Token，输出预留 1,200，共需预留 13,097；原根账本要求 `6,482 + 13,097 = 19,579 > 18,000`，因此拒绝。子账本同样不能容纳该预留。
- 原估算器为保守的 `utf8_bytes_plus_128`。这是本地调用前预留触顶；实际已用 Token 未超过 18,000，也没有发生全局额度耗尽、未知扣费或额外摘要调用。
- 没有提高预算、释放已用费用、自动恢复、重跑失败任务或执行 bh2-032–060。原失败及 issued 标记全部保留。

账本审计覆盖 28 个 Manifest、父子预算结构/Hash、全部已提交调用 payload Hash 与结算收据，以及持久 Artifact 内容 Hash。61 次模型调用均 complete，账本保守累计与供应商已知 Token 均为 77,897，授权上限内；没有待确认调用。停止细节见本地 [stop-diagnostic.json](../artifacts/p7/gate2b-live/stop-diagnostic.json) 和 [ledger-audit.json](../artifacts/p7/gate2b-live/ledger-audit.json)。

## 原冻结评分：分母仍为 60

评分只在候选执行结束后，使用原签名 Collector 输出和原 Gold 离线进行。**31 条已观测中 25 条严格通过、6 条不通过；29 条 not_run 仍保留在 60 条计划分母中。** 31 条包含 3 条预期宿主拒绝（018/019/020），不应将其当成模型完成的业务任务。

| 类型 | 计划 | 已观测 | 严格通过 | 未通过 | not_run | 已观测严格正确率 | 正确数 / 完整计划 |
|---|---:|---:|---:|---:|---:|---|---|
| SQL-only | 20 | 20 | 18 | 2 | 0 | 18/20 = 90.0% | 18/20 = 90.0% |
| RAG-only | 20 | 11 | 7 | 4 | 9 | 7/11 = 63.6% | 7/20 = 35.0% |
| SQL+RAG | 20 | 0 | 0 | 0 | 20 | not_run / null | not_run / null |
| 全计划 | 60 | 31 | 25 | 6 | 29 | 25/31 = 80.6% | 25/60 = 41.7% 覆盖下界 |

这是按固定顺序中止的前缀样本，25/60 仅是正确完成的计划覆盖下界，不能称为完整 Holdout 的无偏成功率。原评分器的 Wilson 95% 区间为 SQL 69.9%–97.2%、RAG 35.4%–84.8%，仍受提前停止、集合构建方式和评分问题限制；SQL+RAG 无观测，区间为 null。

六条预期宿主拒绝在运行前预检均验证；正式派发只到其中三条，其余 034/048/058 及 bh2-060 故意缺定义任务未执行，不能把预检记成这四条的正式 Live 成绩。bh2-032–060 的完整 not_run 清单见 [结构化结果](research/p7-gate2b-live-results.json)。

### 证据、检索和完成分开计量

- 原评分下错误完成为 0/19 个发布 completed 的报告（SQL 0/12、RAG 0/7），仅限本次已观测结果。
- SQL 可回答案例错误拒绝 0/12；RAG 为 1/10（bh2-026）。031 是执行预算失败，单独记录，不计为模型拒答。其余 unavailable 的严格原因码不匹配也没有删除。
- 12 个已发布数值 claim 全部与独立 Gold 一致，12/12；17 组原 P3 Evidence/Verification 经原 scoped MCP 再读，Hash、版本和 verdict 不变。不把未发布或未运行目标算成正确数值。
- 10 个按报告去重的已发布文档引用全部对应 Gold 相关 Document，10/10；原 Collector 复核 source/version/chunk/span/hash。引用准确不等于任务事实齐全，更不能证明因果。
- 已观测必需文档事实覆盖 15/19。原检索度量采用 16 次 query、固定 k=3；Chunk、Document、Source 各自的宏平均 Recall@3=0.65625、Precision@3=0.291667、MRR@3=0.6875。未进行阈值比较或召回调优。

### 冻结 Scorer 的结果键不匹配

原 `RunState.results` 使用 `1:documents` 等带版本的键，原评分器部分逻辑以未带版本的 `goal_id` 查找，导致其 RAG Worker 完成汇总为 0；对照原 TaskResult.task_id / 完成收据实际为 **8/11 检索任务完成**。该差异也影响 bh2-030 的拒答完成条件判断。

本轮没有修改 Scorer、没有用诊断值覆盖原汇总或把严格正确数提高。**25 个严格通过保持原值，Worker 汇总 0 必须连同上述缺陷解释。** 8/11 只是原收据诊断，不等于最终业务正确率。原始收据对照在本地 [raw-contract-diagnostic.json](../artifacts/p7/gate2b-live/raw-contract-diagnostic.json)。如后续批准修订评分器，应先在 dev/新反例验证、重新评审和冻结版本；不能追溯性把本次结果包装为完整验收。

## 保留的六个 Bad Cases

| Case | 观测与严格失败原因 | 本轮处理 |
|---|---|---|
| bh2-011 | Gold 和报告均 unavailable；P3 原因是零起始 cohort。报告给通用 `data_not_verifiable`，严格契约要求 `zero_denominator` | 未发布错误数值；保留原因码不匹配失败 |
| bh2-017 | Gold 和报告均 unavailable；P3 拒绝重复记录粒度。报告给 `data_not_verifiable`，严格契约要求 `duplicate_record_grain` | 不为评分新增别名或改原 Verifier |
| bh2-024 | 必需事实 3/3，报告 partial，保留 `causal_conclusion_not_verified`；Gold 要求 completed | 作为完成语义不一致保留，不临场判哪方应改 |
| bh2-026 | 应可回答，实际 `NO_RELEVANT_DOCUMENTS` / empty 收据 / unavailable，事实 0/2 | 错误拒绝，保留工具轨迹，不重检索刷分 |
| bh2-030 | 应 unavailable，实际也 unavailable、empty；因版本化结果键的评分查找问题，原严格评分不通过 | 保留原失败及收据诊断，不现场重评分 |
| bh2-031 | 应 completed，实际 RAG 预算预留失败、报告 blocked，事实 0/2 | 安全停止全批次，剩余 29 条 not_run |

## Token、成本与时延

| 项目 | 实际记录 |
|---|---:|
| 模型调用 / 已知总 Token | 61 / 77,897 |
| Provider input / output | 71,242 / 6,655 |
| Provider cache-hit / cache-miss input | 36,992 / 34,250 |
| unresolved / unknown usage | 0 / 0 |
| 模型一次 attempt p50 / p95 | 1,201.48 / 1,556.83 ms（n=61） |
| 宿主 start→签名采集 p50 / p95 | 33,436.06 / 41,955.25 ms（n=28） |
| 估算总费用 / 真实账单 | USD 0.009241476 / 未取得 |

费用按执行当日核验的 [DeepSeek 官方费率](https://api-docs.deepseek.com/quick_start/pricing/)：周日 off-peak，USD/百万 Token 分别为 input hit 0.003、miss 0.15、output 0.6，结合每次响应 usage 计算。**它是价格估算，未核验账户实际扣款**；缓存不可控，没有把命中量解释为本产品压缩收益。

宿主时延包括容器启动、可信宿主 review、原 Runtime/P3/RAG/Collector；不含人工逐条等待，不是 API 请求受理时延或生产 SLA。运行环境是 Windows 26100、Python 3.11.16、宿主 32 逻辑 CPU、`datapilot-pro-demo:local`、串行一个候选。28 次原审批起点均为零模型调用；一次用户明确授权由原宿主执行精确许可范围，没有虚构 28 次逐条人工签名。

这次是正式隔离 CLI Runner，不是网站 Chat-first 意图/UI 基准。模型参与真实 Planner / RAG 决策，数值和报告依然由原受审查 P3 配方、Verifier 和确定性 Report 生成；不是让 LLM 心算，也没有拿 Fake/录制回放冒充 Live。

## 可复查资产与实际命令

完整问题、原件、Gold、密钥、模型输入/响应、私密报告和正文只保留在忽略的本地 artifacts；公开 Trace/交付 JSON 不带正文、向量、DSN 或 Key。以下本地链接用于本机复核，不代表它们已上传 GitHub。

- [公开结果和全部 not_run IDs](research/p7-gate2b-live-results.json)、[执行授权摘要](research/p7-gate2b-live-authorization.json)。
- [原冻结评分输出](../artifacts/p7/gate2b-v2/private/campaign-results/business-v2-958ee94411d6a6b4/summary.json)、[已观测逐案例 JSONL](../artifacts/p7/gate2b-live/case-results.jsonl)。
- [60 条完整案例状态账本](../artifacts/p7/gate2b-live/campaign-case-ledger.jsonl)，未执行的案例明确记录 not_run，没有虚构 Run 或零费用响应。
- [完整持久调用/账本/Checkpoint/Artifact 元数据](../artifacts/p7/gate2b-live/private-ledger-export.json)、[原 P3 再读](../artifacts/p7/gate2b-live/private-p3-readback.json)、[实际报告目录](../artifacts/p7/gate2b-live/reports/)。
- [Runner stdout/stderr](../artifacts/p7/gate2b-live/driver.log)、[最终账本审计](../artifacts/p7/gate2b-live/ledger-audit.json)。

已执行一次 `python scripts/p7_run_approved_campaign.py --permit artifacts/p7/gate2b-live/permit.json`，以退出码 1 停止；随后只做原 `p7_business_evaluator.py score --collections artifacts/p7/gate2b-v2/private/campaign-results/business-v2-958ee94411d6a6b4`、只读账本导出、原 MCP 证据再读和离线诊断。**不要再次执行派发命令。** 没有修改业务源码，因此没有重复运行先前双版本完整 pytest，旧回归不冒充本次 Live 的 CI；本轮 JSON/引用/Freeze/账本/静态检查单独留存。

收尾静态检查实际执行 `ruff check .` 通过，`ruff format --check --extend-exclude docs/codex-prompts-v2.5.md .` 为 296 files already formatted，`git diff --check` 通过。格式检查排除了用户 v2.5 规划文档已有的代码块格式问题，未修改 v2.4/v2.5；不是声称全仓无排除格式检查通过。[最终离线核验](../artifacts/p7/gate2b-live/final-validation.json) 记录签名、152 个冻结文件、两份 Seal、JSON、Markdown 本地引用、密钥/canary 检查和原评分 Hash；[交付 Hash 清单](../artifacts/p7/gate2b-live/delivery-sha256.json) 可复核本轮结果文件。未运行新的完整 pytest 或 GitHub CI。

## 停止边界

剩余 29 条尚未运行，SQL+RAG 本轮没有正式观察，评分汇总还有已披露的契约问题；因此不能发布完整 Gate 2B 成功率、正式通过结论或稳定性保证。下一步需要项目负责人独立决定如何处理预算和评分缺陷，再固定后续实验协议；本轮不改实现、不沿用剩余额度自动重跑、不进入 Gate 3，不自动提交/推送。
