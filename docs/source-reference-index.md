# 框架源码参考索引

核查日期：2026-10-21。以下链接固定到实际读取的提交，不指向漂移的 main。行号是定位入口，并不表示对整个仓库作了安全审计。

## 1. 快照与本地基线

| 仓库 | 引用 | 实际提交 |
|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | `1.2.16` | `41c9c22fdc83d68a2859d0c9a2b627c8615a792f` |
| [Mini Claude Code](https://github.com/Windy3f3f3f3f/claude-code-from-scratch) | 读取时 `main` | `0b452360866433fde0dc77cd37ada9d303546592` |

源码位于被 Git 忽略的 `.cache/framework-research-20261021/`，不作为生产依赖、不提交上游文件。机器可读证据见 [source-manifest.json](research/source-manifest.json)，其中记录版本、许可证和 7 个已安装文件与 tag 的规范化哈希比对。只规范化 CRLF/CR 为 LF，不改变其他字节。

重取源码时应先确认 HEAD 与表中 SHA 一致，再使用这些行号。不要执行教学仓库中的启动脚本、Hook、Shell 或自动加载项目配置来“验证”架构。

## 2. LangGraph 官方实现

| 机制 | 实际位置与入口 | 对本项目的意义 |
|---|---|---|
| StateGraph / State Schema | [graph/state.py:131](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/graph/state.py#L131) | 节点 State→PartialState、channel/reducer、输入输出与 context_schema |
| 依赖边/条件路由 | [add_edge:928](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/graph/state.py#L928)、[add_conditional_edges:982](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/graph/state.py#L982) | 由业务 DAG 生成就绪任务，复用图的路由执行 |
| compile / 子图 checkpointer | [state.py:1177](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/graph/state.py#L1177) | None 继承父配置、False 禁用等语义；编译阶段注入持久化 |
| Send | [types.py:738](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/types.py#L738) | 使用独立 arg 派发任务，避免把整个父 State 送给 Worker |
| Command / PARENT | [types.py:833](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/types.py#L833) | update/goto/resume；明确跨子图出口 |
| interrupt | [types.py:903](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/types.py#L903) | 暂停与入口重放；不是身份认证/审批服务 |
| Pregel 执行模型 | [pregel/main.py:460](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/pregel/main.py#L460) | Plan/Execution/Update，同轮状态不可见性 |
| 写入与恢复 | [runner.commit:575](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/pregel/_runner.py#L575)、[loop.put_writes:461](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/pregel/_loop.py#L461) | 区分成功写入、错误和中断，研究 pending writes |
| 重试 | [RetryPolicy:427](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/types.py#L427)、[arun_with_retry:685](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/pregel/_retry.py#L685) | 按异常类型配置；不与 SQL 语义修复混为一谈 |
| reducer channel | [channels/binop.py:66](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/channels/binop.py#L66) | 并行写入必须有确定合并语义 |
| Checkpoint 契约 | [Checkpoint:93](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint/langgraph/checkpoint/base/__init__.py#L93)、[BaseCheckpointSaver:199](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint/langgraph/checkpoint/base/__init__.py#L199) | 检查点与任务写入接口；不替代应用预算账本 |
| 内存 Saver | [get_tuple:239](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint/langgraph/checkpoint/memory/__init__.py#L239)、[put_writes:476](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint/langgraph/checkpoint/memory/__init__.py#L476) | 本轮离线探针使用；仅单进程 |
| Store | [BaseStore:708](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint/langgraph/store/base/__init__.py#L708) | Memory 命名空间接口；未验证生产实现 |
| PostgreSQL Saver | [aio.py:70](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py#L70)、[setup:95](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py#L95)、[依赖](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/checkpoint-postgres/pyproject.toml) | 3.2.0、专用 psycopg 配置、自带迁移；未安装/执行 |

相关上游测试只核查了位置与用例，**没有运行上游测试集**：

| 关注点 | 源码参考 |
|---|---|
| pending writes 恢复 | [test_pending_writes_resume:1807](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/tests/test_pregel_async.py#L1807) |
| Send 恢复去重 | [test_send_dedupe_on_resume:2530](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/tests/test_pregel_async.py#L2530) |
| 并发限制 | [test_max_concurrency:3492](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/tests/test_pregel_async.py#L3492) |
| 子图检查点 | [test_subgraph_checkpoint_true:4971](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/tests/test_pregel_async.py#L4971) |
| 父图 Command | [test_parent_command:6065](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/tests/test_pregel_async.py#L6065) |

## 3. Mini Claude Code Python 实现

| 主题 | 实际位置与入口 | 阅读结论 |
|---|---|---|
| Agent 初始化 | [agent.py:181](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L181) | 模型/工具/权限/可选预算；`custom_tools or tool_definitions` 需注意空列表语义 |
| Agent Loop | [chat:439](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L439)、[OpenAI Loop:1711](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1711)、[Anthropic Loop:1474](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1474) | 流式模型→工具→反馈；含读工具分组并发/提前启动路径 |
| Tool Registry | [tools.py:32](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/tools.py#L32)、[execute_tool:670](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/tools.py#L670)、[Agent dispatcher:1196](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1196) | 定义、激活、执行是不同环节，不能将 Schema 隐藏当执行授权 |
| Subagent Fork-Return | [subagent.py:123](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/subagent.py#L123)、[创建/返回:1371](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1371) | 新建 Agent，独立任务，最终文本与 Token 回传；无持久任务 DAG |
| Context Compaction | [触发:957](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L957)、[OpenAI 摘要:995](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L995)、[分层压缩:1024](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1024)、[大结果落盘:1168](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1168) | 限长、陈旧替换、微压缩、摘要；需为经营证据加可追溯引用 |
| Memory | [分类:24](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/memory.py#L24)、[选择:235](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/memory.py#L235)、[预取:301](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/memory.py#L301) | 文件元数据清单 + LLM 选择，非向量检索 |
| Permission | [规则/模式:589](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/tools.py#L589)、[子模式:914](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L914) | deny 优先，子 Agent 在多个父模式下使用 bypassPermissions；用户允许复用，执行权限仍由外层 MCP 强制 |
| Budget | [成本/检查:516](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L516)、[工具轮预算检查:1769](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L1769)、[重试:88](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L88) | 可选上限、响应后计数、固定倍率，需改为共享预留和统一重试 |
| Memory 辅助模型调用 | [side-query:371](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L371) | 核查辅助调用是否也计入总预算，不能只统计主 Loop |
| MCP | [mcp_client.py:38](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/mcp_client.py#L38)、[握手:93](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/mcp_client.py#L93) | 自写协议、环境继承与动态命令加载；不替换当前官方 SDK |
| Session | [session.py:16](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/session.py#L16)、[Agent 自动保存:939](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/agent.py#L939) | JSON 保存消息/会话元信息，不等于检查点和预算事务 |
| Autonomy / Goal | [autonomy.py:78](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/autonomy.py#L78)、[循环上限:112](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/autonomy.py#L112) | 本轮 P0 补读：解析目标判断结果、非法/矛盾结果失败关闭、有限循环；LLM 判断不替代业务 Verifier |
| Autonomy / Permission classifier | [投影:394](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/autonomy.py#L394)、[判定解析:451](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/python/mini_claude/autonomy.py#L451) | 仅参考不可信输入隔离和解析失败关闭机制，不把分类器当 SQL/DB 授权根 |

只查看了与本任务有关的实现路径，未全面核查 Mini 的 Scheduler、Skills、插件、TUI 和所有供应商分支。autonomy.py 中关于私有实现和提示词来源的注释是上游自述，未作为已验证事实；本轮只读控制逻辑、未运行其分类器/Loop，也未复制代码或提示词。用户允许将现有实现纳入复用，不把来源核验作为当前规划阻塞；未来实际复用保留附带许可证/版权。README 的功能完成度数字没有作为已验证事实采纳。

## 4. DataPilot 对应改造位置

| 当前文件 | 当前行为 | 后续研究落点 |
|---|---|---|
| `src/datapilot/graph.py` | 固定 SQL 路由、review、answer，无 checkpointer | 任务 DAG、Send、Worker 子图、异常归属、恢复 |
| `src/datapilot/agents/sql.py` | Schema 感知、SQL 生成、最多一次修复 | 拆分可恢复节点，保留确定性安全拒绝 |
| `src/datapilot/state.py` / `contracts.py` | 单 SQLTask/SQLAgentResult | 版本化任务、引用和并发 reducer |
| `src/datapilot/harness/budget.py` | 单运行内存预留与结算 | 并发/持久化账本，不把实例放进 State |
| `src/datapilot/runtime/mcp_client.py` / `mcp_server.py` | SDK、固定工具、隔离环境、超时、Reader | 按 Worker 能力与可信身份扩展检索/计算工具 |
| `src/datapilot/harness/verification.py` | 任务结果/终态校验 | 指标复算、证据引用与报告事实验证 |

以上改造均未在本轮实施。完整融合设计见 [研究主文档](framework-research.md)。
