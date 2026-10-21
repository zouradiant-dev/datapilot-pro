# P5A DeepSeek 真实上下文对照实测

日期：2026-10-21。模型 `deepseek-flash`，显式关闭 Thinking Mode；不推进 P5B/P6，不改生产 ContextManager、Worker Loop、SQL/MCP 或数据库权限。

## 结论与范围

**L1/L2/L3 在本组长历史中减少了实际 Token；L4 计入摘要后仍减少 Token，但估算费用和耗时反而增加。短查询没有触发压缩，不能把其波动算作压缩收益。**

两次 opt-in 实验合计 **20 次真实 API 调用、75,304 个供应商报告 Token、16/16 组执行通过**。它们是 5 种受控场景，不等于 16 个独立经营分析任务或总体成功率。真实 SDK、Gateway、父子 Ledger、Worker 子图、ToolRegistry、MCP 和 PostgreSQL 均走现有路径。默认运行脚本只校准，不调用供应商。

- 短查询：从空 Worker 历史开始，真实模型选择 SQL、受控执行后确认引用，开/关各 1 次。
- 普通长历史：真实 MCP 取得 Schema 和查询工件，宿主构造回放；L1、L3 各含 12 次 Schema 反馈及 1 次查询反馈，L4 含 4 次 Schema 反馈及 1 次查询反馈。中间长注释明确为合成材料，不能算作之前真实模型推理。各开/关 2 次，第二次交换执行顺序。
- L2 压力补测：对同一真实查询观察构造 4 次回放，其中 3 条反馈各注入 6,000 字符非权威文本，开/关各 1 次。**它刻意越过正常 L0 模型视图限制，不代表生产工具会自然返回这样的超大正文。** 源 SQL 工件及数值保持原样。
- 普通 Schema 回放实际只触发 L1；L2 的证据来自单独压力场景。没有实现真实 RAG，也不把合成注释当文档检索结果。

## 供应商实际 Token 与耗时

以下为**每组平均实际总 Token（输入+输出，包含额外摘要）**；不是 UTF-8 估算，也不是只选最终一次模型调用。耗时是完成 Worker 和验证的墙钟时间，包含新增工具调用，不包含回放准备/本地门限校准。

| 场景 | 每侧样本数 | 压缩关 → 开，总 Token | 总 Token 减少 | 平均耗时，关 → 开 |
|---|---:|---:|---:|---:|
| 短查询，0 次压缩 | 1 | 2,447 → 2,438 | 不归因于压缩 | 1.593 → 1.469 秒 |
| 12 次 Schema 回放，实际 L1 | 2 | 6,830 → 3,795 | 44.44% | 0.946 → 0.985 秒 |
| 超大重复视图，L1+L2 压力补测 | 1 | 5,890 → 2,393 | 59.37% | 1.219 → 0.765 秒 |
| 长观察回放，L1+L3 | 2 | 10,529 → 2,620 | 75.12% | 0.992 → 0.727 秒 |
| 前三级不足，L1+L3+L4 | 2 | 4,347 → 2,947 | 32.21% | 1.062 → 3.031 秒 |

输入/输出拆分进一步说明 L4 的代价：

| 场景 | 平均输入，关 → 开 | 平均输出，关 → 开 | 每次开启组的摘要调用 |
|---|---:|---:|---:|
| L1 | 6,776 → 3,741 | 54 → 54 | 0 |
| L2 压力补测 | 5,844 → 2,347 | 46 → 46 | 0 |
| L3 | 10,482 → 2,573 | 47 → 47 | 0 |
| L4 | 4,302 → 2,413 | 45 → 534 | 1 |

L4 两次摘要合计消耗 **2,102 tokens**，已计入总数；不能只用最后 Worker 请求的输入减少量声称省费。未额外重试失败摘要或调参挑选正面结果。

## 费用与缓存

每次响应的真实 usage 均完整，原始 prompt_cache_hit_tokens + prompt_cache_miss_tokens 与 input_tokens 一致，total_tokens 也与 SDK 归一化值一致。本次观察到缓存命中字段及非零命中；没有实验控制缓存清空/隔离，不能将缓存变化归因于压缩。短查询两组首个请求哈希相同，均没有压缩事件；其小幅用量/延迟差异和缓存热度不支持压缩收益结论。

采用 2026-10-21 核对的 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：Flash 每百万 Token 高峰价为缓存命中输入 $0.006、未命中输入 $0.30、输出 $1.20；低峰价为一半。计算公式为 `(hit×输入命中单价 + miss×输入未命中单价 + output×输出单价)/1,000,000`，全部摘要输入/输出计费。

按本样本实际缓存用量套用该单价，L4 每组高峰估算 **$0.000516696 → $0.000988380，增加 91.29%**；低峰同样比例。原因是摘要输出更多、输出单价更高。全部 20 次调用的统一低峰/高峰单价估算区间为 **$0.006169278–$0.012338556**。这是公示单价推算，**没有核对账户账单或实际扣款**；价格、缓存热度和时间安排会影响结果，不宣传稳定费用下降。

## 正确性与不变量

16 组执行均经原 Worker 契约与 Coordinator.verify 通过；引用工件的结果与另一条独立 MCP SQL `COUNT(customer_id)` 对照均为 240、无截断。普通长回放和压力补测的开/关输入历史 SHA 相同，最终引用的 query artifact ID 完全一致。短查询由模型自主选择实际 SQL，引用在各自 Run 内校验，不要求两个独立 SQL 执行的工件 ID 相同。

逐组检查：原输入消息不变、assistant/tool 配对闭合、源工件完整内容不变、压缩归档保留全部原回放、引用未被摘要改写、结果符合独立查询。真实 L4 摘要通过现有字段级目标/约束/权限/引用校验。模型视图明确是有损投影；上述完整性仅覆盖**同 Run 内存**，没有实现跨进程恢复，也不证明任意经营分析的语义质量。P3 verified 指标 Evidence、金额/流失口径与复杂报告不在本次真实 API 样本内；不把 P4 Artifact 称为 P3 Evidence。

## 设计限制与复现

为了发送未经压缩的完整基线，关闭组的本地准入上限为 64,000 字符；开启组按目标等级本地校准，L1=17,000、L2 压力补测=9,500、L3=11,000、L4=7,000，最大上下文估算上限均为 100,000。若关闭组也使用同一较小上限，长输入会被宿主拒绝。因此本实验比较原始/压缩模型视图，不声称两组拥有相同宿主窗口。调用/Token 父预算、模型、输出上限 1,200、工具权限、输入源和目标均一致。校准阶段使用显式本地摘要替身挑选可触发的门限，没有选择真实 API 结果或调试成更漂亮的结果。

长历史各只有两对、短查询和超大压力各一对；不能估计稳定成功率、P95、长会话累计成本或复杂用户问题质量。L4 是现有受限结构化摘取，不是自由语义摘要。这次负面成本结果保留，不据此更改生产默认开关或推进新功能。

记录固定了模型别名、调用时间、参数、用量及源码快照；供应商响应未提供可固定的权重修订，后续别名更新可能改变复测结果。机器记录的源码哈希在实验后采集，压力场景选择器是在两次执行之间添加，不冒称两次执行使用字节级相同脚本；核心压缩规则没有按真实结果调参。

```powershell
$env:PYTHONUTF8='1'
# 先本地校准：真实 MCP/PG，只使用本地摘要替身，0 次付费模型请求
uv run --locked --offline python scripts/benchmark_context_live.py --output artifacts/deepseek/my-calibration.json
# 显式 --live 消耗 API 额度；文件必须在 artifacts/ 内且尚不存在
uv run --locked --offline python scripts/benchmark_context_live.py --live --output artifacts/deepseek/my-live-ab.json
uv run --locked --offline python scripts/benchmark_context_live.py --live --only-oversized --output artifacts/deepseek/my-live-oversized.json
```

主要实验父预算 20 次调用/100,000 tokens；压力补测独立预算 2 次/32,000 tokens。**本轮实际主要实验 18 次/67,021 tokens + 补测 2 次/8,283 tokens**，合计满足事先声明的 20 次/100,000 tokens。以后重跑会产生新调用；两个命令的独立最坏预算合计不是全局持久预算，没有实现 P5B 恢复账本。

完整机器记录只含用量/哈希/状态/聚合指标，见 [实际记录](research/p5a-deepseek-context-ab.json)；本地源文件为忽略的 artifacts/deepseek/context-live-ab-01.json 和 context-live-oversized-01.json。模型原文、完整工具正文和凭据不进入公开记录。

## 本轮回归

- `pytest tests/test_context_benchmark.py -q --tb=short -p no:cacheprovider`：**5 passed in 2.37s**，使用明确的本地模型/数据库替身，覆盖 L1/L2/L3/L4 配对一致性、用量采集及篡改摘要失败；不是额外真实 API 调用。
- `DATAPILOT_RUN_DB_TESTS=1`、`DATAPILOT_RUN_LIVE_TESTS=0`，`uv run --locked --offline pytest -q --tb=short -p no:cacheprovider --basetemp=artifacts/deepseek/context-regression --junitxml=artifacts/deepseek/context-regression.xml`：**388 passed, 1 skipped in 100.81s**，真实 PostgreSQL/MCP 回归通过。此处 live skip 是主动关闭，避免重复付费；此前独立的正式 Live pytest 已通过，见 [DeepSeek 接入记录](deepseek-transport.md)。
- `ruff check .`、`ruff format --check .`、`git -c core.safecrlf=false diff --check` 均实际通过。

本轮仅增加实验脚本、5 个本地测试和实测文档/机器记录；不修改数据库、迁移、生产压缩策略或开关，不自动提交 Git。
