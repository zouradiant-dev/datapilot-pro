# P7 评测状态索引

后续仅做 [Scorer v2 离线审计](scorer-audit.md)：修正当前 Plan 版本任务键，原 31 条响应从 v1 的 25/6 修订为 v2 的 26/5，仅 bh2-030 严格判定变化；原 v1 原样保留，29 条仍 not_run，没有新的模型调用。RAG 检索完成 8/11 与业务正确 8/11 的 Case 集合不同，不能混为一项成功率。下段为首次 Live 原冻结 v1 的记录；完整 Gate 2B 仍未验收，预算/其他产品问题只审计未修复。

当前：[Gate 2B 正式业务 Live](p7-gate2b-live.md) 已按本轮明确授权执行，在 bh2-031 原预算预留失败后停止：60 条中观测 31 条，冻结评分严格通过 25 条、未通过 6 条，29 条 not_run。61 次真实调用 / 77,897 Token，费用估算 USD 0.009241476，未取得账单。源码/Gold/Scorer 未调优；RAG 结果键的评分汇总缺陷独立披露，不现场改分。**完整 Gate 2B、Gate 2 整体及 P7 均未验收**。下列旧准备/意图/CI 为各自历史记录，不自动继续 Live 或进入 Gate 3。

| 项目 | 实际状态 |
|---|---|
| Gate 0 SQL / RAG / SQL+RAG | 原有真实 Smoke 通过；历史失败保留，见 [Gate 0](p7-gate0.md) |
| Rule-only 原基线 | 59 条 dev 实跑 46/59，未改规则 |
| LLM-only / Hybrid | 同一获授权 12 条 dev 实跑 10/12、12/12；13 次真实调用/11783 Token |
| 意图 Holdout | 原 59 条首次正式评测：Rule-only 46/59、LLM-only 58/59、Hybrid 57/59；实际 67 次真实调用/59,640 Token，负结果保留 |
| 正式业务/RAG Holdout | 三路径各 20；SQL 18/20、RAG 7/11 已观测（余 9 条未跑）、SQL+RAG 20 条未跑。计划分母 60 不变；原冻结分数/失败保留，[完整账本与限制](p7-gate2b-live.md) |
| NUMERIC 修复前后定向检查 | 32 个定义精确登记，旧零值 rejected 留存；016/052/047 三次新定向 P3 verified。此行是 Live 前工程快照，不代替正式评测结果 |
| Gate 2B v2 本地回归 | 3.11/3.13 各原有 741 passed、17 skipped，另最终新增 37 passed；非付费工程验证，不是业务 Holdout 成绩，也不是新 CI |
| 50 条业务目标 | 在收紧前已启动并完成；真实 PG/MCP/P3/Durable/Report + 显式 Fake 决策，48/50 符合独立 Gold，不能当真实模型成功率 |
| Provider HTTP 故障 | 收紧前初次执行为 13 passed、1 failed；畸形 usage 的原缺陷未修复，后续标注 strict xfail 的测试版本未再次运行 PG |
| 隔离 PG 真重启 | 已启动实验安全收束；5 类最终只读断言成立，期间 2 个观察脚本问题及日志保留，不能声称整个故障矩阵完成 |
| 新的 RAG 专项/阈值对比 | not_run，未在收紧后开展 |
| L0–L4 真实费用消融、产品/多模型对照 | not_run，本轮不实施 |
| Gate 1 基线 CI | `49969b7` / Run 40083421825，3.11/3.13 各 689 passed、15 skipped，含真实 PG/MCP 与 Fake/Mock；不是本次新增 Gate 2 脚本的 CI |
| Gate 2 已提交版本 CI | `18271d7` / Run 40096866653，3.11/3.13 各 709 passed、17 skipped，2026-10-24 22:41 +08:00 重核 Success；原“未提交/未运行新 CI”为推送前快照 |

协议与分母见 [冻结协议](evaluation-protocol.md)、[protocol JSON](research/p7-protocol.json)、[意图 corpus manifest](research/p7-intent-corpus-manifest.json)、[业务 Gold manifest](research/p7-business-manifest.json)。59 个意图问题、50 条业务目标、512 项非 PG 测试分别计数，不能合并凑业务成功率。

50 条业务开发目标的独立 Gold 为原 XLSX 行 + Decimal/集合，按已审阅口径计算；无需模型计算数字。38 条应有数字，36 条准确发布；12 条合理 unavailable，另 2 条合法空月份/空支付筛选误拒绝（business-001、006）。报告没有发布错误 verified 数字。48/50 的开发工程正确率不证明真实模型能力；没有使用 Holdout 结果改配方。全部指标请求明确提供已确认口径，不是自然语言理解端到端质量。

原始逐任务文件保存在 `artifacts/p7/business/`；收入空窗口的 missing code 为 metric_verification_rejected，本轮没有为了提升分数修改 SQL/P3。该问题与畸形 usage 一并作为后续独立修复候选，不能偷偷修复后覆盖旧分数。

推送前工程历史快照：Gate 2B 工程准入通过，等待独立 Live 授权；适用回归两版本各 262 passed、2 deselected，真实 PG/MCP + Fake/Mock/确定性执行。此前 173 项、各 5 项诊断及所有失败保留，SQL Decimal 边界修复形成新 Freeze。此段不再表示当前未运行 Live；当前已授权尝试及安全中止见页首，不进入 Gate 3，不提交推送。


## P7 Final Evaluation Prep（2026-11-03）

当前源码（HEAD `4cf867…` + 未提交 independent facts/single-case admission/current Formal 入口与宿主确认绑定）的完整 CI 仍为 **NOT_RUN**；基线 CI #31 只覆盖 committed 4cf867。

已发生的非付费/有界进展（不得回写成“P7 已验收”）：

- 19 条公开合成 supplement 已封存；与 retained 31 条合并为 Final 50 清单并物化到 `datapilot_p7_current`。
- Final 50 v3 已部分执行后 STOP：18 评分 / 10 严格正确 / 8 严格失败 / 31 未执行；详见 [v3 结果](research/p7-final-50-v3-results.md) 与 [封存与下一步](research/p7-final-50-closure-and-next.md)。
- 八条评分器标记的 `rag_retrieval_failure` 经只读拆分：检索均命中，真实缺口为 Formal runner 未调用 `confirm_finite_scope`（`goal_scope_not_attested`）；原分数保留，不改 Gold/Scorer 重测。
- 064/077 口径错配已裁定；017 版本身份 blocked 保留；不静默重映射。
- Combined 独立文档事实修复后有一次有界 Live 业务 completed，但 Freeze 原始字节治理 FAIL，完整 CI 仍 NOT_RUN。
- 畸形 usage 的 Journal `RECOVERY_CORRUPT` 类型化已在统一回归中落地；隔离故障矩阵整表对当前工作区仍为 NOT_RUN。

旧计划中的 `FREEZE_INVALIDATED: runtime/build closure differs` 描述的是再绑定前的 v3 product snapshot 状态；current Formal 入口与源码快照已另建，**不能**把该句当作“19 条尚未建立”的当前事实。分组预算与授权边界仍见 [最终评测计划](research/p7-final-evaluation-plan.md)；任何续跑须新 Permit。
