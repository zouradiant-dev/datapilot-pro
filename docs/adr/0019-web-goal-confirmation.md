# ADR-019：Goal v4接入已有Chat与审批

2026-10-31；Phase2C.6。实现前只读审计所得方案，不表示已验收。

| 能力 | 实际已有 | 缺口及最小增量 |
|---|---|---|
| Conversation/Message | 真实PG、owner/TTL、不可变payload/hash、幂等、分页 | 复用，不新建会话或恢复表 |
| Pending Goal | ChatDraft存CreateTask和授权摘要 | 保存经MCP核对的完整有限合同快照与审阅投影 |
| 用户确认 | launch.confirmed仅表示提交，Journal审批表示执行许可 | RAG要求合同版本/Hash前置条件及明确的完整目标、有限范围/已解决前提确认 |
| Attestation | Host SDK confirm_finite_scope；Goal v4进入Manifest/Receipt | 只由受认证API签发，ref指向不可变确认事件Message |
| Durable | 原Outbox、Worker、Journal/Checkpoint、恢复 | 原调用链不变；Host每次重新核对确认事件有效性与原配置 |
| 修改/追问 | 追加新消息、取消旧Run | 显式supersedes关联使旧合同失效；追问从不继承旧Attestation |
| 报告/UI | HTTP-only聊天、审批、引用/数值/状态 | 增加完整合同卡和确认历史；Scope确认与事实验证、执行审批分开 |

## 持久化与原子性

复用execution.web_messages的不可变JSONB记录：原消息存待确认合同，确认/拒绝为有界追加事件，修改为带supersedes的新消息。合同ID是原Message ID，版本是现有会话sequence。有效状态由事件及新版本关系推导；不建新Scheduler/确认服务/通用状态机，也不增加DDL或消息UPDATE权限。

同一owner已有advisory锁串行化事件、原Outbox创建和Message.run_id关联；网络/MCP均在事务外。确认事务重新核对Message与最新状态；重试读取同一事件和同一Run。事件消耗原200消息配额，不能静默清理历史。Source/定义/合同过期或Hash变化失败关闭。

## 真实确认与有限目标

客户端只提交对服务器版本/Hash的乐观前置条件，以及用户显式的审阅决定；不接受confirmation_ref、Attestation、Goal版本或eligible。原问题完整保留，卡片展示有限目标、授权Dataset/指标/窗口、Source版本、Required Facts、预算和不保证事项。

没有自动语言等价证明。用户必须确认合同覆盖完整原目标且无未解决前提；不能勾选时应拒绝或修改原问题产生新版本。既有unsupported/穷尽/快照守卫继续拒绝，不能靠确认解除；未命中的歧义仍需真实用户判断，披露该可信用户可能误判的残余风险。不要从LLM或Gold填充确认。

Source选择只是候选，宿主经原MCP核对后生成CitationPolicy。必需来源只能从授权集合缩小；用户描述事实不是引述证明，事实仍须原Verifier核验。SQL-only复用Registry与原执行审批，不增加范围审批。直接/tasks创建RAG不允许绕过聊天合同；旧未绑定记录不自动升级。

## 身份、撤回与恢复

确认事件绑定owner、真实HTTP认证session哈希、Conversation/Message、合同版本/Hash、来源/定义身份、服务器时间和TTL。session哈希用于审计，既有本地单用户owner可重新认证读取/恢复，不冒称生产多租户或把Cookie当长期Dataset授权；跨Conversation或owner不能引用确认。

Host将事件ID作为confirm_finite_scope的ref，并把来源事件绑定加入原Web任务载荷。授权/恢复/Inspector入口从不可变事件重建同一Attestation，比较整个载荷；不相信报告自述。撤回或修改追加事件并调用原取消机制，保留已发出调用、unknown和预算。不可撤回已发生的外部请求，不自动重发或换Run掩盖unknown。

Goal v4、P3及Journal/Ledger不改。老v3恢复继续RECOVERY_IDENTITY；取消入口保留。默认BGE不改；可信Host可显式选择原Qwen Reader Profile（不由请求/.env/PATH选择）。本轮不新增Qwen Web摄取器，受控既有CLI摄取后授权同一确认链；不能混用模型/索引。

## 验收与限制

采用新隔离PG、公开合成来源、真实Embedding/MCP和脚本决策。分开报告HTTP、Streamlit AppTest与真实浏览器；不调用付费模型、不续跑已停止实验、不提交推送。Web功能未验收前不宣称产品已接入。
