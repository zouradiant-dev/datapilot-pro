# P7 Final 50 v6 — 064 数值差异诊断

原冻结任务要求统计 2032 年 3 月事件使用量。独立 Gold 为 213 events。实际启动的冻结指标为 Dataset v1、Semantic v1、usage v1。该 Registry 定义绑定了 feature=export_batch，P3 发布 124 events，六层验证均通过。

对 Source SHA256 为 2230a6b5003a4b300709b822b3579d2e2847a65d2327bbf4ad9b0e82bd080a2c 的 master.xlsx 独立复算。该哈希与 Collector 所记录的 MetricContext 一致。usage_events 工作表在 [2032-03-01, 2032-04-01) 有 9 个唯一 event_id。

| 口径 | Decimal SUM(event_count) |
|---|---:|
| export_batch | 124 |
| webhook_delivery | 89 |
| 全部 feature | 213 |

SQL 配方与 P3 独立复算均按已确认定义应用 feature 条件。证据支持的是按该指标定义计算的 124。冻结任务意图和 Gold 采用全功能范围，所绑定的指标却只有 export_batch。根因是任务与指标定义的口径不匹配，未发现数值运算或六层验证错误。

原分数及安全停止保留。本次只读复算未改 Gold、Registry、代码或 Run，付费调用为 0。后续应在派发前核查剩余任务的业务口径与已确认指标是否匹配。若要单独评价修订后的 064，需要新的明确任务身份与已确认的全功能指标定义，保留原失败。
