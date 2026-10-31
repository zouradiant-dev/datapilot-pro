# P7 Phase 2C.7：目标确认质量与最终源码验证

记录时间：2026-10-31T10:43:52.139589+00:00。结论：**BLOCKED_FOR_BUSINESS_AB**。

用户明确答复“暂无，按 NOT_VERIFIED 记录”。没有独立人工审核人、逐条阅读或签名。本轮只完成公开合成合同技术测试和工程控制，不将自动化点击、AI 自审或 Hash 一致等同人工语义验收。

## 分层 Gate

| Gate | 当前结论 | 边界 |
|---|---|---|
| Web 工程 | PASS（有界工程） | 最终源码，真实 HTTP/浏览器/PG/MCP、独立审批、重启、撤回；脚本决策 |
| Goal Confirmation Quality | NOT_VERIFIED | 人工语义审查缺失；有限目标可用性另有 4/15 过度拒答 |
| Retrieval / Evidence | BLOCKED（整体） | BGE 工程控制通过；Qwen 当前控制因 RAM 准入失败；独立检索质量未测 |
| Business Quality | NOT_VERIFIED / NOT_RUN | 正式 A/B 0 观测；保留 40 个条件性槽位，不伪造 20 条已注册业务 Gold |
| Safety | PASS（已执行控制） | 24 条未自动签发范围或执行；审批、撤回、旧身份及 unknown 负例通过，不外推全局语义安全 |

## 源码、数据和预登记

分支 `p7-ci-verification-20261028`，HEAD `f8b122438d2c67ab26e618ecded72ecc18454015`。全部原工作区修改保留，未 commit/push。本轮没有修改 `src/`、既有测试、迁移、依赖、规划文档或产品策略。

父最终 Web r4 Manifest SHA：`a54bd133ff6c274618f37c98b329353b81fd886181930ee948176a25a85f340c`，11 个 Web 文件和其余产品文件均匹配；本轮源码/输入注册 SHA：`4dbd037db8b46a7812dcc3c5789fbbd8204a4bc8fc5c4f8322f4a13301470460`。

公开输入位于 [cases](../../evaluation/goal_confirmation_quality/cases.json)、[Gold](../../evaluation/goal_confirmation_quality/gold.json)、[原件](../../evaluation/goal_confirmation_quality/sources.json)、[CSV](../../evaluation/goal_confirmation_quality/invoices.csv)、[协议](../../evaluation/goal_confirmation_quality/protocol.json)。24 条覆盖有限事实、SQL 时间窗、组合目标、多 Source、未知集合、穷尽性、否定、前提、英文和跨 owner。先冻结逻辑输入/Gold/规则，再物化并封存具体身份，最后收集正式 24 条；更早的浏览器准备请求不属于这 24 条或 40 个业务槽位。

新隔离库 `datapilot_test_goal_confirmation_quality_v1_20261031` 使用 PG17/pgvector、原迁移与隔离角色；没有 Seed、清库、删卷或连接历史库写入。8 份新公开文档供合同观察，另 1 份发布提醒文档仅供工程控制。保留真实另一 owner 的 Dataset 权限负例。Dataset `456cf8a5-4a7c-530a-9d6a-d51d7184f49f` v1、Semantic/Metric v1 及全部 Source/Document/IndexVersion/Hash 固定于 `bindings.json`、`binding-seal.json`。

Gold 作者与技术审查者是同一 Codex AI，生成者是冻结 Rule-only 产品，执行者是薄 HTTP/CUA 驱动。没有独立人工语义审查。公开开发夹具做了原文及标点/大小写/数字归一的重复检查；新主题不是旧 STOP 题目的实体替换，但同一作者知道旧缺陷类别、案例共享原件与数据，因此不声称 IID、封闭 Holdout 或独立人工准确率。

独立 CSV/Decimal Gold 为 1229.00、111.00、141.25 CNY；三条独立受限 MCP SQL 全部匹配。Gold 未由 Agent 报告反推，P3 配方、Verifier、Embedding、0.55/Top-k/预算和默认 BGE 均未改。

## 24 条技术合同观察

全部 24 条已观察，0 not_run；12 条生成请求，23 条存储原始消息，1 条跨 owner 被 HTTP 403 拒绝。

| 指标 | 实际计数 | 含义 |
|---|---:|---|
| 技术预期响应 | 20/24 | 声明字段/拒绝形状，**不是业务完成率或语义准确率** |
| 原始文本保留 | 23/23 | 已接受消息逐字相同；被拒请求 N/A |
| 声明字段、版本及引用保留 | 12/12 | Dataset/Metric/时间、Source/Index/Hash、Fact ID、causal 字段；不证明自然语言合同等价 |
| 有限目标可审查候选 | 11/15 | 另 4 条被过度拒答 |
| 非有限目标未自动接受 | 9/9 | 仅 1/9 有具体穷尽性提示，其余多为泛化拒绝 |
| 自动执行 / 自动 Attestation | 0/24、0/24 | 收集器从不调用 launch/approve |
| 错误确认率 | N/A，分母 0 | 24 条没有真实确认尝试，不能宣称错误确认率为 0% |
| 人工合同等价性 / 语义遗漏率 | NOT_VERIFIED | 不用字段保留率代替 |

| Case | 预期 | 请求候选 | 技术判断 |
|---|---|---|---|
| gc7-001 | 有限 | 有 | 符合技术预期 |
| gc7-002 | 有限 | 有 | 符合技术预期 |
| gc7-003 | 有限 | 有 | 符合技术预期 |
| gc7-004 | 有限 | 有 | 符合技术预期 |
| gc7-005 | 有限 | 有 | 符合技术预期 |
| gc7-006 | 有限 | 有 | 符合技术预期 |
| gc7-007 | 有限 | 有 | 符合技术预期 |
| gc7-008 | 有限 | 无 | 过度拒答 |
| gc7-009 | 有限 | 有 | 符合技术预期 |
| gc7-010 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-011 | 有限 | 无 | 过度拒答 |
| gc7-012 | 有限 | 有 | 符合技术预期 |
| gc7-013 | 有限 | 有 | 符合技术预期 |
| gc7-014 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-015 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-016 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-017 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-018 | 澄清/拒绝 | 有 | 符合技术预期 |
| gc7-019 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-020 | 有限 | 无 | 过度拒答 |
| gc7-021 | 有限 | 无 | 过度拒答 |
| gc7-022 | 澄清/拒绝 | 无 | 符合技术预期 |
| gc7-023 | 有限 | 有 | 符合技术预期 |
| gc7-024 | 澄清/拒绝 | 无 | 符合技术预期 |

四条过度拒答：

- **gc7-008**：明确只计算 paid revenue、只解释与 MRR 的区别，MRR 否定语境仍触发不支持拒绝。
- **gc7-011**：两个指定文件名与中文邻接，文档/指标识别未形成有限文档请求，反而要求指标和时间。
- **gc7-020**：明确不要文档，缺 Scope 防护仍按“文档”提及要求 Corpus，阻断 SQL。
- **gc7-021**：文档规则解释与否定叙述被识别为需指标任务，无法形成有限合同。

其余 8 条泛化拒答不能证明系统找到了真实缺失的客户全集、合同附件、历史版本或访谈前提。当前证据只支持“没有自动执行”，不支持“理解完整”。本轮未修这些产品规则，也没有重选/重跑案例。

## 评分器失败与只读修正

初始预登记评分器 v1 在真实 `CreateTask` 上抛出 `KeyError: dataset_id`：Dataset 在 `GoalContractView.datasets` / `MetricRequest`，不存在顶层。原文件、原 SHA 和 `scorer-v1-contract-failure.log` 原样保留；v1 没有有效 0/24 或其他成绩，不能记为通过。

另建 [scoring_v2.py](../../evaluation/goal_confirmation_quality/scoring_v2.py)，仅按权威 DTO 定位身份，保留签名、原问题、版本/Hash、结构及阈值检查。Gold、输入、原响应与产品未改。v2 是**观察后的显式离线定位修正版**，不是原预登记评分器；不据此宣称严格独立 Benchmark 通过。5 项布局/签名/身份反例验证后，Python3.11 首评与独立 Python3.13 进程对同一 24 份签名包复评，24/24 完全一致；未重新生成合同或请求模型。最终 Scorer SHA：`3255adda95735dab87fb24f9901feb1c219673259f95b156886a12667a6c609e`；Gold SHA：`5551abb1e821ef1ef4128e35a22f4bc6f6c5213c32823a417b5c3e030b67d6f0`。

## 最终源码浏览器、P3 与恢复

API `127.0.0.1:8027`、UI `127.0.0.1:8527`，Fake/脚本 `ReportDecisions`、真实 BGE/PG/MCP/原 LangGraph/Verifier/Report/Durable，`dispatch=False`，只经原 Outbox `execute_one` 单次处理明确待办。没有第二套调度或恢复框架。自动化的两项合同确认和三项执行审批不是独立人工审批。

1. 浏览器输入完整问题；缺 Corpus 先澄清，显示完整合同、原问、Dataset/Source/版本、限制，三个确认默认未勾选。
2. 首个有限措辞含“每批”被判为 unresolved，旧候选保留；通过浏览器修改形成新版本，旧候选显示 superseded。后续审查完整合同并经原 API 事件确认。
3. 确认后仍停在 `awaiting_review`，0 模型调用；再经独立 Journal 审批执行。
4. 首个执行 Run `1561392c-0f23-4039-ae9e-5a2075dd5eba` 因 no_matches 返回 unavailable；没有重跑或覆盖失败。
5. 另行预登记的一次有限引述工程控制 `b688747d-bcdd-4197-908f-aa0fa2b0db78` 完成，浏览器展示授权原文、行1–1和 Chunk `3a28b9151d35b9b3c361dbc09a951fa17e01d53e27dbe0a69fcc906e369d3efb`。它是工程正例，不能取代原失败或计入独立检索收益。
6. SQL-only Run `108d3573-7a94-4042-ab62-fcc6d05f7edb` 不出现 RAG 确认，原审批后 P3 verified 收入为 **1229.00 CNY**。Evidence `250d36f5-10b0-4fab-afe7-d4c9c4d91afc`、Verification `1cfa1e18-a257-40b0-811a-aacb3cb73733`。
7. 实际停止并重新启动仅本轮 API/UI；独立进程签名采集逐字段比较三 Run 的 payload、view、outbox、report、trace，全相同。P3 IDs/Hash/verdict、Report/Artifact 引用、Ledger 未改变，没有追加模型调用。
8. 重启后浏览器仍显示原 confirmed/completed；撤回后显示 rejected 并隐藏原报告，API `403 GOAL_REVOKED`。诊断宿主通过原 Inspector 只读复验原工件，再用原 `report_view` 投影核对，报告与预算未改变；SQL P3 报告也未受影响。原诊断把内部 Report 与公共 DTO 直接比较的失败留在 `withdrawal.log`，修正检查在 `withdrawal-projection-check.log`，不改产品或结果。
9. 明确“参考文档”却未选 Corpus 的候选仅澄清，无 Run、无 SQL 降级。其澄清日期控件曾显示2025-10默认值，尽管原问是2026-03；没有提交该表单，记录为待处理的交互语义风险。

已确认合同的修改/旧确认重放拒绝、并发幂等、跨会话伪造、缺事实、跨进程恢复、unknown 不重发，复用现有 PG 测试验收。浏览器修改是 pending 合同控制，确认后修改的更强断言来自 `pg-edit311`；不混称所有分支均为完整浏览器点击。原生 CUA 截图在对话工具记录中，没有虚构独立截图文件。

## 实际测试与失败记录

| 范围 | Python3.11 | Python3.13 |
|---|---:|---:|
| 本轮非集成定向：76项 + v2新增5项 | 81 passed | 81 passed |
| 本轮真实 PG/MCP/BGE/P3 | 8 passed | 3 passed（含2项交叉版本重点、1项旧v3身份拒绝） |
| 本轮 Qwen CUDA 工程控制 | **1 failed，资源拒绝** | NOT_RUN |

两个版本的合计数不是去重任务数；PG 跨版本有重复。非集成初始13项是76项子集，不重复计入81。没有运行完整 pytest；父阶段628 passed/18 skipped 保留为历史结果，未冒充本轮执行。

主要命令与路径：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_goal_confirmation_quality.py tests/test_web_goal_confirmation.py tests/test_chat_ui.py tests/test_chat_contracts.py tests/test_goal_scope_integrity.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_goal_confirmation_quality.py tests/test_web_goal_confirmation.py tests/test_chat_ui.py tests/test_chat_contracts.py tests/test_goal_scope_integrity.py -q
.venv\Scripts\python.exe -m pytest tests/test_goal_confirmation_quality_v2.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_goal_confirmation_quality_v2.py -q
# 私密PG环境通过本轮 pytest_run.py 注入，完整精确selector见交接记录和JUnit
.venv\Scripts\ruff.exe check src tests evaluation/goal_confirmation_quality
.venv\Scripts\ruff.exe format --check src tests evaluation/goal_confirmation_quality
git diff --check
```

JUnit 和日志均在 `artifacts/p7/goal-confirmation-quality-v1/`：`target311/313.xml`、`scorerv2-final311.xml`、`scorerv2-313.xml`、`pg311.xml`（6）、`pg-edit311.xml`（2）、`pg313.xml`（2）、`legacy313.xml`（1）、`qwen311.xml`（1 failed）。

Qwen 先完成真实摄取，但候选的 MCP 准备阶段可用 RAM **3,134,971,904** 字节，低于 **3,221,225,472**，返回 `403 EMBEDDING_RESOURCE_LIMIT`，进程正常关闭，无降阈值、CPU回退或盲重试。原完整失败见 `qwen311.log/xml`；原件摄取日志 `artifacts/tests/qwen-web-ebd251cb92904ffeadca9ef7d2ff1fe7/ingest.log`。最终关闭本轮服务释放到约4.00GB，并不等于补验通过；本轮没有第二次 Qwen 测试。

其它失败保留：重复 Corpus ID 的新测试夹具（`unit311.xml`:1 failed/12 passed，预登记前修正后13 passed）；9份文档超过单次 Scope 上限，改为分批只读元数据、没有重摄取；私密ACL读取被拒，保持ACL后授权只读；Scorer v1布局错误；SQL驱动在批准尚未提交时拒绝无待办执行（`sql-execute.log`，随后只读确认seq2后处理原命令）；诊断的内部/公共Report类型比较错误。准备脚本的导入路径、嵌套结果字段、OpenAPI地址和psutil缺依赖也记录为工具脚本错误，不伪装产品验收结果。

Ruff 全部通过；format 检查234个文件。OpenAPI 3.1.0，26路径、244内部引用全部解析。JSON、Markdown链接、Diff与封存校验见本轮 `final-static-checks.json` / `result-seal.json`，其最终执行结果以机器记录为准。

## 成本、历史与未验证边界

24个合同HTTP系统耗时：p50 **5.049s**、p95 **12.202s**，总计 **138.949s**，串行、含MCP元数据会话。它不是Worker/E2E或单工具10秒Timeout指标。人工思考/操作耗时、分阶段启动/编码/资源p95均 NOT_MEASURED。本轮没有另做性能实验。

付费 Provider 调用/Token/费用均0。三个浏览器工程Run共7次脚本模型决策、105个Mock报告Token，只是合成计量，不能称真实Provider usage、cache或成本。回归夹具的Fake Token总额未作为质量/费用统计。没有DeepSeek、真实账单或BGE/Qwen业务收益结论。

历史2222唯一路径：2218匹配原SHA；1个已由本轮开始源码/父封存绑定，另3个测试文件匹配Phase2C.5既有封存。全部差异有版本依据，剩余意外差异0。Phase2C.6父Seal99文件完整，原tracked工作区Diff与本轮开始相同。原Pilot14/16、15/16；2C.2的75/200、125 not_run/BLOCKED；2C.4的21/200、179 not_run/BLOCKED、STOP和Seal均保留，不续跑。未写历史数据库；未做历史DB逐行快照，不把文件SHA核验说成数据库WORM证明。

## 最终十项回答与下一步

1. 原始文本23/23、候选声明字段12/12保留；**不能据此认定所有合同语义完整**，4条有限目标被拒。
2. 没有独立人工语义证据，NOT_VERIFIED。
3. 24条没有自动错误Attestation，但确认尝试分母为0；两次工程确认不构成人工语义通过。
4. 测试中的未确认/未解决目标未执行或completed；不保证任意未识别自然语言请求都安全，仍依赖可信完整合同审阅。
5. 指定有限引述和已确认P3指标能够completed；原空召回仍为unavailable。
6. Qwen收益是否转化更多正确报告：NOT_RUN，不能外推旧A/B。
7. 已执行安全控制无新增违规，生产源码未改；Qwen当前资源控制未验收通过。
8. 系统HTTP成本如上；人工交互成本未测，付费成本0，Mock计量另列。
9. **不能进入80条Validation**；也未启动40个条件性配对槽位。
10. **没有新的DeepSeek Live准入**，仍需独立质量依据、资源Gate及单独付费授权。

下一步先处理这四类过度拒答及澄清默认日期的独立公开Dev修复方案，另行授权后实施；资源充足时用新身份单独补Qwen工程回归。独立人工审查仍NOT_VERIFIED，不重复索要不存在的签字，也不借用旧Gate2B的负责人决定替代本阶段质量准入。详见 [交接记录](p7-goal-confirmation-quality-handoff.md)。本轮停止，不进入Gate3、不提交推送。
