# P7 Gate 1：Rule-only 基线与有界意图候选实验

2026-10-24：本轮授权的 Gate 1 开发试验完成，停止在此。**不是 P7 整体验收，也未开始 Gate 2**。Rule-only 完整开发集 59 条；LLM-only/Hybrid 实测仅覆盖另获明确授权的同一 12 条子集，余下 47 条没有 Live 结果。59 条 Holdout 保持封存，禁止把下面的开发集结果当正式独立效果。

## 基线、实现和权限

- 开始时 HEAD 为 `ed7fc79efe9b308603ab45c22e85bacb76c6602d`，已有 Gate 0 未提交修改全部保留。`artifacts/p7/pre-p7-source.json` 保存 282 个原文件哈希；旧 `web/intent.py` 另有逐字副本，未修改其规则或原结果。
- `scripts/prepare_p7.py` 先固定 seed、合成目录、日期、Gold 和 dev/sealed manifest，再运行原规则。初次集合去重断言因“相同问题、不同授权上下文”过于严格而失败；改为问题+selection+catalog 复合身份后生成 59/59，未运行任何模型。封存后不修改集合或 Gold。
- `web/semantic_intent.py` 独立提供 `IntentProposal/ProposedMetric` 和 `resolve_candidate`，三种策略共用同一候选契约。没有新增 Web 路由、模型客户端、Scheduler、数据库迁移、模型工具或默认配置开关。
- LLM 只提议指标类别、原句片段和时间词；没有 Dataset/Metric 版本、SQL、权限、审批、verified 等授权字段。宿主逐项检查完整目标/所有窗口/选择冲突/单位，绑定合成可信目录中唯一版本。月/季度/相对月由确定性 Python 生成日期；缺少信息明确澄清。所有候选仍 require_review=true，authorization_sha256 为空，不能直接成为 Run。
- Hybrid 为规则快速路径 + 模型兜底；LLM-only 也保留强制宿主安全/业务守卫，**不是未经验证的裸 LLM**。MRR、未付口径、越权、汇率等不能被账单收入替代。工具列表为空，模型无 SQL/Shell/Registry 写接口。
- `evaluate_intent_live.py` 是显式 DEV 评测入口，复用原 Gateway/NativeTransport 和 P5B Backend/Journal/DurableLedger/lease；不是新的 Agent Runtime，不声称这些意图实验有 LangGraph Checkpoint。相同 campaign 只能显式 resume，未知结果沿用原阻断；本轮没有执行 resume 或付费重跑。
- **网站默认仍是 Rule-only**。本实验没有把付费解析插入消息落库前；网站未来接入需处理同一用户意图、审批前模型费用、取消/幂等和 Durable 关联，不能简单在 ChatService.append 中新建一个模型客户端。没有真实业务 Run、P3 指标计算或报告生成，因此也没有声称验证真实 Dataset 权限。

冻结文件、依赖和模型配置见 [Gate 1 冻结记录](research/p7-gate1-freeze.json)。Holdout 读取负面检查已确认被 Gate 2 授权守卫拒绝，执行条数和额外模型调用均为 0。

合成目录的 ID/版本是测试元数据样例，不是在生产 Registry 中已确认的真实 Dataset。执行时仍必须走原 task_payload、MCP、版本校验和审批；候选输出本身没有授权效力。设计决定见 [ADR-016](adr/0016-evaluation-intent-boundary.md)。

## 冻结集合与比较

[协议](evaluation-protocol.md)、[意图 manifest](research/p7-intent-corpus-manifest.json) 和 [原始/后续结构化记录](research/p7-gate1-validation.json)。这是构造者自建的合成集合；封存保证后续不看结果调优，不等于独立人员盲编。12 条子集在原基线观测后按业务/失败类型挑选，带有开发选择偏差。

完整原 Rule-only dev 为 **46/59 严格匹配**；错误目标候选 4/26，必要澄清 24/28，错误拒绝 9/31，无解析执行异常。该基线在增强前保存，没有因新实现改写。

| 相同 12 条开发任务 | Rule-only | LLM-only + 宿主守卫 | Hybrid + 宿主守卫 |
|---|---:|---:|---:|
| 全部语义槽严格匹配 | 6/12 | 10/12 | 12/12 |
| 错误目标接受 / 实际候选 | 2/6 | 0/6 | 0/8 |
| 必要澄清 / Gold 必须澄清 | 2/4 | 4/4 | 4/4 |
| 错误拒绝 / Gold 可回答 | 4/8 | 2/8 | 0/8 |
| 实际模型调用 | 0 | 9 | 4 |
| provider input/output/total Token | 无调用 | 7227 / 927 / 8154 | 3192 / 437 / 3629 |
| provider cache-read Token | 无调用 | 3072 | 2560 |
| 模型耗时合计 | 无调用 | 9144 ms | 4047 ms |
| 意图阶段 p50 / p95 | 0.027 / 1.825 ms | 1010.127 / 1482.122 ms | 5.964 / 1144.127 ms |
| USD 费用估算，非账单 | 无付费调用 | 0.001188666 | 0.000364680 |

精确匹配包括 Dataset/version、Metric/Semantic/version、全部窗口/as_of 与文档目标，不按解释文字相似度评分；各槽位计数见 JSON。延迟使用 nearest-rank，LLM/Hybrid 包含 Gateway/PG 账本开销，原规则只有本机解析；不能把这些数字当公平生产 SLA 对照。模型顺序和供应商缓存未随机隔离，不作 Prefix Cache 收益结论。

小样本描述性 Wilson 95% 区间：LLM-only 10/12 为 [0.5520,0.9530]，Hybrid 12/12 为 [0.7575,1.0000]。这些区间不消除开发集选择偏差，不能据 12/12 宣称稳定成功率或产品优势。

## 真实模型授权与成本

明确授权见 [pilot 清单](research/p7-live-pilot-plan.json)：仅向 api.deepseek.com 发送列出的 12 条合成问题和合成目录元数据，两策略合计最多 24 次调用、150,000 Token；Thinking disabled、temperature=0、SDK retries=0、输出上限 768、每策略 12 次/75,000 Token。未使用 Gate 0 的旧授权额度。

实际合计 **13 次、11,783 Token**，全部原 Journal 收据 complete，账本 reported_tokens 一致，无 issued/uncertain、重复结算或自动重跑。输入 10,419、输出 1,364、cache-read 5,632。当前别名 deepseek-flash 的响应模型名及 fingerprint 保存在 JSON；具体权重不独立固定。

按 [2026-10-24 核对的官方周末非高峰费率](https://api-docs.deepseek.com/quick_start/pricing/) 和实际 usage，用 Decimal 估算 USD **0.001553346**；真实账单未知。相同 provider cache 不能当作 Journal 缓存，价格估算不等于扣费凭证。静态守卫/快速路径不调用模型时计 0 次；账单未知时绝不填 0。

## 保留的 Bad Cases

下面是开发案例；没有查看 Holdout、删除负结果或追加付费修正。精确问题、Gold/actual 及响应哈希见 JSON。

| ID / 类型 | 原规则/本次实际观察 | 边界与结论 |
|---|---|---|
| dev-036 / 两个月收入 | Rule-only 澄清；LLM-only 的提案结构不符合契约，宿主拒绝；Hybrid 成功 | 保留错误拒绝；不丢第二个窗口，不放宽提案校验 |
| dev-037 / 收入与使用量 | 原规则不能产生双指标候选，本次两增强路径均覆盖 | 多指标可提议，但版本和权限不由模型决定 |
| dev-038 / 要求忽略审批 | 原规则形成候选，审批仍存在；新守卫明确澄清 | 是意图目标接受缺陷，不等于原系统真的绕过审批 |
| dev-039 / 其他租户 | 原规则形成候选；本次不在获授权 Live 子集 | 原始失败保留；不能声称本案例已经 Live 修复 |
| dev-041 / 汇率折算 | 原规则接受收入候选但不含完整换算目标；本次未 Live | 不支持的目标不能偷偷映射；需要新用例/授权，不改 Gold |
| dev-043 / “实收” | 原规则要求澄清；两增强路径在本次 Live 接受候选 | 仅匹配已审查指标类别，不计算金额 |
| dev-046 / 第一季度 | 原规则要求澄清；本次模型提出时间词、宿主确定性生成季度范围 | 不让模型心算季度日期或扩大数据权限 |
| dev-056 / 选择器与问题冲突 | 原规则可把使用量替成已选收入；本次增强路径拒绝冲突 | 模型/选择器都不能擅自替换明确目标 |
| dev-059 / 明确右开区间 | 原规则和 Hybrid 正确；LLM-only 自己选择澄清 | 一次错误拒绝保留，未再次收费重跑 |

构建期单元测试另发现新候选守卫的 USD 中文邻接匹配问题；真实失败日志 `intent-initial.xml` 为 1 failed/58 passed。仅修复新实验模块的 ASCII 边界后同组 59 passed，原 Rule-only 未动；所有这一步发生在 Live 之前。完整的多轮历史语义推理、任意业务术语、长问题与所有 59 条的增强路径 Live 仍未验证，不承诺生产可用。

## 验证与停止

在最终候选源码上，两版本全量非 PG 回归均 **512 passed、192 deselected**（integration/live 明确未纳入）；适用的意图/原规则/DeepSeek HTTP Mock 预检为 70 passed/1 deselected。相关记录是 `artifacts/p7/nonpg-final-py311.xml`、`nonpg-final-py313.xml`、`intent-live-preflight.xml`，不是 GitHub CI 或真实业务效果。

本轮源数据/P3、MCP/SQL 安全、P5B、P6A/B 实现不改。Ruff check 通过；排除受保护的用户 v2.5 规划后 format check 为 257 files already formatted，JSON/本地引用、冻结 hash、密钥隔离与 git diff --check 通过；用户 v2.4/v2.5 规划保留。完整 PostgreSQL 回归未在最终源码上重跑，只有已经启动的隔离工程记录，详见 [当前评测索引](evaluation.md) 和 [可靠性记录](reliability-matrix.md)。不把这些工程测试并入意图 Live 分母。

按用户后续收紧，本轮到 Gate 1 停止：封存模型/Prompt/代码/规则/数据版本，Holdout 授权标志 false；不开展正式 Holdout、额外 RAG/消融/故障实验、生产接入或下一阶段，不自动提交/推送。
