# 求职展示：DataPilot Pro 与 AI Agent 开发岗位

这份讲解围绕一个可复现的 SQL + RAG 工程 Demo，并单列正式业务验收和远端 CI。

工程 Demo 已验收，模型决策使用 Fake／脚本，PostgreSQL、MCP、BGE、P3 和 Durable 实际执行。另一次封存的 DeepSeek Flash 48k 正式评测覆盖 60 道合成 SaaS 题，**严格分 60/60、业务分 60/60，边界各 42/42**。[工程 Demo](releases/p7-engineering-candidate-v1/frozen/p7-demo-acceptance.md) · [正式业务验收](research/p7-formal60-48k-acceptance.md)

## 1. 一句话介绍

DataPilot Pro 是一个面向 SaaS 经营分析的 **Evidence-driven AI Agent**：用户用自然语言提出经营问题，系统把它收敛为一份**经用户确认的有限合同**，由 LangGraph 双环执行（外层任务 DAG + 内层模型工具循环），所有业务数据只经 MCP 只读访问，数字由 SQL/Decimal 独立复算并绑定 P3 Evidence/Verification，文档只作为经校验的引述背景，最终报告显式区分"已完成 / 部分 / 不可用 / 被阻断"。

对 AI Agent 岗位的匹配点：

| 岗位关注点 | 本项目对应证据 |
|---|---|
| Agent 编排 | LangGraph StateGraph、Send 并发、interrupt/Command、父子图共享 Checkpoint |
| 工具使用与协议 | 真实 MCP SDK stdio、ToolRegistry、每条 tool_call 一一配对反馈、能力最小化 |
| 可信与安全 | 宿主绑定 scope、SQLGlot AST + 只读角色、模型无 DDL/文件/Shell、凭据按用途隔离 |
| 可观测与可恢复 | Journal/Ledger/Artifact、unknown-outcome 阻断重发、跨进程重启一致性 |
| 评测 | 正式 DeepSeek Flash 48k 批次分别报告严格分、业务分及边界结果，历次 STOP 和未运行项独立留档 |
| 工程交付 | 发布提交 `23c44c7` 的 Python 3.11／3.13 CI 均通过，包括真实 PostgreSQL／MCP 回归。[CI 运行](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/42354878566) |

## 2. 项目亮点（可直接写进简历/自我介绍）

1. **双环 Agent 架构**：外层 `planner → scheduler → worker → verifier → replan → finish`，内层 `decide → tools → decide` 子图；每个逻辑 Run 只编译一次图，模型只提供 Plan 数据，不能新增节点、工具或可执行表达式。
2. **"模型不能自证正确"落到代码**：P3 六层验证（安全/形状/语义/独立复算/引用/覆盖），Evidence 与 Verification 分离；任何未通过验证的数字都不能进入报告。
3. **Goal v4 可信有限范围**：把"用户到底要什么"变成宿主签发的合同 + 显式确认事件；确认、执行审批、完成判定三件事在代码与 UI 上都分开。
4. **可恢复且不重复扣费**：官方 PG Checkpoint + Journal + 原子预算账本；已提交响应复用，未知结果保守计账并阻断自动重发。
5. **真实数据边界**：SQL MCP 只有 `datapilot_reader` / `datapilot_upload_reader`，RAG MCP 只有 `rag_reader`；模型侧不存在管理员、Owner、Seed、Registry 凭据。
6. **可追溯的评测**。正式 60 题使用预注册评分，涵盖 54 个模型执行 Run 和 6 项零模型调用的宿主拒绝。旧 Gate 2B 在预算预留失败处停止，29 条 `not_run` 保留在旧批次。[评测索引](evaluation.md)
7. **可复现的工程证据**：五个 Demo Run、重启前后签名快照、撤回后 `403 GOAL_REVOKED`、unknown 不重发，均有本地工件与公开脱敏副本（见 [交付索引](releases/p7-engineering-candidate-v1/README.md)）。

## 3. 三个技术难点与解决方案

### 难点一：LLM 会"顺手"扩大权限或替用户做决定

**问题**：自然语言目标天然模糊；如果让模型同时负责"理解目标、选择数据、判断是否完成"，它可以静默缩小问题、越过未确认口径，甚至用相关性冒称因果。

**方案**（`reporting/contracts.py`、`web/goal_confirmation.py`、`orchestration/coordinator.py`）：

- ReportScope 绑定 owner、原始问题、Dataset/version、已确认 MetricRequest、文档目标与限制；`confirm_finite_scope` **只能由可信宿主显式调用**，模型、普通审批、非空检索、`unsupported=false` 都不能生成 Attestation。
- UI 要求用户分别确认"完整目标 / 有限范围 / 已解决前提"三项，再单独走 Journal 执行审批；`awaiting_review` 期间模型调用为 0。
- 未确认的目标仍可被分类为 `bounded`，但 `completion_eligible=false`，整份组合报告不能 `completed`。
- 撤回后服务端先置 `rejected`，报告读取返回 `403 GOAL_REVOKED`。

**可讲的证据**：RAG-only Run `cb6f5a65…` 在确认后创建、独立审批后执行、撤回后拒绝发布；`tests/test_web_goal_confirmation.py` 覆盖 DTO 不接受宿主证明字段、伪造确认、过期与跨会话引用。

### 难点二：让"数字"可信，而不是让模型说它可信

**问题**：LLM 生成的 SQL 可能看起来正确；同一指标的口径（paid 账单 vs MRR、客户流失 vs 订阅流失、右开区间、CNY 分）极易被悄悄改写。

**方案**（`semantics/service.py`、`semantics/recipes.py`、`semantics/recompute.py`、`harness/metric_verification.py`）：

- 只执行 `saas_metrics_v1` 封闭配方；候选 SQL 的规范 AST 必须与配方一致，保守拒绝"可能等价"的写法。
- 六层验证中的**独立复算**由 MCP 以另一条原始列投影分页读取（REPEATABLE READ / READ ONLY，20,000 行 / 256 页上限），Python 独立选队列、过滤、求和，不复用 SQL 聚合结果。
- 金额以整数分存储、Decimal 文本发布；浮点只用于图表坐标。分母为零、缺定义、覆盖范围不足都返回 `unavailable`，不发布数字。
- 报告中的每个数字绑定 Evidence/Verification ID、版本、时间窗口、单位与过滤条件。

Demo 中两条 paid/CNY 账单合计 **1432.25 CNY**，受限 MCP SQL 与独立 CSV／Decimal 复算一致，P3 六层通过。另一次正式 DeepSeek 评测的 **36/36** 个必需数值和 **36/36** 个必需引文均通过核验。[工程 Demo](releases/p7-engineering-candidate-v1/frozen/p7-demo-acceptance.md) · [正式业务验收](research/p7-formal60-48k-acceptance.md)

### 难点三：长流程失败后，既不丢状态也不重复花钱

**问题**：模型调用、工具调用、Checkpoint 提交不在同一事务；进程崩溃或超时后，"到底执行了没有"往往无法判断。天真的重试会重复扣费、重复发布或掩盖未知。

**方案**（`persistence/journal.py`、`persistence/backend.py`、`persistence/session.py`）：

- 每次外部调用先原子写入父子预算预留与 `issued` 调用，完成响应与 usage 同事务提交；恢复时按**压缩前原始输入**复用已完成响应，不重发。
- 结果未确认（超时/取消/PG 断连）标记 `uncertain`：保留最大预留、`usage_complete=false`、阻断自动恢复，要求人工对账；不假设只读请求"一定没执行"。
- 恢复由宿主重新提供身份与 scope，重查 Dataset/version、Semantic/Metric、source hash 与原 P3 verdict；摘要、Memory、Checkpoint 都不能补授权。
- Web 层只增加有界本地进程派发与 PG Outbox，不新增 Scheduler/Checkpoint；终态不能被恢复退回 `running`。

工程 Demo 重启 API 和 UI 后，五个 Run 的签名与证据一致。合成 unknown 调用使恢复接口返回 `403 WEB_RESUME`，调用与 Ledger 哈希保持一致。旧 Gate 2B 则在预算预留失败时安全停止，当时 61 次真实调用均已结算。[工程 Demo](releases/p7-engineering-candidate-v1/frozen/p7-demo-acceptance.md) · [历史 Gate 2B](p7-gate2b-live.md)

**补充难点（可简略）**：工具协议配对——每条 assistant tool_call（含拒绝、异常、取消）必须有唯一反馈，JSON 解析失败不允许退化为空参数；否则模型会在"工具没执行"的幻觉上继续规划。

## 4. 一次可信证据链的典型执行流程

以下用已验收的 **SQL+RAG 组合 Run**（`37768ae4-04e7-430a-a48e-f2ef2261c8aa`）说明典型链路。该次验收通过 HTTP 预先提交候选消息，浏览器用于确认、审批、查看报告和撤回。[原 Demo 记录](releases/p7-engineering-candidate-v1/frozen/p7-demo-acceptance.md)

1. **准备可信输入**：通过真实 HTTP 上传合成 CSV，审阅 Schema 并显式确认；受限入库生成 Dataset v1；人工确认 Semantic/Metric v1；上传 `billing-guide.md` 并用固定 BGE 建立 Corpus/IndexVersion。
2. **形成候选**：用户在对话里提出组合问题；有限意图规则生成候选，不调用模型；候选卡片展示 Dataset、指标、右开时间窗口、文档目标、预算与"不保证事项"。
3. **用户确认合同**：用户勾选完整目标、有限范围、已解决前提；服务端在 owner 锁与事务内创建 Run 并关联 Message；状态 `awaiting_review`，模型调用 0。
4. **独立执行审批**：用户点击批准，Journal 记录审批事件，进程被拉起并续跑原图。
5. **规划与执行**：Planner 只安排宿主批准的同名任务；Scheduler 用 Send 派发 SQL 与 RAG 两个就绪任务；SQL Worker 经 MCP 取数，RAG Worker 经独立 RAG MCP 检索。
6. **数字验证**：P3 六层验证——AST/授权/只读事务 → 结果形状 → 口径与版本 → 独立复算 → 证据读回与 hash → 目标覆盖；生成 Evidence `cc959e8d…` 与 Verification `1157e7ba…`。
7. **报告重建**：Report 不调用生成模型，独立重读 P3 持久引用，确认数值/单位/版本/hash/verdict 未变，再渲染 claim、Markdown 与图表；文档 chunk 校验来源、跨度、行号与授权范围，只作背景引述。
8. **结果呈现**：页面显示精确 Decimal `1432.2500000000000000 CNY`、Evidence/Verification 引用、`execution_status` 与 `business_completion`；明确不推导因果、不把它称为 MRR。
9. **事后校验**：重启 API/UI 后五项签名一致；撤回 RAG 合同后报告 403，但原 Inspector 仍可只读核验已保留工件。

这条链路同时覆盖了"确认—审批—执行—验证—发布—撤回"六个环节，是面试时最值得展开的 5 分钟故事。

## 5. SQL + RAG Demo 讲解脚本（约 8 分钟）

演示使用本地 Fake 模式和工程 Demo 的 2026 年 6 月账单与计费说明。根 README 快速开始的 300 CNY 属于另一套合成样例。[账单 CSV](../tests/fixtures/demo/engineering-v1/invoices.csv) · [计费说明](../tests/fixtures/demo/engineering-v1/billing-guide.md)

**0:00–0:40 开场**

"这是 DataPilot Pro，一个 SaaS 经营分析 Agent。它要解决的不是'生成一段像分析的文字'，而是'给出一个能被复核的经营数字，并说清楚哪些结论还不能下'。今天我用合成数据走一遍 SQL + RAG 的组合报告。"

**0:40–1:40 上传与确认**

（上传工程 Demo 的账单 CSV 与计费说明）“上传后页面展示有限的数据画像。我先确认 Schema，再确认字段映射和 `paid_invoice_revenue` 指标口径。映射和指标各有版本。”

**1:40–2:40 提问与合同**

（在聊天框输入"2026 年 6 月已支付账单收入，并结合计费说明解释"）"这不是直接把问题丢给模型。系统先形成一个候选合同：Dataset、指标、右开时间窗口、文档目标、预算和限制都在卡片上。我需要分别确认：这覆盖了我的完整目标、范围是有限的、没有未解决前提。"

**2:40–3:30 审批**

"现在状态是 awaiting_review，模型调用是 0。确认合同不代表批准执行；我单独点执行审批——这是第二个信任边界。"

**3:30–5:30 执行与证据**

"批准后 LangGraph 规划出 SQL 和 RAG 两个任务，并行执行。SQL 只走 MCP 只读会话；数字由 P3 六层验证，其中独立复算会用另一条原始列投影在 Python 里重算，不复用 SQL 的聚合结果。RAG 走独立进程，检索到的引用要核对原件 hash、行号和授权范围。"

**5:30–6:30 报告**

"报告里的 1432.25 CNY 带有 Evidence 和 Verification ID；文档引用只作为背景，不证明因果。页面同时显示执行状态和业务完成状态——这次是 completed，但如果是缺文档，会显示 partial 或 unavailable，不会把部分结果说成完整分析。"

**6:30–7:30 可靠性与撤回**

"我可以重启 API 和 UI，五个 Run 的签名完全一致；我也可以撤回这份 RAG 合同，撤回后报告返回 403，但已发生的扣费和证据不会被抹掉。如果模型调用结果未知，系统会阻断自动重发并要求人工对账。"

**7:30–8:00 收尾**

“刚才用脚本决策演示了真实的权限、证据和恢复链。另有一轮正式 DeepSeek Flash 48k 评测，54 个 Run 加 6 项零模型调用的宿主拒绝，严格分和业务分各 60/60，边界各 42/42。这个结果适用于封存的合成 SaaS 题和宿主审阅范围。”

## 6. 验收范围与待验证项

- **正式业务验收已通过**。题本由开发者合成，合同由宿主审阅，独立第三方人工语义盲审仍为 `NOT_VERIFIED)。[正式业务验收](research/p7-formal60-48k-acceptance.md)
- **演示与部署范围**为可信本地单用户、回环监听。生产认证、租户隔离和 SLA 需要独立验收。
- **可选 Qwen3** 的 CUDA、生产切换及最新 Web 确认链资源验证仍单列，默认使用 BGE 512／ONNX。
- **独立消融已暂停**，零付费对照已留档。[消融状态](research/p7-independent-ablation-preparation.md)

## 7. 可能的面试追问与回答要点

- **"为什么不用一个 ReAct Agent 直接查库？"** 因为业务数字需要独立复算与版本化证据；ReAct 无法保证"模型没有自授权"，也无法在崩溃后判断外部调用是否已执行。
- **"Fake 模式是不是造假？"** 不。Fake 只替代模型决策，SQL、MCP、PG、Embedding、P3 验证、Checkpoint 都真实执行；文档中所有 Fake 结论都标注了边界，且另有真实模型 Smoke/Live 记录（含失败）。
- **"怎么防止 Prompt Injection？"** 文档只作为数据，不执行其中指令；工具权限由宿主绑定，文档不能扩大权限。报告另有指令式片段过滤，但这只是附加防线，不是完整检测器。
- **"为什么不用向量数据库？"** 单实例 pgvector 已能满足 512 维精确 cosine 与授权过滤；引入独立服务会增加一致性与运维面，当前没有性能证据支持。
- **“60/60 能说明什么？”** 说明固定候选在这 60 道合成 SaaS 题及已审阅范围内满足预注册门槛。要评价真实客户场景，仍需要独立抽样与外部语义审查。

## 事实边界

- 工程 Demo 的 10 次 Fake 调用及 1 次合成 unknown 调用按模拟账本列报。正式 48k 批次单列实际 Provider 用量与账单。[工程 Demo](releases/p7-engineering-candidate-v1/frozen/p7-demo-acceptance.md) · [正式业务验收](research/p7-formal60-48k-acceptance.md)
- 远端 CI 对应发布提交 `23c44c7`。旧 Gate 2B 的 STOP 和 `not_run` 按原批次保留。[CI 运行](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/42354878566) · [评测索引](evaluation.md)
