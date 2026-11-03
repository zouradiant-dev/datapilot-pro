# P7 当前可靠性记录（未完成全部矩阵）

用户收紧至 Gate 1 后，未开始新的 Gate 3 实验。以下只记录此前已启动工作及其安全收束；不作为 Gate 1 意图质量分母，更不代表原 P7 可靠性全部验收。

## 实例与副作用范围

仅使用新 `datapilot-p7-postgres-1`、127.0.0.1:55439、datapilot_p7 和专用卷。脚本同时核对名称、disposable label、精确 PG17+pgvector 镜像；没有 down、删除或清卷接口。原 datapilot-pro 数据库和卷没有停止/修改角色或重新 Seed；隔离新库只成功 Seed 一次 48 客户。首次初始化调用错 Python 模块，在建表前失败，原日志保留；修正评测调用入口后续做成功步骤，不重复 Seed。

## 已启动的 HTTP SDK + PG Journal 初次结果

| 故障 | 初次真实执行观察 | 预算/重复请求 |
|---|---|---|
| HTTP 401/403/429/500/502/503/504 | 7 项通过；原 Journal 将异常外发保守标 unknown，第二次被 RECOVERY_UNCERTAIN 拒绝 | 每项 1 次 HTTP Mock attempt，保留预算 |
| ConnectError / ReadTimeout | 2 项通过；不靠异常字符串假定未执行 | 保守阻断，不重发 |
| 取消 | 1 项通过；持久取消为真 | 原账本保留，第二次 CANCELLED |
| 缺 usage | 1 项通过；响应已知、计费未知 | 已提交响应可重放，保留最大预留，不伪造 0 Token |
| null content / 不完整 tool call | 2 项通过；已提交响应导致确定性 PLAN_INVALID/MODEL_OUTPUT_INVALID | 复用同一错误响应，不新增 HTTP |
| 畸形 usage | **1 项失败**；SDK 对象带非法 total_tokens 被保存，缓存读取触发未包装 ValidationError | 预算保留、没有重复请求；错误分类/恢复边界缺陷未修复 |

证据：`artifacts/p7/provider-initial.xml/.log`，13 passed/1 failed。当前正式测试对最后一项增加 strict xfail 标记和事实记录，但根据用户停止边界**未再次运行这版 PG 测试**，不能写成 13 passed/1 xfailed 的已执行结果。没有真实供应商故障请求、费用或 exactly-once 结论。

## 已启动的实际 PG 重启

实际重启整个专用实例，并非只 terminate 一个 backend。第一轮观察脚本直接 hash 嵌套 DTO 导致 TypeError，保留 `restart-evaluation.log`；第二轮把已完成 bootstrap 工具收据也当模型调用，导致计数断言失败，保留 `restart-v2.log`。这些是评测脚本错误，不是 Runtime 故障结论。

随后只读重核第二轮的同一组 Run、原前后快照和既有子进程输出，未重启第三次、未恢复执行或新增模型调用，五类断言成立：

- 已完成 Run 的 Manifest、Ledger、收据、Artifact 引用全不变；重复读取没有新调用。
- Worker 后暂停 Run 安全完成，原调用次数/预算不变。
- review Run 仍等待可信审批，模型调用 0。
- cancelled Run 重启后仍 CANCELLED。
- 真正模型 double 的 issued 窗口在连接丢失后 RECOVERY_UNCERTAIN；仍仅 1 个模型收据，另 1 个原已完成 bootstrap 工具收据，均未重发。

`artifacts/p7/restart-v2/verification.json` 包含修正后的事实、旧失败日志位置及全部前后快照。模型本身是显式 Fake/阻塞测试 double；只有 PG/驱动/跨进程链真实，不能称真实 Provider 故障，也不把 uncertain 算透明恢复成功。

## 待后续独立授权的范围

新的 RAG/阈值专项、完整并发/TTL/维护/遥测矩阵、临时源码变异、L0–L4 成本消融及正式业务 Holdout 均未继续执行。原安全守卫、P3/P5B/P6A/B 未为评测弱化。未来需在同一冻结协议上明确剩余实验授权、版本和分母，不以本页部分结果替代完整验收。


## P7 Final Evaluation Prep（2026-11-03）

本轮不重跑旧故障矩阵，也不把旧结果提升为当前源码证据。已确认的历史结果：旧 Provider HTTP 测试曾 13 passed / 1 failed（畸形 usage）；随后统一回归将 Journal 缓存畸形响应类型化为 `RECOVERY_CORRUPT`，并移除对该项的 xfail（见 [统一回归](p7-unified-regression.md)）。旧隔离 PG 重启只完成 5 类只读断言且是显式 Fake 模型 double，不是完整实例矩阵。当前工作区源码的完整故障注入整表仍为 **NOT_RUN**，需新隔离 PG 与本地 Provider Mock；不以 `pg_terminate_backend` 代替全实例重启。对照、Final 50 部分封存与授权边界见 [最终评测计划](research/p7-final-evaluation-plan.md) 与 [封存与下一步](research/p7-final-50-closure-and-next.md)。
