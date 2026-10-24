# P7 评测状态索引

2026-10-24：用户后续明确要求“跑完 Gate 1 先不进行下一步”。当前仅完成 [Gate 1 有界开发试验](p7-gate1.md)，**P7 整体未验收**，不因局部结果提前进入 Gate 2/3 或 P8–P11。

| 项目 | 实际状态 |
|---|---|
| Gate 0 SQL / RAG / SQL+RAG | 原有真实 Smoke 通过；历史失败保留，见 [Gate 0](p7-gate0.md) |
| Rule-only 原基线 | 59 条 dev 实跑 46/59，未改规则 |
| LLM-only / Hybrid | 同一获授权 12 条 dev 实跑 10/12、12/12；13 次真实调用/11783 Token |
| 正式 Holdout | 59 条已封存，未读取 Gold 进行评测；Gate 2 未授权/未开始 |
| 50 条业务目标 | 在收紧前已启动并完成；真实 PG/MCP/P3/Durable/Report + 显式 Fake 决策，48/50 符合独立 Gold，不能当真实模型成功率 |
| Provider HTTP 故障 | 收紧前初次执行为 13 passed、1 failed；畸形 usage 的原缺陷未修复，后续标注 strict xfail 的测试版本未再次运行 PG |
| 隔离 PG 真重启 | 已启动实验安全收束；5 类最终只读断言成立，期间 2 个观察脚本问题及日志保留，不能声称整个故障矩阵完成 |
| 新的 RAG 专项/阈值对比 | not_run，未在收紧后开展 |
| L0–L4 真实费用消融、产品/多模型对照 | not_run，本轮不实施 |
| 最终完整 PG / GitHub CI | 未重新执行 / 未推送；不借历史 CI 声称本轮通过 |

协议与分母见 [冻结协议](evaluation-protocol.md)、[protocol JSON](research/p7-protocol.json)、[意图 corpus manifest](research/p7-intent-corpus-manifest.json)、[业务 Gold manifest](research/p7-business-manifest.json)。59 个意图问题、50 条业务目标、512 项非 PG 测试分别计数，不能合并凑业务成功率。

50 条业务开发目标的独立 Gold 为原 XLSX 行 + Decimal/集合，按已审阅口径计算；无需模型计算数字。38 条应有数字，36 条准确发布；12 条合理 unavailable，另 2 条合法空月份/空支付筛选误拒绝（business-001、006）。报告没有发布错误 verified 数字。48/50 的开发工程正确率不证明真实模型能力；没有使用 Holdout 结果改配方。全部指标请求明确提供已确认口径，不是自然语言理解端到端质量。

原始逐任务文件保存在 `artifacts/p7/business/`；收入空窗口的 missing code 为 metric_verification_rejected，本轮没有为了提升分数修改 SQL/P3。该问题与畸形 usage 一并作为后续独立修复候选，不能偷偷修复后覆盖旧分数。

本轮停止边界：不继续 Gate 2/3、不新增付费调用、不修改默认网站策略、不自动提交/推送。未来正式评测必须复核冻结文件与相应独立授权；不能把开发集成绩或历史 Gate 0 Smoke 当 Holdout 成绩。
