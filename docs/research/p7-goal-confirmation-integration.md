# P7 Phase 2C.6：可信 Goal 确认接入与端到端验收

2026-10-31。**PASS（有界工程验收）**。不代表自然语言总体质量、真实 DeepSeek、生产部署或远端 CI 已通过。

本轮在原 Chat/FastAPI/Outbox 上完成有限合同审查、确认、修改和撤回；未建立新的 Scheduler、Agent、Verifier、账本或恢复系统。默认 BGE 未变。所有模型决策为明确的 Fake/脚本；数据库、Embedding、MCP、P3、Report 和持久化实际执行。

机器结果：[p7-goal-confirmation-integration.json](p7-goal-confirmation-integration.json)。设计：[ADR-019](../adr/0019-web-goal-confirmation.md)。父阶段：[Goal v4 交付](p7-trusted-goal-scope-attestation.md)。原分支 `p7-ci-verification-20261028`、HEAD `f8b122438d2c67ab26e618ecded72ecc18454015` 保留，本轮没有 commit/push。

## 实际基线与增量

| 原有实际能力 | 本轮接入 |
|---|---|
| PG Conversation/Message，owner/TTL/配额，payload hash，不可变消息 | 原消息保存有界完整合同；服务器确认/拒绝追加为消息事件 |
| ChatDraft、Rule-only、授权 Dataset/Metric、原 MCP | 以真实 MCP Manifest 解析授权 Source/Document/Index，保存指标定义与时间窗口审阅投影 |
| launch.confirmed 仅表示提交，Journal 表示执行许可 | RAG 改为先审阅完整有限合同，再进入原 Journal 执行审批；两次决定不合并 |
| Goal v4、confirm_finite_scope、Manifest/Receipt/Report/Inspector | 后端只从当前有效、已认证决定记录重建同一 Attestation |
| Outbox/Worker/取消/恢复 | 继续复用；修改/撤回写原取消命令，unknown 不通过新合同替代 |
| Streamlit HTTP-only、历史/审批/报告组件 | 有限合同卡、原问、限制、三项默认不勾选的声明、服务器状态与修改入口 |

只新建了隔离库 `datapilot_test_goal_confirmation_web_v1_20261031`（现有测试实例端口55441，PG17/pgvector，既有迁移0008）。未 Seed、未改历史迁移/依赖/锁文件、未写原 Demo/评测库。Docker 引擎及已存在的隔离测试容器原先停止，本轮恢复其运行，没有重建或删除卷。

## 接口与持久合同

- `POST /api/v1/conversations/{cid}/messages`：原问题、候选选择与可选 `supersedes`。解析失败先澄清；有效文档候选生成 `goal_contract`，不创建业务 Run。
- `GET /api/v1/conversations/{cid}/messages/{mid}/goal`：重新核对 owner/TTL、当前 Dataset/版本/定义/授权和宿主配置，返回完整合同。
- `POST .../{mid}/launch`：SQL-only 保留原行为；RAG 必须提交当前版本/hash前置条件及三项明确审阅声明。客户端不能提交 Attestation、confirmation_ref、actor、eligible 或 policy。
- `POST .../{mid}/goal/reject`：追加拒绝/撤回事件，发送原取消命令；重试仍指向原合同和 Run。
- `/tasks/{id}/approve|resume|cancel|report|trace`：继续原实现和安全边界。直接 `/tasks` 创建 RAG 返回 `GOAL_CONFIRMATION_REQUIRED`，不能绕过卡片。SQL-only 不增加范围审批。

合同ID为原 Message ID，版本为原会话 sequence，hash覆盖完整服务器快照，包括原问/请求、授权范围、Dataset版本/源hash、Metric/Semantic版本与定义、时间/单位、Corpus/Document/Source/Index、Required与限制、过期时间。Source选择只是缩小必需集合，不授予权限；“授权背景”也不自动获得补充引用资格。

`can_confirm`仅表示可以提交范围审阅，**不是** `completion_eligible`、证据充分或业务完成。新事实描述只包含 fact_id/description，不是已证明事实。

### 新字段与辅助实现的必要性

| 增量 | 用途 |
|---|---|
| `ChatSelection.required_source_ids` | 只能从真实授权 Manifest 指定 Required；未知/重复来源拒绝 |
| `MessageCreate.supersedes` | 追加新合同并使旧确认失效，不 UPDATE 旧 payload |
| `ChatLaunch.expected_version/expected_contract_sha256` | 乐观前置条件，不接受客户端自创合同作为权限结果 |
| reviewed_contract / covers_original_goal / prerequisites_resolved | 分别确认审阅、完整目标与已解决前提；缺一不能确认 |
| GoalReject、GoalContractView、GoalSource/GoalDataset、MessageView投影 | 严格、有界的 HTTP 审阅和服务器事件视图 |
| HostPolicy.rag_embedding_profile | 可信本地配置显式 opt-in；无请求/.env/PATH解释器选择，非空才加入原宿主策略hash |
| ChatService 的消息/事件/状态/版本/actor/授权辅助函数 | 在原 owner PG 锁下原子追加决定、创建原 Outbox、绑定唯一 Run |
| goal_confirmation.proposal/base_payload/bind_payload | 分别解析授权元数据、复查原授权、由已提交决定重建原 confirm_finite_scope；不是新语义验证器 |
| ProductService.ensure_no_unknown/cancel_runtime | 读取原调用状态，复用原 Backend/control_state/取消；不建立新恢复状态 |
| ui_chat.goal_card | 只显示与提交 HTTP，不访问 DB、MCP、内部确认函数 |

消息体在32KiB数据库限制之前以24KiB拒绝；合同最多8份原件，不截断原文/引用。文档原问必须完整保留且不超过512字符；组合任务也不得先截断再确认。确定的提交前配额/输入/scope拒绝可修改输入；响应丢失等不确定结果仍保留原幂等意图。

## 确认、身份与恢复

实际 HTTP 会话认证后，由中间件注入 actor_session_hash。服务器记录 owner（会话所属Conversation）、Conversation/Message、完整版本/hash、时间/TTL和三个明确决定；ref 为 `web-goal:<服务器事件UUID>`。同一 owner 原 PG 锁将确认事件、原 WebStore.command 和 Message.run_id 原子提交。并发/ACK丢失只产生一个事件、一个 Run。

后续授权、执行和 Web Inspector 先重读不可变事件及当前授权，从快照重建相同 Scope，再进入原 Manifest/Goal/Receipt/Report 校验。新字段不进入模型权限来源。底层 SDK仍以可信宿主为边界，Attestation并不是面向不可信调用者的独立密码学签名。

- 修改通过 `supersedes` 新增消息；旧状态为 superseded，新版本重新审阅。取消ACK丢失后重试会继续原取消，不另建 Run。
- 独立追问可以参考授权历史作候选，但不继承旧 Attestation；旧证明只绑定旧合同/Run。不是删除全部历史确认。
- 拒绝/撤回/过期/权限或版本变化阻止继续确认、恢复和发布报告。已发生的工具/外部请求不会被假定未执行。
- issued/uncertain 先人工对账，不能以修改合同换 Run 或释放预留。原 Journal/Ledger/Checkpoint/Artifact 逻辑未改。
- 本地单用户可重新认证读取原 owner 的有效决定，actor hash保留原审计归属，不因浏览器重开伪造新确认。这不是生产多租户/session隔离设计。
- 旧未绑定当前 Web 确认的 RAG Run失败关闭 `RECOVERY_IDENTITY`，不自动升级。旧v3 SDK恢复拒绝及快照不变控制通过。

## UI 与真实业务结果

合同卡显示完整原问、有限子目标、用途、数据/指标/版本/时间、Required来源、待核验事实、未知前提、预算与限制；完整JSON可展开。三个声明默认关闭；刷新不提交；服务器返回 confirmed 后仍需原执行审批。

真实浏览器在独立8026/8526测试宿主完成：聊天输入 → 选已授权Corpus/明确用途 → pending合同 → 显式范围确认 → awaiting_review → 原执行审批 → 真实MCP/Report → completed → 实际重启API/UI → 同一报告恢复 → 撤回后 rejected，旧报告HTTP返回 `GOAL_REVOKED`。测试操作者为自动化模拟用户；不是负责人对生产业务/Gold的人工签署。

浏览器使用原 Outbox + execute_one，脚本明确控制模型决定，Dispatcher关闭以便分步验收；没有用脚本替代数据库、Embedding、验证或报告。故不宣称已验证真实模型自主推理或默认Fake的自动派发业务质量。原Chat/RAG回归与原Worker未重建。

浏览器完整点击在最后的缺失文档Scope补丁之前完成；最后补丁不改变已声明文档的路径，新增门控路径另经双版本真实HTTP/PG验证。没有将旧浏览器记录冒充再次点击的结果。临时测试API/UI已经停止，数据库及工件保留。

浏览器Run：`2a354627-f6ee-4667-9720-6c49a9a32a2f`。重启前后报告hash：`f19a02dd84eb6b69373c5f809537b70c7cd46dd7c04952f04390af0bfde39f50`。Journal/调用/Artifact/Ledger快照hash均为 `818edabf993754182baf5bc8b28bc4c6af1f77bdcd401aa104ebe41b286bd5b9`；当时已有4组P3 Evidence/Verification身份/hash未变。重启不重新执行。原生截图在本次浏览器工具记录，未导出独立图片文件。

正例包含真实文档引用与组合查询的300 CNY（Decimal精确比较），数值经P3，文档经原引用/Goal验证。事实描述无证明仍 partial/unavailable；真实引用不能补齐未知事实或证明因果。BGE默认和显式Qwen CUDA-FP16均实际经过同一Web合同/原MCP/Report/Inspector；Qwen Web摄取未新增，使用既有受控CLI，错误混用在入口拒绝。

## 实际测试与失败保留

全部路径在 `artifacts/p7/goal-confirmation-web-v1/`；测试函数清单和计数见机器JSON，不能把参数测试数当独立业务质量任务数。

| 结果记录 | 实际结果 |
|---|---|
| unit-final-r4-311.xml | 628 passed，18 skipped |
| unit-final-r4-313.xml | 628 passed，18 skipped |
| pg-final-311.xml | 10 passed，1 failed（测试子进程配置问题，后续补验通过） |
| pg-remaining-311.xml | 3 passed，1 failed（Qwen CLI未注入隔离UploadReader，后续补验通过） |
| pg-qwen-r2-311.xml | 1 passed，真实CUDA/PG/MCP |
| pg-legacy-311.xml | 15 passed，原Chat/SQL/P3/RAG |
| missing-doc-scope-after-311.xml | 1 passed；明确文档目标不能降为SQL-only，纯SQL正常完成 |
| Python3.11 PG最终有效通过并集 | **30个唯一测试项**，含15项新增及15项原回归；不是把失败记录删除后拼成功率 |
| pg-focus-313.xml + missing-doc-scope-after-313.xml | **8个唯一项通过**，分别7+1；含BGE、P3、unknown、Qwen、SDK v4恢复/v3拒绝和缺失文档scope门控 |
| Ruff check / format --check | 当前Web及对应测试通过，27文件格式符合 |
| JSON/OpenAPI/Markdown本地引用、git diff --check | 通过（完整回归不是本轮范围） |

18个skipped均为非DB单元运行中未启用的旧PG Review测试，不能算通过；本轮没有运行全仓pytest、全部PG矩阵、远端CI、新Linux/Docker回归或付费Live。

保留的失败/中断及根因：

1. pg-initial：因输出不足中断，无终态JUnit，**不声称通过**，已有记录未清理或复用。
2. pg-diagnostic：8 passed/1 failed，脚本首个查询不是组合合同原问，触发 `RAG_QUERY_POLICY`。改脚本决定，不改产品守卫。
3. pg-r2：Qwen测试导入路径错误，collection失败，无该次通过结论。
4. pg-r3：8 passed/1 failed；组合文档查询真实空召回，P3成功、报告安全partial。保留。后来使用明确限定且含来源字面规则的公开合成工程问题验证接线，不能把该调整当独立召回质量提升。
5. pg-focused-r4：300与300.0000000000000000文本表示不同；用Decimal比较数值和CNY单位，未改P3或结果。
6. pg-final-311跨进程：子进程继承本机.env配置而与捕获Settings不同，正确被 `RECOVERY_VERSION` 拒绝；显式传递非敏感配置快照后通过，未跳过Manifest。
7. Qwen CLI最初遗漏隔离UploadReader注入，Dataset预检失败；修正测试环境绑定后通过，原失败保留。未执行非隔离数据库写入。
8. unit-ui-r2：Streamlit把False渲染为带反引号文本，测试改查实际session_state；不改业务行为。

9. missing-doc-scope-before：1 failed。无文档Scope但明确要求文档时，旧宿主进入指标处理而未先拒绝；未重新执行任何历史错误完成。最后补丁在原task_payload统一门控，Chat返回澄清，直接API拒绝；仅校验声明边界，不改冻结Rule-only解析器。带用途而无Corpus的候选DTO也拒绝。修复后两版本真实PG单项均通过。

必要重验命令（新的label/输出位置，不覆盖旧日志；测试会向新隔离库追加新记录，不是恢复旧Campaign）：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest tests/test_web_goal_confirmation.py tests/test_chat_ui.py tests/test_chat_contracts.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_web_goal_confirmation.py tests/test_chat_ui.py tests/test_chat_contracts.py -q
# 受控私密wrapper仅绑定本阶段隔离库；需现有PG17+pgvector与固定本地模型。
.venv\Scripts\python.exe artifacts/p7/goal-confirmation-web-v1/pytest_run.py new-label tests/test_web_goal_confirmation_postgres.py tests/test_web_goal_confirmation_qwen_postgres.py -x
.venv\Scripts\python.exe -m ruff check src/datapilot/web tests/test_web_goal_confirmation*.py tests/web_goal_recovery_probe.py
.venv\Scripts\python.exe -m ruff format --check src/datapilot/web tests/test_web_goal_confirmation*.py tests/web_goal_recovery_probe.py
git diff --check
```

## 修改与封存

生产修改仅限：`web/app.py`、`chat.py`、`chat_contracts.py`、`chat_routes.py`、`config.py`、`service.py`、`store.py`、`ui_chat.py`、`ui_components.py`、`ui_management.py`，新增 `web/goal_confirmation.py`。`web/client.py`、`worker.py`和其他100个既有产品源码保持父阶段字节hash；尤其P3、RAG、Goal v4、Coordinator、Report、Journal/Ledger/Durable未修改。

新增测试：`test_web_goal_confirmation.py`、`test_web_goal_confirmation_postgres.py`、`test_web_goal_confirmation_qwen_postgres.py`、`web_goal_recovery_probe.py`；更新原 `test_chat_postgres.py` 和 `test_rag_only_postgres.py` 的模拟用户确认/首查决策，不删除有效断言。管理页移除了已无法安全直达RAG的重复建任务分支；RAG统一回合同卡，不创建第二套审批入口。

实现清单：`artifacts/p7/goal-confirmation-web-v1/implementation-web-final-r4.json`，SHA256 **a54bd133ff6c274618f37c98b329353b81fd886181930ee948176a25a85f340c**。每文件完整SHA在该清单及机器JSON。旧r1/r2/r3保留。

父2C.5 Seal自身SHA仍为 `342fd7c4cb9990827be5e1680538edebc61b83625a820667e7173837e24aaa0c`。其444条文件中434保持原hash，10个Web源码按本次授权版本化；无未授权变化。没有宣称旧实现的全部源码hash仍匹配。旧3324路径完整性记录保留，本轮未重扫所有旧数据库；不触碰旧Gold/Scorer/Seal/历史运行。2C.4的 fr002 STOP、21 observed/179 not_run/Validation 0保持，不调用旧Runner。

原工作区大批未提交成果仍在；开发前Git状态/diff、Web源码快照、历史核验、所有JUnit/失败/配置身份在本阶段忽略目录留存。私密环境/源文/完整合同/原始工件不进入公开Trace或Git。

## Gate与未验证边界

| 问题 | 结论 |
|---|---|
| 真实产品入口能否审阅完整合同 | 是，实际浏览器与HTTP通过 |
| 未确认文档任务能否直接completed | 不能；创建/发布门控与原Verifier分别校验 |
| 后端是否识别合法/伪造确认 | 认证会话、owner、版本/hash、事件及Run绑定；伪造字段拒绝。不识别人类与合法自动化的生物学区别 |
| 修改/追问旧证明是否可复用 | 显式修改使旧合同失效；新追问不继承；旧证明仅属于原Run |
| 有限任务能否完成 | BGE/Qwen文档和P3组合正例实际完成；缺事实仍保守 |
| UI是否HTTP-only | 是，不调用DB/MCP/内部confirm |
| Goal/Receipt/Report/Durable是否一致 | 是，原身份校验与跨进程/重启/快照控制通过 |
| 旧Run限制是否保留 | 是，不兼容v3拒绝；不迁移或改旧hash |
| 新独立非付费质量验证前提 | 已具备有界工程前提；仍需用户另行授权，未启动 |

残余风险：明确提及“文档”或受支持文档文件名、却未声明文档Scope的Web请求现在先澄清，避免只完成指标部分。该保守门控不是新语义解析器，否定提及或只把文档当数据描述时可能多一次澄清；没有宣称零过度澄清，也不保证识别所有隐式跨来源目标。

任意自然语言与合同等价不能由hash证明，可信操作者可能误审；未匹配的歧义仍依赖明确声明和修改，不能宣称所有fr002改写都被自动理解。没有全语料穷尽证明引擎、自动事实审批、自由指标脚本或通用语义澄清Agent。有限合同不等于材料齐备证明。

Qwen每stdio会话的显式就绪仍有冷启动成本，本轮不优化其生命周期；Web Qwen摄取需既有CLI。合同超过8来源/24KiB、文档原问超过512字符会明确拒绝。单用户owner重认证不是生产多租户。真实DeepSeek自主决策、广泛语义质量、生产并发/部署及远端CI **NOT_RUN**。

下一步可另行预登记新的独立非付费质量集，分别验证范围理解、真实用户合同选择、检索/事实/业务完成，保留拒答与人工误审风险分母。不得复用已STOP实验、启动旧179项、切默认模型、付费Live或进入Gate3。本阶段交付后停止。
