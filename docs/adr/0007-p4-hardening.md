# ADR-007：P4.1 工具生命周期、宿主完成判定与 L0 上下文保护

日期：2026-10-21。基线：`1f0decd02ce9eed989c52486797bdba88ff11f46`。范围仅 P4.1；不改变官方 LangGraph、依赖或数据库结构。

## 决策与安全顺序

1. 不新增 Scheduler、Registry、Loop 或 Budget。原 `ToolRegistry.invoke` 收敛为受控入口：已知工具与输入契约 → 子能力/宿主已绑定工具句柄 → 取消/原子尝试预留 → 有界调用 → 输出契约 → 完整 Artifact → L0 模型视图 → 脱敏 Trace。未知工具直接拒绝。SQL 的编译修复仍只有 Loop 负责，暂时性工具故障只由有界外层 Replan 处理；坏输出视为验证错误，不能重规划绕过。
2. 没有用户 Hook、Skill 脚本、动态可执行插件或 before/after 授权覆盖机制。共享前后置流程是可信宿主代码，不允许修改工具参数或把拒绝改为成功。取消/超时及 SQL 尝试限制也覆盖 Schema bootstrap；模型预算仍复用 Gateway/Ledger，工具没有第二套模型账本。
3. `context.py` 只承担计量和 L0 视图，不实现通用 ContextManager。Gateway 在 reserve 前记录消息数、字符/工具 Schema/UTF-8 字节、输入 Token 保守估计（字节 +128）、输出预留、工具结果体积；字符或 Token 上限超出时 CONTEXT_LIMIT，零模型调用。估计不是 tokenizer 实测或费用承诺。
4. QueryResult 原先就不把行发给 SQL 模型；继续只反馈行数/列摘要/截断与引用。RAG 全文通过严格契约/hash 后先保存完整工件，再反馈每篇至多 256 字符及省略长度、来源/版本/hash；整份视图默认最多 4096 字符，必要时只留计数和引用。Schema 保存完整 schema 工件并原样提供，绝不裁剪安全约束/Schema。schema 工件不能冒充 query 结果或成为最终工具引用。
5. 延后可选 L1/L2：本阶段不改既有消息历史或删除重复 tool 消息，以免提前确定 P5A 权威状态/历史压缩与 P5B 恢复存储设计。保留完整 AIMessage/ToolMessage/tool_call_id，L0 视图只改变工具反馈的内容，不改变对应关系。存储仍是同 Run 内存，不宣称跨重启保存。
6. `CompletionDecision` 独立于模型 complete 与执行 status。必需任务均为成功终态、五层记录契约及身份有效、Finish 实际引用重新验证且无截断，才可 completed；缺结果/验证/截断/丢弃原任务为 incomplete；拒绝/失败/不可回答/错误引用为 blocked。重规划不能删除初始必需任务来抹去原要求。Goal scope 明确为 required_task_contracts，不声称验证任意自然语言覆盖。
7. **P3/P4 不建立假桥接。** 当前 DAG 不能消费 persisted P3 Evidence/Verification，所有已识别业务指标请求一律 blocked/P3_VERIFIED_EVIDENCE_REQUIRED，保留原查询供受限查看，但不发布 verified metric。独立 P3 路径继续有效。关键词保护是补充，不是完整语义分类器；未来 P6B 必须从可信结构化目标/MetricRequest 校验实际版本和六层证据，而非接受模型布尔值。
8. 完成判定不自动启动新任务，不无限续跑、不改变权限。原执行 `status` 为兼容保留，调用方须同时检查 `completion`；输出 Markdown 明示受限状态。真实 RAG、报告桥接、Memory/Saver 与多租户均未实现。

## 验证

针对受控入口、尝试竞争、坏输出/哈希、批量拒绝/剩余未执行反馈、Token 维度、工件先存、完成判定及引用遗漏设计反例；关键引用检查另做一次变异 smoke，验证测试真实变红后还原。实际命令/结果见 [交付](../p4-hardening.md)。
