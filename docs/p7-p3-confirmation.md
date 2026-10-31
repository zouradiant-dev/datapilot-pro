# Gate 2B：P3 精确批量确认清单

**2026-10-25 当前状态**：负责人已按原清单 SHA 明确批准 A/B 32 项，并通过原 Registry 追加登记，版本/Hash 匹配；C 与不存在版本仍未登记。下面保留批准前快照，不再要求重复审批。随后授权的 [零值序列化最小修复](p7-numeric-serialization-fix.md) 和最终适用回归通过，`ready_for_live_authorization=true`；没有 DeepSeek Live 授权。

## 批准前快照

本记录只提出待批准的业务定义，不登记 Registry，不填写 `reviewed=True`。项目负责人的 Gold 审核流程决定已生效；该决定不等于 P3 Semantic / Metric 定义确认。

35 条 P3 未确认任务按 Dataset ID/version、Semantic version、Metric ID/version 和定义 SHA 去重后，有 34 个定义条目：13 个 Semantic、21 个 Metric。

| 分组 | 条目数 | 本次处理 |
|---|---:|---|
| A：定义完整、等待业务口径批准 | 26 | 纳入精确批量确认请求 |
| B：定义完整的负例政策 | 6 | 纳入请求，但只确认所列限制，不增加指标能力 |
| C：故意未确认的单位及其依赖 | 2 | 排除；维持未登记，供 `bh2-060` 负例使用 |

A+B 合计 **32 个定义（12 个 Semantic、20 个 Metric）**，覆盖 34 条任务。C 对应 `precision` Dataset 的 Semantic v2（`amount_storage=null`）及依赖的收入 Metric v2，不能由文档或模型补全金额单位。`bh2-019` 的 Metric v999999、`bh2-048` 的 Dataset v999999 也不会被创建，仍是预检阻断负例。

完整的逐项身份、版本、source hash、definition hash、字段映射、日期/单位/过滤口径和受影响 Case 列于本机私有清单：

- [可读清单](../artifacts/p7/gate2b-v2/private/p3-confirmation-request.md)
- [精确 JSON 清单](../artifacts/p7/gate2b-v2/private/p3-confirmation-request.json)
- [公开计数及清单哈希](research/p7-p3-confirmation-summary.json)

JSON 文件字节 SHA256：`76c1e8d6ca861770e6e5c32cc9c67b7a1a2a0d1bdbebc17ae25796929ecf29c0`。

B 的含义必须保持：`history_complete=false` 不改为完整历史；重复使用事件仍保留，确认的是预期事件粒度而非数据已经唯一；USD 指标仍不支持换汇/数值发布；MRR 仍没有可执行配方，不补造合同条件。

可一次批准上述 SHA 对应 JSON 中的 A/B 条目，明确排除全部 C 条目。批准后才能通过原 `confirm_semantics` / `confirm_metric` 接口，按版本及依赖顺序追加登记，再重跑只读准入。这个清单本身和工程测试均不构成批准。若某项被拒绝，保持其阻断，不能删掉该评测任务或改 Gold。

在批准之前，Registry 只读检查显示该 Holdout 的 Semantic / Metric 登记均为 0。本轮未执行任何 Holdout 定义确认；公开 Toy 的独立样例定义不属于该清单。

当前 `ready_for_live_authorization=false`：真正待办是这 32 个精确定义的项目负责人决定及后续原 Registry 登记/准入复核。`bh2-060` 的已分类缺失并非需要“修好”的阻断。真实业务 Live 仍需另行明确授权；旧意图实验授权不延用。
