# P7 最终评测验收对照与预算申请

日期：2026-11-03。状态：**非付费准备；等待付费授权**。本文不构成执行许可，不创建 Permit，不调用 DeepSeek。

## 1. 当前源码与身份

- HEAD：`4cf867ee56b837a170a60b0d2abe2534394bb520`
- 工作区：保留全部 independent facts 与 single-case admission 未提交修改
- 必要运行文件 **141 个**，源码身份记录：
  - LF 规范化 manifest：`ff698f8452a6672ddb37e3903f0ca54ff5d02fd20e5652e854a6889205a46b36`
  - raw manifest：`b53c5970f8439955fcb6db5a0e9dff624595c3ea0dd97bd80a90796ac2b3a1d0`
  - Git blob manifest：`bd80172d6b4b9c05748bada31a2b605903766158f1fe4f3ea2b8f3ba57aa9d1a`
- 本轮执行校验规则：**canonical LF SHA256**；Git blob 与 raw SHA 同步留档。15 个文件存在 CRLF。
- 2026-11-03 的 Smoke 曾因 raw 字节/Freeze 不一致创建新 Freeze；该偏离保留，不追溯改写，不据此重跑旧 Live。
- 当前源码完整 CI：**NOT_RUN**；CI #31 是基线 `4cf867` 的 PASS，不是本工作区 PASS。

## 2. 验收对照表

| 原要求 | 已有证据与源码版本 | 可复用 | 缺口 | 本轮方法 |
|---|---|---|---|---|
| ≥50 条独立业务任务 | 新 v3 sealed 60，但历史 Campaign **29 observed / 31 not_run**；seal 校验通过 | **Case/Gold/Scorer 可复用** | 执行绑定仍是旧 product `c2dd57...`；当前源码不匹配 | 先非付费重绑当前源码，再执行 60 |
| 三路径覆盖 | v3 20/20/20 | 是 | 无 | 按 001/021/041 交错顺序 |
| 独立 Gold | v3 Oracle：43 数值、4 JOIN、34 P3 机械检查；不导入 Agent/P3 配方 | 是 | 无人类独立盲审 | Gold 只在离线程，不进入 candidate |
| 未用于调参的封存集 | v3 **29 observed / 31 not_run**；旧 Gate2B 29 unrun 可作补充候选 | 31 v3 fresh；19 old unrun 需 cross-set | 缺 19 fresh / cross-set 协议 | 不重命名、不把 observed 当 fresh |
| 当前源码候选 | HEAD + 141 文件 LF identity | 身份已固定 | v3 `verify()` 返回 `FREEZE_INVALIDATED: runtime/build closure differs` | 新建 v3 implementation binding；不改 Gold/Scorer |
| 意图与 E2E 分离 | Gate1 59 意图（12 live）历史独立 | 只作意图证据 | 无当前 E2E | 不与业务分母合并 |
| 故障注入 | 旧 provider 13 pass/1 fail（畸形 usage）；旧 PG restart 5 条断言，非完整实例矩阵 | 部分历史 | 当前源码/完整矩阵 **NOT_RUN** | 非付费新隔离 PG + 本地 Mock |
| 消融 | P5A L0–L4 20 calls/75,304 Token，仅上下文 A/B | 仅上下文参考 | 六 arm 未验证；10×6 不是已具备能力 | 先验证 arm；不可运行明确 NOT_RUN；0 预算 |
| 成本 | 历史估算；单 Smoke 3 calls/4,365 Token/$0.001076952；无 60/消融账单 | 方法可复用 | 无最终成本/真实账单 | 按 provider usage + 官方峰值上限；bill 保持 not_reconciled |
| 安全 | 历史零违规声明；当前仅定向 admission/independent tests | 部分 | 无当前 60 安全分母 | 冻结守卫；安全/unknown 立即停止 |
| 完整 CI | CI #31 基线 PASS；当前源码 NOT_RUN | 基线仅作参考 | 当前完整 CI | 与评测准备并行，不作为 Smoke 理由 |

## 3. 关键阻塞

`v3_common.verify()` 当前返回：

`FREEZE_INVALIDATED: runtime/build closure differs`

原因是 v3 runner 和 implementation manifest 仍绑定旧 product source snapshot `c2dd57...`；当前工作区是独立 facts 修复后的源码。31 个 v3 fresh case、Gold、Scorer 可复用；另 19 个需旧 Gate2B unrun 或新 authoring，但**不能直接申请付费执行当前源码**。  
这是评测绑定工程问题，不是预算不足；必须先做非付费 rebind、确定 19 条 supplement 协议并重新验证 50/50 preflight。

## 4. 付费计划（等待明确授权）

### Group A：v3 fresh 31（仅为下限）

- v3 31 fresh：SQL-only 10 / RAG-only 10 / SQL+RAG 11
- 25 Runtime + 6 预检宿主拒绝；模型 attempts **200**
- Token 计账上限 **450,000**
- 峰值费用上限 **USD 0.54**
- 并发 1；SDK/外层重试 0；30 秒 provider timeout；单任务 180 秒；campaign 10,800 秒
- Protocol B：普通业务失败记录并继续；安全/未知/预算/身份异常停止
- 数据：仅 v3 合成 inputs/assets/pins；Gold、Scorer、旧业务库不入 candidate

### Group B：新 19 条：未建立

- 用户已明确否决旧 Gate2B 19 条跨集合方案；不得再用。
- 新 19 条公开合成任务尚未 author/freeze；当前不能把它计为已具备。
- 模型 attempts 上限 **480**；Token 上限 **1,080,000**；峰值上限 **USD 1.296**
- arm：Base SQL、Worker/Planner、P3、Context L0–L4、Memory/Recovery、RAG/Report
- 10 个 dev 只用于相对消融，不进入独立质量分母；不可安全运行的 arm 标记 NOT_RUN。

### 总付费上限

| 项目 | 上限 |
|---|---:|
| Runtime | **42**（31+19 supplement，条件性） |
| Model attempts | **336** |
| Token 计账单位 | **756,000** |
| 峰值费用 | **USD 0.9072**（条件性） |
| 真实账单 | 仍为 not_reconciled |

费率免费核对：DeepSeek 官方页 `https://api-docs.deepseek.com/quick_start/pricing/`，`deepseek-flash` 峰值 input hit $0.006/M、miss $0.3/M、output $1.2/M。上界用 18,000 token units/run × $1.2/M。

### 非付费组

- 隔离 PG 全实例重启、Provider HTTP/网络/协议故障、并发/审批/取消/恢复/Idempotency、issued/unknown、Checkpoint/Journal/Ledger/Artifact、身份/版本不一致
- Provider Mock；新建 disposable 实例；不使用旧业务数据库
- Mutation 只在隔离临时副本；不推送危险变体
- **0 付费调用**

### 授权与停止

- 仅在项目负责人明确批准上述上限后执行；不借用历史 Permit/余额
- 24 小时授权窗口；不自动重跑、不替换失败任务
- 普通业务失败保留；未知/安全/预算/身份异常停止受影响的执行
- 不修改 Prompt、P3、Goal、Report、Retriever、Scorer、Gold；不新增框架
- 不 commit/push、不进入 P8–P11、不部署生产

## 5. 当前结论

1. **P7 评测工作：未完成**；入口已绑定且 3 个 Fake 控制通过；v3 只有 31 fresh，新 19 尚未建立；故障注入/消融/最终成本未完成。
2. **评测执行有效性：受阻**；v3 seal 有效但当前源码绑定已通过；新 19 条未建立。
3. **业务质量：not_run**；不能从历史 Smoke 或 Gate2B 前缀推断。
4. **安全指标：not_run**；历史零违规只对应旧版本。
5. **完整 CI：NOT_RUN**（当前源码）。
6. **下一步**：先批准/完成非付费 rebind 或明确允许作为预备工程；然后审批本预算计划。
