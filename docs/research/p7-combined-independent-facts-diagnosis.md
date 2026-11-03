# SQL+RAG 单例：RAG insufficient 诊断与最小修复

日期：2026-11-03。对象 Run `304ca32e-70ff-40af-bea2-d7b54094a3d9`。本轮 **0 次付费调用**，未创建 Permit，未创建新 Run，未 Commit/Push。

## 1. 结论先行

**根因已确认：目标耦合，不是“召回为空”。**

RAG worker 实际检索到并读取了退款政策文档；随后它又按收入指标搜索，得到 0 个文档，最终主动提交了 `insufficient`。文档 artifact 存在，`relevant_chunk_ids=[]` 只是 `tools.py` 对非 complete outcome 的投影，不能反推检索为空。

修复方向：把**独立文档事实**与指标目标显式解耦；不删除指标关联，不强制 complete，不放宽事实/引用/citation 守卫。

## 2. 原始失败链

系统消息中的 `HOST_GOAL_CONTRACT` 和父 Run 的 `DocumentGoal` 都是：

- `DocumentGoal.question`：完整组合问题：“计算…收入（CNY），并依据…退款政策原文说明企业版退款审核时限；不要把文档当作收入或因果证明。”
- `DocumentGoal.metric_goals`：`["metric_1"]`
- `purpose`：`facts`
- `required_facts.fact_1`：带宿主机 `citation`、`quotation`、`confirmation_ref`
- `business_conclusions_verified=false`

RAG worker 实际消息顺序：

1. `search_documents(完整组合问题)` → 1 个文档 artifact `da32a8f7…`，包含退款政策全文。
2. `read_context(document_id=55469a84…)` → 完整授权原文，含“企业版…7 个工作日…”。
3. `search_documents("2026年9月 已支付账单 收入 金额 CNY 账单明细")` → **0 个文档**。
4. `submit_rag_result(outcome="insufficient", artifact_ids=["da32a8f7…"])`。

没有更早的 `complete` 提交，也没有 tool 拒绝；宿主接收了 `insufficient` 收据。最终 Report 的 `matching_document_or_metric_evidence_missing` 是**后续结果**，不能倒推为模型此前决策的原因。

## 3. 已确认的耦合点

1. **DocumentGoal.question 使用完整组合问题**，RAG worker 被要求同时满足 SQL 收入目标与退款事实。
2. **DocumentGoal.metric_goals=["metric_1"]**，让文档事实被当作指标关联证据。
3. **Report `metric_topics_match`** 还会要求退款文档包含收入指标 topic；即使 RAG Worker 提交 complete，旧绑定也会被 Report 拒绝。

因此这是契约绑定问题，不只是模型行为。模型行为是在错误输入下作出的合理 insufficient 判断。

## 4. 最小修复

在没有清空 `metric_goals`、没有强制 complete 的前提下：

- 新增显式 `document_facts_independent` / `DocumentGoal.independent_facts`；
- UI 提供“文档事实独立于指标（不要求文档证明指标）”确认项；
- 仅当该显式标志为 true：
  - `DocumentGoal.question` 改为“请依据授权文档核验以下事实：<Required Facts>”；
  - 保留 overall `question`、指标请求和 `metric_goals` 关联；
  - Report 跳过 `metric_topics_match`，但仍要求 required source、Required Fact citation/quotation、版本/hash 和业务完成条件；
- 无该标志时，保留原有 metric 关联与因果/事实验证守卫；
- 不修改历史 Goal/Result；旧合同仍是 full question + metric coupling。

修改文件（工作区未提交）：

- `src/datapilot/web/chat_contracts.py`
- `src/datapilot/web/contracts.py`
- `src/datapilot/web/chat.py`
- `src/datapilot/web/goal_confirmation.py`
- `src/datapilot/web/service.py`
- `src/datapilot/web/ui_components.py`
- `src/datapilot/web/ui_chat.py`
- `src/datapilot/reporting/contracts.py`
- `src/datapilot/reporting/service.py`
- 相关测试

同轮保留了此前 single-case AdmissionGate 兼容修改，未重开架构。

## 5. 反例与验证

- 旧绑定反例：Run `304…` 的完整 question + metric_goals 绑定，RAG 提交 insufficient；旧结果为 unavailable/partial，未改。
- 新契约反例：`test_independent_document_facts_are_scoped_apart_from_metric` 验证：
  - overall question 保持完整；
  - metrics 保持；
  - document question 变为 fact-scoped；
  - `metric_goals` 关联保留；
  - `independent_facts=true`；
  - quotation 仍只是输入。
- 真实隔离 PG/MCP：Admission 各 **15 passed**；独立合同各 **1 passed**。
Fake Worker 完整路径（候选→Goal→审批→Worker→P3/文档→Report）：**3.11 1 passed / 3.13 1 passed**，SQL verified、文档 citation 进入报告、business completed。
缺引述负例：**3.11 1 passed / 3.13 1 passed**；篡改/因果负例：**3.11 22 passed / 3.13 24 passed**。
- 3.13 相关 Web 单元 **14 passed**。
- Ruff / format / diff check 通过。
- 未运行完整本地 pytest；新源码完整 CI **NOT_RUN**。

新源码 Freeze（不含 Permit，不可执行）：

- `p7-combined-repair-independent-fix-2fc42e0ef101`
- SHA `2fc42e0ef10106b64ac646bd29ff92f2d5b60964723b610d9985fe48bc030f82`
- 记录：`artifacts/p7/combined-repair-single-v1/private/freeze-independent-fix.json`

## 6. 旧结果与历史

- Run `304ca32e…` 仍为 **unavailable / business partial**；未重跑。
- 旧 `p7-fresh-web-smoke-v1` 的 1/3、8 次调用 / 12,066 Token、STOP/Permit/Result 均不变。
- 未修改历史 Goal、admission 或 Report。
- 无新付费调用、无新 Permit、无新 Run。

## 7. 是否具备申请一次新 combined Live 的条件

**当前不具备直接执行条件；具备“申请一次新验证”的源码候选条件。**

必须同时满足：

1. 这个工作区修复通过新的完整 CI（当前 **NOT_RUN**；CI #31 只覆盖基线 `4cf867`）；
2. 新源码建立新 Freeze 和新 Permit，不能复用旧 Permit；
3. 新 combined Goal 在可信确认页面明确选择 `document_facts_independent=true`，并显示 fact-scoped document question；
4. required source/citation/quotation、指标 P3、预算和 180/1800 边界保持原规则；
5. 新授权明确只创建一个 combined Run，失败不重跑。

本轮不创建 Permit、不调用 DeepSeek、不执行新 Run，停止。
