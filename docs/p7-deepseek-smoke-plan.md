# P7 DeepSeek Live Smoke 准备计划

日期：2026-10-26（Asia/Shanghai）。这是8条新的合成 **Dev 工程兼容性 Smoke**，不是正式 Holdout 或总体成功率评测。**READY FOR SEPARATELY AUTHORIZED PAID SMOKE；本轮没有付费授权。** 冻结身份与 SHA 见 [新实现冻结](p7-new-implementation-freeze.md)。

## Case / Gold

| Case | 类别 | 冻结目标 | 独立预期 |
|---|---|---|---|
| smoke-01 | SQL-only | 2026年8月已支付CNY收入，排除退款/待付款/区间外 | completed，191.34 CNY |
| smoke-02 | SQL-only | 同月automation事件数，排除dashboard及九月边界 | completed，24 events |
| smoke-03 | RAG-only | 配额升级回复工作日，授权文档精确事实定位 | completed，两个工作日；需原文/Hash/span及宿主字面证明 |
| smoke-04 | RAG-only | 账单复核必须多少分钟解决；原文无此承诺 | unavailable，相关背景可召回，resolution_minutes仍无证明 |
| smoke-05 | SQL+RAG | 九月收入＋已支付收入/MRR口径文档 | completed，398.77 CNY＋正确文档引用，不计算MRR/因果 |
| smoke-06 | SQL+RAG | 八月收入＋未声明的分钟级解决承诺 | partial，191.34 CNY可 verified，文档事实不能升级 |
| smoke-07 | 拒绝/不足 | 导出并行度公告能否证明因果 | partial，保留背景，causal_conclusion_not_verified |
| smoke-08 | 权限负例 | 读取未委派的文档范围 | blocked，原MCP DOCUMENT_NOT_AUTHORIZED，0模型/业务查询/检索 |

两条SQL、两条文档、两条组合、两条负例。按底层 lane，负例也使用文档契约，不能误认为有四个正向 RAG case。8条分母固定；7个真实 Runtime 配置，1条元数据宿主拒绝。任何失败/停止/未运行都保留。

完整输入、Gold、单位/窗口/条件、来源与 SHA 在本机 `artifacts/p7/dev-smoke-v1/sealed`；公开可核对 [Case Manifest](research/p7-dev-smoke-case-manifest-v1.json)。8Case各有独立对象 SHA；Case Seal 固定 inputs/Gold/pins/oracle/budget/assets。实现与协议、Smoke Evaluator Seal分开固定，互不自引用。

Gold 数值先由固定新原件上的独立 Decimal/事件加总产生，再经受限 MCP 的独立 SQL 对照；不是 Agent/P3 输出反推。原件8张账单/5条事件，右开边界和付款/功能筛选有反例。文档事实来自人工可审查的明确合成文本；smoke-03 的字面 proof 是合成宿主夹具，无独立人工签名宣称。其他缺事实/因果不补证明，不要求尚不支持的通用事实证明能力。

封存后自动比对旧60条的**问题输入**和来源 Hash：exact/去数值重合、3gram近重复≥0.8、源字节重合均为0；旧 Gold未用于调优，旧29条不执行。复用了同一业务配方、Schema形状、PG/MCP/BGE/恢复设施，不能称无偏、独立人员盲编或泛化证明。未来一旦实测，这8条即为已观测Dev，不能再充新Holdout。

## 评分及失败分类

所有适用维度同时通过才 strict_correct：业务完成状态、数值/单位/范围、真实P3 verified、源版本/引用、事实要求覆盖、授权、工具协议、原账本/恢复和预算。RAG Worker completion、Evidence验证和最终BusinessCompletion分别记，不合并。事实不足可允许 Worker complete，但最终事实/因果仍 unverified；非completed既不自动失败，也不自动成功。

采用原签名 Collector/inspect_run（原Run lease），复用原数值/引用检查和权威Plan版本结果定位；新适配只增加Phase3D事实覆盖及Dev身份。Gold/Scorer不挂给候选，宿主 proof 仅在原 ReportScope 内使用，不作为模型审批入口。原 Scorer v1/v2未改。

分别记模型推理/协议、召回、P3拒绝、证据不足、权限、snapshot unsupported、budget、provider、基础设施、unknown。仅从原结构化码归类，不凭异常文本猜测；无法确认供应商是否执行时保留 unknown。P3数值对纯文档/宿主拒绝为NA；检索对SQL-only/宿主拒绝为NA，零分母不编百分比。

## 可执行预算与停止

| 项目 | 冻结建议（尚未授权消费） |
|---|---|
| 样例 / Runtime | 8 / 7，顺序执行，并发1 |
| Root / Child | 8 calls/18000 Token；4 calls/18000 Token，不提高旧上限 |
| 输出 / 模型超时 | 1200 Token / 30秒 |
| Campaign | ≤56次模型尝试；≤90000计账Token单位 |
| 时间 | 每任务180秒，整Campaign1800秒 |
| 重试 | SDK及外层0；原内层有界修复/Stop Hook仍受Root限制 |
| 费用建议 | 峰值最保守估算≤0.108 USD；不代表账户实际账单保证 |

原Live平均约2513 Token/观测任务，仅作数量级参考；本次组合任务/压缩可能不同，不外推成功率/成本。公共池可结算已知未用额度，不保证最坏情况下所有Run都能完成：7×18000=126000大于90000，预算不足须停止而非加额度。

复用原 Backend lease＋DurableLedger，派发前一次预留整个18000，不新增计费引擎；已知按原结算，未知保留全额/usage不完整，不能清零或新Run盲重发。7个唯一定义的派发槽×每Root8次构成56次强制边界。Ledger.calls在Campaign层是Run槽，原Root账本calls仍是模型尝试；报告不混单位。

旧Campaign目录、原PG事件、pending或非空Ledger均阻止自动重复执行；新Run ID绑定模式、Case Seal与Freeze SHA。用户STOP/Ctrl-C/超时仅停止本次新候选容器，保留原Journal与父预留。budget/安全/身份/hash漂移、首次严格失败、provider/协议异常、unknown立即停止，不为获取更多样本自动继续。

按 [DeepSeek官方费率](https://api-docs.deepseek.com/quick_start/pricing/) 2026-10-26网页快照，峰值USD/百万Token为hit0.006、miss0.3、output1.2；90000×最高1.2/百万=0.108 USD。实际估算由原每次usage/cache数据与冻结峰值费率产生，未知缓存/未确定用量不造账单。别名/费率可能改变，输入估算和供应商报告并非账单硬承诺；不声称缓存可隔离或已节省费用。

## 配置、授权与运行路径

DeepSeek配置与本机Key非空/形式已检查，Thinking关闭；尚未验证Key/余额/真实响应，未调用API、模型列表或免费探测。真实API只允许原Gateway/NativeTransport，完整预算/工具反馈/Verifier/Report/Durable保留。网站仍Rule-only，Smoke是受信任宿主经原ReportScope和审批链执行，不宣称本轮重测自然语言前端质量。

授权建议模板为本机 `artifacts/p7/dev-smoke-v1/authorization-template.json`：authorized=false、审批角色/授权消息/到期时间为空。模板不是批准；必须以新的明确负责人授权创建独立permit，绑定Freeze、Case/Policy SHA、全部Scope、资源/费用限制和审批范围。旧Gate0/1/2/Holdout授权不适用。

本轮唯一正式执行入口为**零付费**：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe scripts/p7_smoke_run.py --infrastructure artifacts/p7/unified-regression/private/environment.json --mode fake
```

这是一次性身份，不要重新执行已完成Campaign。未来得到新授权后，原脚本才允许 `--mode live --permit <独立批准文件>`；没有permit/授权为false/身份或限额不符，会在读取Key/创建供应商客户端前拒绝。当前不要执行Live命令。

预期记录路径：`artifacts/p7/dev-smoke-v1/private/results/fake` 与 `.../live`，每Case保留 config、probe/start/approve/collect、签名、score、NoModel重放（Fake only）、原Call/Evidence/Verification/Artifact/Trace及状态总账。密钥env和collector.key仅私密存储，不进Freeze/公开Trace/候选挂载。Live不会自动开展恢复故障实验。

## Dry Run与剩余边界

最终结果见机器 Preflight Summary，零真实供应商调用。原产品未变，保留Unified每版本985 passed/1 Live skipped基线；本轮新增评测边界和SDK HTTP Mock定向测试，不重复长耗时全仓回归。真实PG父预算重开测试与本地真实BGE/pgvector/MCP验证单列；Fake/Mock结果不能填真实DeepSeek分母。

仍不支持可信最新/跨来源同一时点快照；表指纹为逐次点检而非全局原子快照。保守Token估算、原查询策略召回局限、开放事实证明、别名/费率变化仍需披露。本轮无新训练、Reranker、查询策略/阈值修改、生产Schema/权限改造、主动Agent、Gate3或后续阶段。

远端CI仍not_run，无commit/push/PR/dispatch。原60条/29未运行与31条历史成绩及失败不变。准备完成只意味着可以申请**单独授权的有界真实Smoke**，不代表DeepSeek业务能力已通过。

## 最终执行前验收（本轮实际完成）

- Freeze、261文件完整运行闭包、只读快照、Case/Gold/Evaluation Seal前后校验通过；冻结后0运行源码变更。
- Python3.11/3.13定向集合各 **71 passed / 2 deselected**；其中被排除的是本次单列的PG/SDK-PG集成入口，不是失败忽略。原SDK-PG全集已在Unified基线验证；本轮原DurableLedger的真实隔离PG重开测试各 **1 passed**。Ruff/格式/Diff检查通过。
- 正式零付费Dry Run：**8 observed / 8 strict_correct，0 not_run**；7个Runtime＋1个授权拒绝。模型决策明确为脚本化，17次决策、255个合成usage单位；真实Provider调用0，真实Token/缓存/账单均未测，不能当作DeepSeek成绩。
- smoke-04 / smoke-06 的RAG Worker实际完成检索，但必需事实验证0/1，最终分别unavailable/partial；smoke-03事实1/1。检索完成未提升业务证明。
- 七条Runtime任务在另一进程中NoModel重放，再独立采集，原 calls、artifacts、snapshot完全相等；无新增模型决策或证据覆盖。
- Campaign原持久Ledger最终为7个Run派发槽、255个已知合成Token单位；未知预留/硬Token拒绝/用户停止/过期或错身份授权/FREEZE_INVALIDATED均有定向反例。权限负例原MCP拒绝、0模型/业务查询/搜索，不把宿主指纹查询冒充零业务读取。
- 本机before-files-corrected记录的767份保护文件均不变，包含原Gold/Seal/Scorer/历史结果与原有未提交修改。初始基线曾继承上轮Unified之前的两份Docker/CI旧SHA，已用上轮稳定验证记录纠正并保留两版；不是本轮改写这两个文件。
- 付费授权模板经实际权限函数拒绝。未调用供应商API/模型列表/免费探测；只读取官方价格文档。当前GitHub工作树CI仍not_run，无commit/push/dispatch。

完整机器结果见 [Preflight Summary](research/p7-deepseek-smoke-preflight-v1.json)，本地日志、失败记录和校验在 `artifacts/p7/smoke-preparation-v1`，原始私密Run在 `artifacts/p7/dev-smoke-v1/private/results/fake`。这些私密文件未自动提交；公开JSON仅包含合成范围和Hash，不含凭据。

**没有剩余的准备工程阻断。可以进入单独授权的真实DeepSeek Smoke，但现在不得调用。** 本轮到此停止，不续跑旧Holdout、不进入Gate3或后续阶段。
