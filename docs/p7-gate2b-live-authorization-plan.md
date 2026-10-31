# P7 Gate 2B v3：下一轮 Live 授权方案

**这是准备方案，不是付费授权。** 当前 60 条全部 `not_run`。负责人本轮只批准非付费设计/物化/验证；旧 Holdout、Smoke 的授权和未用额度均不能挪用。

## 1. 推荐范围与固定身份

一轮 `p7-business-independent-v3-first-live`，按已封存交错顺序执行全部 60 条：各 Lane 20 条；其中 6 条宿主预执行拒绝、最多 54 个业务 Runtime。不重启或续跑原 60 条历史 Holdout，不复用 8 条 Dev Smoke 充当新样本。

绑定 [Holdout 交付文档](p7-gate2b-independent-holdout.md) 中的 `p7-business-independent-v3-abc47cf7a250`、Data/Gold、Protocol、Evaluator、Budget SHA，以及 60 份 base config hash。产品继续使用已通过 Smoke 的原 Source `c2dd57f1294a…`，新启动/评测适配器有单独 Hash；发生任何代码或数据变化均需新版本与受影响回归，不能静默换包。

## 2. Provider 与可执行预算

| 项目 | 固定值 |
|---|---|
| Provider / Model | DeepSeek / `deepseek-flash` |
| Endpoint | `https://api.deepseek.com`，Chat Completions，经原 Gateway/Native Transport |
| Thinking / temperature | disabled / 0 |
| Root | 8 model calls / 18,000 Token |
| Child | 4 calls / 18,000 Token |
| max_tokens | 1,200 / attempt |
| Provider timeout | 30 秒 |
| Runtime / attempts | 最多 54 / 432 |
| Campaign Token | 最多 972,000 计账单位 |
| 并发 | 1 个 Runtime；沿用原 Worker 能力调度 |
| 重试 | SDK 0、外层 0；只保留原有有界 Loop/Stop Hook，不能叠加重试 |
| 时限 | 每 Run 180 秒、Campaign 10,800 秒 |

保留原 BudgetLimits 的上限，不把单个 Ledger 扩成任意大数。固定 11 个独立分区，复用原 PG lease 和 DurableLedger：前 10 个各 5 派发槽/90,000 Token，最后一个 4 槽/72,000 Token。总派发槽 54，总计账上界 972,000；每个槽对应原 Root 上限 8 次模型 attempt，因此总上限 432。全 Campaign 的原 PG lease 是唯一派发所有者；固定身份/私密结果目录与各原账本拒绝重放、重建或清零。

每个 Run 派发前完整预留 18,000，已知用量按真实值结算，未知保留全部预留并停止；重复结算拒绝。模型真实 usage、保守预算扣减与派发槽分别报告，不能将 `Ledger.calls` 的槽单位当作供应商调用数。

预算是按 Root 最坏上限推导，不是假定历史均值。可用于人工容量规划的较宽假设是约 2–6 次 attempt、3k–9k Token/Run（未验证预测，复杂任务或摘要可能更高），不构成真实费用上界；严格准入始终使用 8 / 18k 与完整 Campaign 上限。

冻结峰值费率每百万 Token：cache hit 0.006、miss 0.3、output 1.2 USD。按全 972,000 都取最高单价，**估算上界 USD 1.1664**；实际账单可能因费率、别名和供应商计费变化不同。原价格来源为 [DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing/)，真正执行前需重新核对免费官方信息，不使用 API Key 查询余额、付费探针或擅自换模型。缓存、Token、估算费用和真实账单分开；真实账单没有对账时为 null。

## 3. 一次性 Permit

模板：`artifacts/p7/independent-holdout-v3/authorization-template.json`。当前 `authorized=false`、审批人与来源/期限为空，不得补成真实授权。

未来负责人明确授权后，可信宿主另建一次性私密 Permit，绑定：Campaign、Implementation/Data/Gold/Protocol/Evaluator/Budget 身份、全部 config hash、上述模型与额度、实际授权来源和时间、精确 Run 审批范围及 expiry。记录实际批准范围，不虚构逐项独立人工审查。

模板与真实 Permit 分离；不得改旧模板或源 Seal 使检查通过。预检需要角色/版本/Hash/预算/Journal/Artifact 全部一致，新的 Campaign/Run/分区不存在旧 pending 或已尝试状态。每个 Run 开始前 Permit 至少应覆盖 180 秒任务与 30 秒保护余量；建议负责人授权的期限覆盖完整 3 小时 Campaign 和预检余量。过期不足就安全停止，不能根据时间经过推定同意。

## 4. 固定停止协议 B

普通的、已知执行结果且不涉及安全问题的业务严格失败记录并继续，保留负结果与全部分母，不重跑。以下立即停止后续派发：

- Source/Scope/定义/Freeze/config 身份变化，越权、伪造证据、工具协议或未经验证的完成声明。
- Root/Child/分区预算异常，无法确认实际 usage，未知调用、恢复冲突或 Artifact/Journal 损坏。
- Provider 严重错误、网络/协议异常、任务/Campaign 超时、Permit 失效或用户 STOP。
- Collector/Scorer 本身不能安全评估；不能在当前 Campaign 热修复评分器、Prompt、Gold 或阈值再跑。

STOP 路径为 `artifacts/p7/independent-holdout-v3/STOP`。正在发出的外部调用不能假定没有执行或没有扣费；停止不自动释放未知预留，不能盲目恢复或自动重发。供应商端 exactly-once 仍不能承诺。

## 5. 未来执行、采集与封存

执行前重新核对所有 Seal/闭包、真实隔离 PG17/pgvector、原 MCP/源指纹、P3 定义、RAG 版本/本地模型、角色、当前预算与 Permit；不 Seed、不删卷。正式入口仅在新授权后使用：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe evaluation/p7_v3/v3_runner.py --permit <新的有效一次性Permit路径>
```

占位符不能原样运行。没有有效 Permit 时入口在凭据/SDK/新执行前拒绝；本轮没有执行该 Live 命令。

候选每 Run 经过原 review interrupt，由精确宿主批准，再运行原 LangGraph。原 Collector 用 `inspect_run` 和 lease 重读 P3/RAG/Report/Journal/预算/工件；HMAC 签署完整私密采集。独立评分进程读取封存 Gold，Runner 仅消费评分结果；不能把模型自述 succeeded 当作业务 verified。

保留每次模型的返回 ID、finish_reason、native tool 关联、usage/cache/时延，所有 P3 Evidence/Verification、RAG 来源与事实覆盖、完整报告、错误、原账本和未知预留。公开结果默认不包含原文、向量、凭据或原始私密 Prompt。结果目录首次创建且拒绝覆盖。

运行后可离线复评原始签名采集，不重发模型；用冻结统计规则输出 Lane/预期类型分母、strict、合法拒答、错误完成、P3/引用/事实/RAG 完成、失败类别、时延/费用及不适用项。所有 60 状态保留；若安全提前停止，其余仍 not_run，不能缩小分母或宣称 Benchmark 完整通过。

失败后只做只读审计，先区分模型/产品、Gold/数据、工程或 Provider 原因。确有缺陷则另建版本/新封存集验证，不据已观测本包调规则刷成绩；不复用本次 Permit 自动发起第二轮。最后封存原始输入/输出、签名、版本和结果 SHA，报告实际账单是否独立核实，然后停止等待下一步授权。
