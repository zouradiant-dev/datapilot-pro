# ADR-012：P3/P4 显式证据桥接与 P6B 报告

用户授权仅 P6B；不修改 P3 已发布规则、历史迁移或 LangGraph 源码。复用当前 Coordinator/Saver/Worker/Journaling，禁止第二个调度器。

ReportScope 是可信宿主契约，不是 Planner JSON。模型只选择其中已确认的目标；SQL 指标执行固定 P3 配方，持久 Evidence 与 Verification 分开保存。新 MetricBridge 是这些持久对象的受核验投影，不是新的 verified 标志或模型自评。P4 五层编排检查不能替代 P3 六层业务规则。

新增只读、DatasetScope 受限的 Verification 查询与原 Evidence 查询对称，不新增 DB grants 或写 MCP 工具。Report 只公开核验过的数值；文档需原 scope/index/source/chunk/hash 和目标相关性，且与请求指标对应。引用文本只作为引述背景，不生成因果事实。

持久化沿用 execution 工件与原 Journal。已提交操作幂等重放；P3 追加与执行日志之间不存在跨库全局事务，未知结果必须 uncertain 阻断，不能重新生成新证据假定未执行。原执行状态保持兼容，business_completion 与未来复用前提采用显式版本化可选契约，不实现 P11 引擎。
