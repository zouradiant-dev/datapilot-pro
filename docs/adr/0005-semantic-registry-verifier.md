# ADR-005：P3 封闭指标配方与独立证据验证

日期：2026-10-21。状态：已实现于 D6–D8 / P3；不授权继续 P4。

## 决策

1. 不引入通用表达式语言、模型可写指标或新调度框架。`saas-1` 映射和 `saas_metrics_v1` 指标政策由可信操作者分别确认；与源文件/数据集版本及 hash 绑定。用户可覆写字段、paid/churn 分类、单位、覆盖范围和使用特征；固定配方公式变更需新政策版本与验收。
2. 新 0003 Alembic 冻结快照增加 semantic_versions、metric_versions、evidence、verification_runs。前两者保存完整定义 JSON 和定义 hash；后两者保存完整原始工件/六层结果 JSON 和 body hash，关系键绑定 Dataset/Metric/Semantic 版本。历史 0001/0002 不改。
3. 新 `datapilot_registry` 是元数据专用 SELECT/INSERT 身份，与 admin/owner/seed/ingest/reader/upload_reader 隔离。固定表 Owner 仍为 datapilot_owner。没有业务 Schema USAGE、DDL、角色继承、UPDATE/DELETE/TRUNCATE；确认和证据写入不注册为 MCP 工具。
4. Worker 的 MetricRequest 显式指定源/语义/指标版本。`metric_session` 从可信宿主注入有版本的 DatasetScope，只给上传 Reader DSN；模型提供的 Dataset ID/version 不是授权。MCP 新增三个只读能力：get_metric_context、recompute_metric、get_evidence。上下文只投影必须实体/列，不含原始行和其他表。
5. SQL 安全链完全保留。语义层采用候选与封闭配方规范 AST 相等的保守规则，收入/使用量不接受额外 JOIN；客户净流失配方中的自连接用 DISTINCT 控制粒度。没有为 EXISTS/CASE 内部节点扩大原函数白名单。
6. 独立验证从原始必需列投影重新计算，而非重复执行同一聚合 SQL 或比较 LLM 自评。复算快照 REPEATABLE READ + READ ONLY、分页受控，20,000 行/256 页及协作时限，超限明确不能验证；Decimal 计算无浮点中间值。不同快照或来源异常不能被声明正确。
7. Evidence 是 raw，不等于 verified。宿主先追加工件，经 scoped MCP 读回再检验引用，最后追加 Verification。六层全过才显示数字；结构化 claims 校验完整目标、真实引用、单位/数值与请求版本后确定性渲染。因果请求/claim 没有因果识别证据就拒绝或说明不可回答。
8. MRR 可登记/追踪但当前没有可执行配方；账单求和不得冒充 MRR。原 Seed 的最终状态/套餐期间不证明合同历史，不能自动给历史流失。首版 CNY/DATE；其他币种、退款、复杂合同和政策变化明确留给后续定义及测试。

## 权衡与后果

保守 AST 相等会拒绝部分等价 SQL；这是可复核首版的明确取舍，不能宣称通用 SQL 语义证明。独立 Python 原始行扫描有资源上限，大表先明确拒答，后续优化必须保留独立验证性质。用户确认是本地操作标记而非身份认证；Registry/Owner/ingest 仍受可信宿主边界限制。Hash 证明工件一致性，不证明数据本身真实或业务完整。无新依赖、无 LangGraph 内核或 site-packages 修改。

完整公式、DTO、权限、运行示例和限制见 [P3 说明](../semantic-metrics.md)。Domain Pack/Source Connector 的后续接口继续依 ADR-004，未实现干洗店/未知 POS Connector。
