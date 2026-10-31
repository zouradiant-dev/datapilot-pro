# P7 Gate 2：冻结意图 Holdout 与真实收据核验

2026-10-24：完成本次明确授权的 **59 条合成意图场景**三策略对照。Rule-only 46/59、LLM-only 58/59、Hybrid 57/59。两增强路径合计 67 次真实 DeepSeek 调用，无付费重跑。**这只完成 Gate 2 的意图部分；业务执行、P3 数值/Evidence、真实 RAG/跨来源报告的独立 Holdout 均未运行，Gate 2 整体与 P7 尚未验收。**

## 冻结、授权与被测对象

基线 HEAD 为 `49969b7e32c7f88846f37e61f3ed78ba2ef7b978`。其 [GitHub CI](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/40083421825) 两版本各 689 passed、15 skipped，仅证明该基线的 Fake/Mock + 真 PG/MCP 回归，不能当本次新增评测脚本的 CI。

用户先授权“进入gate2”，再明确批准“允许这一次有界 Holdout Live”。原 Gate 1 的 13 文件、dev/Holdout hash 先逐字复核一致；在首次解码 Holdout 前，新增宿主评测入口、测试及引用依赖共 18 文件已固定 hash，见 [Gate 2 清单](research/p7-gate2-plan.json)。模型、Prompt、规则、Gold、阈值和默认网站实现未修改。旧 [Gate 1 freeze](research/p7-gate1-freeze.json) 的 `holdout_authorized=false` 是历史事实，原 DEV runner 继续拒绝 Holdout，未篡改旧快照。

原 Settings 每 Run 至多 20 次调用，BudgetLimits 的上限相同。本轮每策略固定为文件原顺序的 **12/12/12/12/11** 五批，按全部 LLM-only、再全部 Hybrid 执行，每批独立复用原 Gateway/PG Journal/Ledger/lease，每批至多 75,000 Token、每条最多一次意图候选调用。总上限 118 次/750,000 Token，输出上限 768，Thinking disabled、temperature=0、SDK retries=0。没有提高运行期上限、第二套账本、业务图或调度器。

原问题、合成目录及 selection 发给模型；Gold、业务行、文档正文、数据库句柄均不发送。模型只能提候选，scope/版本仍由冻结宿主逻辑绑定；候选没有批准或执行权限。**网站继续使用原 Rule-only**，本轮未开发产品语义入口。

`scripts/evaluate_gate2.py` 增加单独授权和固定批次的可信评测入口，失败停止后续批次，已记录/已注册批次拒绝重建。部分执行分开记录 planned/observed/not_run，不能缩小分母或把未执行任务填入延迟。已完成批次的 JSON、原 PG 收据与首次快照均保留。初次 Rule-only 运行早于付费批准，仅批准元数据后来更新；`artifacts/p7/gate2/plan-before-first-holdout-read.json` 保留读取前定义，候选/数据/批次定义完全相同。

## 三策略正式观测

原 [预注册协议](evaluation-protocol.md) 的分母与 Wilson/nearest-rank 算法不改；[结构化结果](research/p7-gate2-validation.json) 保留全部批次、响应哈希、原始 usage 与失败 ID。

| 指标 | Rule-only | LLM-only + 宿主守卫 | Hybrid + 宿主守卫 |
|---|---:|---:|---:|
| 全部槽位精确匹配 / 59 场景 | 46/59，77.97% | 58/59，98.31% | 57/59，96.61% |
| 可回答场景精确匹配 / 31 | 22/31 | 30/31 | 29/31 |
| 错误目标接受 / 实际候选 | 4/26 | 0/30 | 0/29 |
| 必要澄清 / Gold 要求澄清 | 24/28 | 28/28 | 28/28 |
| 错误拒绝 / 可回答场景 | 9/31 | 1/31 | 2/31 |
| 意图执行异常 | 0/59 | 0/59 | 0/59 |
| 实际模型调用 | 0 | 45 | 22 |
| 意图阶段 p50 / p95，ms | 0.026 / 0.171 | 956.107 / 1348.904 | 10.949 / 1229.358 |
| 单次模型 attempt p50 / p95，ms | 无调用 | 1000 / 1313，45 样本 | 1000 / 1203，22 样本 |

槽位 Dataset/version、Metric/Semantic/version、时间窗口/as_of 的严格覆盖分别为 Rule-only 22/31、LLM-only 30/31、Hybrid 29/31。这是合成目录绑定一致性，**实际数据库授权准确率 not_run**。两增强路径的样本点估计达到意图协议的可回答正确 ≥90%、必要澄清 ≥95%；不据此宣称业务目标达标或总体错误率为零。

全部任务精确匹配的 Wilson 95% 区间分别为 [0.6587,0.8665]、[0.9100,0.9970]、[0.8846,0.9907]。这些是构造集合的描述性区间，不能消除模板重用和选择偏差。三策略总共仍是同一批 59 个场景，不是 177 个独立经营分析任务。

意图阶段用 perf_counter，包含宿主验证、Journal/预算和收据检查；Rule-only 不访问 PG。模型 attempt 用原 Gateway 的 monotonic 耗时。模型快速路径/强制守卫不调用模型，仍进入所属策略分母；LLM-only 不是裸模型。批次初始化/模型构造不含在每条意图延迟中。并发固定 1，环境见 JSON；API 受理/最终业务完成延迟均 not_run，不能当生产 SLA。

## 真实 Token、缓存与费用

| provider 收据 | LLM-only | Hybrid | 合计 |
|---|---:|---:|---:|
| input Token | 35,844 | 17,407 | 53,251 |
| output Token | 4,425 | 1,964 | 6,389 |
| total Token | 40,269 | 19,371 | 59,640 |
| cache hit Token | 18,560 | 13,824 | 32,384 |
| cache miss Token，供应商原始字段 | 17,284 | 3,583 | 20,867 |
| USD 费用估算 | 0.005303280 | 0.001757322 | 0.007060602 |
| 真实账单 | unknown | unknown | unknown |

cache miss 同时记录供应商原始字段与 input-hit 推导值，二者一致；未知 usage/cache 不补零。按 [当天核实的官方费率](https://api-docs.deepseek.com/quick_start/pricing/) 与周六非高峰计价，cache-hit/input-miss/output 每百万 Token 为 USD 0.003/0.15/0.6，Decimal 计算；[价格快照](research/p7-gate2-pricing.json) 与真实账单分开。未调用 Search/Fetch/Embedding，不把估算当扣费凭证。

响应模型名均为 deepseek-flash，fingerprint 一致，见 JSON。官网当时标注 DeepSeek-V4.1-Flash-1017，但响应别名/指纹不能独立证明精确权重。没有随机化供应商缓存：全部 LLM-only 先运行，Hybrid 后运行；缓存差异受顺序影响，不能将费用差全部归因于策略或 Prefix Cache。本轮也没有 Context L0–L4/恢复消融，不外推旧压缩率。

## 原始收据与未知结果边界

`scripts/summarize_p7_gate2.py` 只读取既有记录，不构造模型。逐一复核 10 个 Run 的 owner、确定性 Run ID、Manifest/plan/selected hash、持久账本 SHA、调用次数、结算 ticket、响应 payload SHA 与 provider usage。67 个模型收据全部 complete，pending=0、unknown=0，账本和已观察 Token 一致；本轮没有恢复或外部自动重试，不把它当供应商 exactly-once 证明。

新增真 PG + Mock 反例验证：正常 12 条产生 12 个原 Journal 收据，重复批次拒绝且不增调用；首个 Mock 网络失败保留 uncertain 与保守预算，11 条未执行，下一批拒绝启动。两版本各 2 passed，Mock 数据不进入上述真实质量分母。原 P3/P4/P5B/P6A/P6B 与数据库权限/迁移均未修改。

## Bad Cases：先报告，不调优

以下描述类别及结果，不公开封存问题/Gold 全文；精确输入、完整观测位于私密 JSONL。冻结候选没有根据这些失败改动。

| ID | 观察与原因 | 含义 |
|---|---|---|
| holdout-036 | 原规则不能覆盖并列窗口；Hybrid 本次模型明确选 clarify，LLM-only 本次正确 | 原问同样可答，仍保留 Hybrid 错误拒绝；单次生成有差异 |
| holdout-037 | 原规则拒绝并列收入/使用量；两增强路径正确提议双指标 | 只验证目标覆盖，没有计算两种指标 |
| holdout-038 | Rule-only 对绕过审批指令形成普通指标候选；增强路径强制澄清 | 是意图错误接受，未发生实际审批绕过 |
| holdout-039 | Rule-only 对其他租户范围形成候选；增强宿主守卫拒绝 | 未执行数据库查询，不能当真实权限攻击测试 |
| holdout-041 | Rule-only 缺失汇率转换目标却形成收入候选；增强路径澄清 | 不能偷偷替换不支持的口径 |
| holdout-044 | Rule-only 未识别业务同义词；Hybrid 模型本次选 clarify，LLM-only 正确 | 错误拒绝保留，未增加提示或重跑 |
| holdout-045 | 原规则未识别使用量别名；增强路径正确 | 同义表达样本有限，不能推广任意术语 |
| holdout-046 | 原规则不能处理季度；增强路径提出原句，宿主确定性生成日期 | LLM 未心算日期范围 |
| holdout-056 | Rule-only 被选择器替换了明确目标；增强守卫澄清冲突 | UI 选择器也不能覆盖用户完整目标 |
| holdout-059 | LLM-only 本次明确选 clarify；Hybrid 规则快速路径正确 | 原问题有明确右开区间，模型仍可能过度澄清 |

三个新增 Live 失败的原响应均为合法 clarify 提案，宿主原因 INTENT_CLARIFICATION_REQUIRED，不是 HTTP/预算或畸形 JSON。完整 13 个基线失败和 3 个增强路径失败记录均保留，未择优删除。posthoc 分类来自原响应与冻结验证函数，没有再次调用模型；它不重写实际观测。

## 集合独立性与未完成项

必须披露一个实质限制：12/59 问题文本与 dev 完全相同；对问题执行 `re.sub(r"\d+", "#", question)` 后，59/59 都能在 dev 找到同句式。复合身份（问题、selection、目录上下文）去重与封存 SHA 不等于全新语言模板或独立人员盲编。它是一份**封存的数值/日期/上下文变体集**，结果只能支持这一有限范围的冻结对照，不能视为真实 SaaS 泛化验收。该事后分析写入 JSON，未用于重选题或调分。

下一步 Gate 2 业务部分需要在执行前另行封存：至少 50 个独立业务目标、真实源快照/版本、独立 SQL/Decimal Gold 与拒答条件，补齐授权/审批以及 SQL、RAG、跨来源报告路径。现有 50 条已看过的 Fake 决策业务 dev 不能复用作正式 Holdout；已观测意图 Holdout 也不能为后续 P11 调优重用。此次授权明确不执行业务任务，所以本阶段相关模型、P3 数值/Evidence、真实 RAG 质量与业务完成率全部 not_run。

Gate 2 业务任务/模型预算尚未批准，当前不伪称整体 Gate 2 通过，也不自动进入 Gate 3。一次有界意图授权已结束，118 次上限中的未用部分不挪用。

## 验证、文件与复现

新增文件为 `scripts/evaluate_gate2.py`、`scripts/summarize_p7_gate2.py`、`tests/test_p7_gate2.py`、`tests/test_p7_gate2_summary.py`、本文件和 research 下五份 Gate 2 JSON；更新 AGENTS、README、评测索引与路线图。新入口负责固定的授权/批次/观察记录，新汇总只审计原收据；没有新模型接口或业务模块。用户 v2.4/v2.5 规划不改、不提交。

初次新增单元测试有 3 个失败，均因 Windows 临时 fixture 的 CRLF 字节与固定 LF hash 不一致；在读取 Holdout 前改为显式字节 fixture，原候选未动。初次真 PG 测试有 2 个 setup error，是 pytest 默认 Temp/cache 目录权限；改用仓库内全新隔离目录后通过。原日志分别为 `harness-initial-py311.xml`、`journal-pg-py311.xml`，没有删除失败历史。

报告脚本后来补充 `--output` 时，循环变量覆盖目标路径；只读复核实际被 FileExistsError 拒绝，原 JSONL 未覆盖。新增正式反例先 1 failed，再将局部 JSONL 路径与目标路径分开，报告契约 7 passed；没有改被测候选、Gold 或分数，更没有追加 Live。失败日志为 `readonly-audit-repeat.log`、`reporter-output-counterexample.xml`，修复后的只读复核为 `readonly-audit-final.json`，67 条原收据及所有分数/账本 hash 一致。

最终回归与文档/冻结核验见 [本轮验证记录](research/p7-gate2-checks.json)。Gate 1 基线 CI 与本次本地验证分别计数；本轮没有新 GitHub CI、没有自动 commit/push、没有新增付费复测。

以上“未提交/未运行新 CI”为评测结束时的**推送前快照**。用户随后单独要求上传 Git；后续提交及其 CI 以该提交对应的 GitHub Actions 为准，不覆盖这里的原始测试、Live 指标或失败历史。

### Post-push CI Verification / 意图收尾

2026-10-24 22:41:28 +08:00 通过 GitHub REST 重新查询 push Run 和 jobs：提交 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`、Run `40096866653`、工作流 **DataPilot checks**，completed / success，attempt 1。Python 3.11、3.13 均 Success；对应原始 CI 日志各为 **709 passed、17 skipped**，Ruff 通过。见 [Actions](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/40096866653) 和 [结构化 post_push_ci](research/p7-gate2-validation.json)。这些是已提交版本的 PG/MCP + Fake/Mock 回归，不是新增 DeepSeek 实验，也不包含本轮尚未提交的准备工具。

意图结果、Token、费用估算、三条增强路径错误拒绝、模板重用限制和推送前历史全部保留。此次收尾没有追加模型调用，网站仍为 Rule-only。下一步只完成 [独立业务 Holdout 准备](p7-business-holdout.md)：60 个新目标已封存，物化、人工审阅及业务 Live 仍未完成，Gate 2 整体仍未验收。

在仍有原私密 PG 收据和封存文件的可信环境，可以只读重新汇总：

```powershell
uv run --locked python scripts/summarize_p7_gate2.py --output artifacts/p7/gate2/new-readonly-audit.json
```

此命令检查原件 hash/预算，不调用模型；输出必须是新文件。三策略逐任务 JSONL 在 `artifacts/p7/gate2/{strategy}-observations.jsonl`，公开 JSON 不含完整 Gold、Prompt 或响应正文。原独立 DEV runner 和本轮已消费的 Live 批次均不得再作为无条件重跑入口。

原始字节复现另有两个限制。5 个既有文件受 Windows CRLF/Git LF 转换影响，工作区冻结 SHA 与 HEAD blob 原字节不同，但 LF 规范化后均与 HEAD 完全一致。未改换行或冻结 hash 来放宽检查；[字节清单](research/p7-gate2-source-bytes.json) 记录 18 文件的原始/规范化 SHA 和换行计数，`artifacts/p7/gate2/frozen-sources.zip` 保留精确被测字节。在独立复现目录还原原字节，不能直接绕过 freeze 检查。

PG Run 有原 P5B TTL，过期后上述在线复核会安全拒绝，不能承诺永久可在线恢复。本轮在有效授权期内只读归档自身 10 Run/67 收据、Manifest 与账本至忽略的 `artifacts/p7/gate2/private-original-receipts.json`，SHA 记在验证记录；只用于历史离线核对，不恢复授权、不重发调用、不绕过 TTL。完整源问题和原响应继续仅留私密目录，不提交 Git。
