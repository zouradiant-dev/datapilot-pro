# ADR-015：Chat-first 会话是交互索引，不是执行权限

状态：已实现；最终验收记录见 [Chat-first 交付](../chat-first-ui.md)。仅可信本地单用户。

## 决策

复用 P6C HTTP API、Web 身份、Outbox 和原 P5B Durable Run。新增 Alembic 0007，只追加 `execution.web_conversations` 与 `execution.web_messages`。前者保存 owner、创建幂等键、TTL；后者保存有界用户问题、附件引用、宿主生成的候选请求及可空 Run 引用、请求/hash 和顺序。没有第二套执行状态、账本或恢复引擎。

每 owner 最多 30 个未过期会话，每会话 200 条消息；列表/历史分页最多 30/20 项。会话 TTL 沿用宿主 TTL，不因读取延长。过期拒绝，P6C.1 不自动删除。Web 角色只获新表 SELECT/INSERT 与 messages.run_id 的 UPDATE，不获 DELETE/DDL。消息正文/hash 追加后不可由 API 修改；run_id 是唯一可填充字段。历史迁移不改。

创建会话、追加消息在现有 Web owner advisory lock 下去重。候选的 MCP/网络校验在锁外进行，提交时在短事务中重新检查会话、请求 hash 和唯一键；不持有 owner 锁等待外部 I/O。候选请求确定后，显式“提交审批”才创建 Run；同一 message 固定创建键，在原 command 事务内写入 Run 关联，丢失响应/并发/重启只返回原 Run。会话表不外键关联执行表：执行 TTL 与会话 TTL 独立，历史索引不能阻止已有保留流程；缺失/过期 Run 必须不可用，不能重建替代 Run。

有限规则解析只识别已支持 SaaS 指标及显式日期/月窗口；相对月份使用宿主 Asia/Shanghai 日期并显示绝对窗口。无年份月份要求补充年份；追问可引用此前已绑定 Run 的年份、指标和 Dataset 作为候选。比较只形成两个经 P3 验证的窗口，展示并列事实，不自行计算环比或趋势。多个 Dataset/指标版本、MRR、未知目标、缺映射或不明确窗口须澄清，不能由模型批准。

历史消息、摘要、客户端 selection 不是 scope。生成候选和启动时都读取当前授权；启动重新走原 task_payload/MCP/Manifest 检查。历史读取逐项校验 owner/TTL/hash/授权/版本及 Run 可见性，失效项只返回脱敏不可用占位。历史列表不返回消息内容。消息仅允许用户文本/上传引用，客户端不能追加 assistant、verdict、授权或审批状态。

审批仍调用原 tasks/{id}/approve，原 Journal 是权威；聊天入口强制 require_review。返回修改保留冻结 Run，必须先取消或明确查看旧 Run，再提出新请求，不修改 Manifest。未知调用仍 RECOVERY_UNCERTAIN，禁止自动恢复或用新 Run 隐藏。

报告继续从原 ReportView 读取，精确 Decimal 与 P3 引用不改。UI 只有 HTTP；只读轮询最多 12 次/次会话，不能调用执行入口。无新增模型意图调用；默认 Fake 标识清楚，无付费实验。

## 边界

不实现完整自然语言理解、生产多租户、长期记忆、自动清理、主动 Agent 或新 Runtime。会话用户文本是私密本地元数据，不进入公开 Trace；不存原始业务行、文档正文、SQL、Prompt 或 Checkpoint。未知语义宁可澄清。已有管理页面继续提供完整映射/指标审阅入口。
