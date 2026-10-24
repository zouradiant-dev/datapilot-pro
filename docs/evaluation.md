# P7 评测状态索引

2026-10-24 当前：用户已单独授权进入 Gate 2，并批准一次有界意图 Holdout Live。[Gate 1](p7-gate1.md) 保留历史；[Gate 2 意图评测](p7-gate2.md) 已完成，**业务 E2E 尚未运行，Gate 2 整体及 P7 均未验收**。不进入 Gate 3 或 P8–P11。

| 项目 | 实际状态 |
|---|---|
| Gate 0 SQL / RAG / SQL+RAG | 原有真实 Smoke 通过；历史失败保留，见 [Gate 0](p7-gate0.md) |
| Rule-only 原基线 | 59 条 dev 实跑 46/59，未改规则 |
| LLM-only / Hybrid | 同一获授权 12 条 dev 实跑 10/12、12/12；13 次真实调用/11783 Token |
| 意图 Holdout | 原 59 条首次正式评测：Rule-only 46/59、LLM-only 58/59、Hybrid 57/59；实际 67 次真实调用/59,640 Token，负结果保留 |
| 正式业务/RAG Holdout | not_run；现有 50 条业务 dev 不可冒充，需先独立封存任务/来源/Gold，再批准相应 Live |
| 50 条业务目标 | 在收紧前已启动并完成；真实 PG/MCP/P3/Durable/Report + 显式 Fake 决策，48/50 符合独立 Gold，不能当真实模型成功率 |
| Provider HTTP 故障 | 收紧前初次执行为 13 passed、1 failed；畸形 usage 的原缺陷未修复，后续标注 strict xfail 的测试版本未再次运行 PG |
| 隔离 PG 真重启 | 已启动实验安全收束；5 类最终只读断言成立，期间 2 个观察脚本问题及日志保留，不能声称整个故障矩阵完成 |
| 新的 RAG 专项/阈值对比 | not_run，未在收紧后开展 |
| L0–L4 真实费用消融、产品/多模型对照 | not_run，本轮不实施 |
| Gate 1 基线 CI | `49969b7` / Run 40083421825，3.11/3.13 各 689 passed、15 skipped，含真实 PG/MCP 与 Fake/Mock；不是本次新增 Gate 2 脚本的 CI |
| Gate 2 本地验证 | 两版本非 PG 回归、隔离 PG+Mock 与只读账本复核见 Gate 2 交付；“未提交/未运行新 CI”为推送前快照，后续用户已单独要求上传，实际 CI 以对应提交的 Actions 为准 |

协议与分母见 [冻结协议](evaluation-protocol.md)、[protocol JSON](research/p7-protocol.json)、[意图 corpus manifest](research/p7-intent-corpus-manifest.json)、[业务 Gold manifest](research/p7-business-manifest.json)。59 个意图问题、50 条业务目标、512 项非 PG 测试分别计数，不能合并凑业务成功率。

50 条业务开发目标的独立 Gold 为原 XLSX 行 + Decimal/集合，按已审阅口径计算；无需模型计算数字。38 条应有数字，36 条准确发布；12 条合理 unavailable，另 2 条合法空月份/空支付筛选误拒绝（business-001、006）。报告没有发布错误 verified 数字。48/50 的开发工程正确率不证明真实模型能力；没有使用 Holdout 结果改配方。全部指标请求明确提供已确认口径，不是自然语言理解端到端质量。

原始逐任务文件保存在 `artifacts/p7/business/`；收入空窗口的 missing code 为 metric_verification_rejected，本轮没有为了提升分数修改 SQL/P3。该问题与畸形 usage 一并作为后续独立修复候选，不能偷偷修复后覆盖旧分数。

当前停止边界：本次已批准的 Gate 2 意图 Live 结束，不追加业务模型调用、不进入 Gate 3、不修改默认网站策略、不自动提交/推送。业务 Holdout 必须单独封存与授权；不能把意图分数、开发集成绩或历史 Gate 0 Smoke 当业务 E2E 成绩。上述旧工程故障及负结果保留，本轮不借正式评测修复生产代码。
