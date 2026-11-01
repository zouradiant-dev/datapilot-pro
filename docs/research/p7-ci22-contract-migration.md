# CI #22：代表性测试契约迁移（本地）

本轮仅迁移四类代表路径的测试前置条件，不修改产品 API 或核心。基线提交 `607e68c988121e0e686ee36f740e601a5f8e0e86`，分支 `p7-engineering-candidate-v1`。本轮创建独立本地 `fix(test)` 提交，不推送、不重跑远端CI。原 #22 归因报告两份文件保持原字节并留在工作区，不纳入本次提交。

**结论：最小迁移已实现，单元/合同验证通过；真实 PG/MCP 验收 NOT_RUN，不宣称 #22 已修复或具备全量迁移准入。**

## 实际修改与必要性

| 文件 | 修改及必要性 |
|---|---|
| [Web确认测试](../../tests/test_document_confirmation_postgres.py) | 复用已有 `decision(message)`，通过原HTTP launch提交精确版本/SHA及三项决策；保留简单confirmed请求应403的负例，核对服务端事件与Attestation引用。原独立执行审批、幂等、历史与报告终态断言保留。参数化构造适用于原四个purpose，本轮只选择summary代表收集。 |
| [引用篡改测试](../../tests/test_document_fact_postgres.py) | 仅在 `test_real_pins_and_scope_cannot_be_forged` 中通过原 `confirm_finite_scope` 确认有限年限问题；新增有效原件可completed的控制后，再执行原四种篡改raises与错误owner拒绝。防止原断言被范围守卫遮蔽。 |
| [预算恢复测试](../../tests/test_phase4_postgres.py) | 仅在参数化恢复测试中对既有有限审计问题作明确合成Host确认，再持久化输入。原18000 Token、轮次、五次Fake调用、搜索/读取次数、错误版本拒绝、重复恢复与RECOVERY_UNCERTAIN断言不变。其他未迁移测试不自动获得确认。 |
| [旧版本拒绝测试](../../tests/test_host_goal_postgres.py) | 仅给旧Manifest拒绝代表测试提供合法的当前有限Host合同，仍以旧goal投影启动新测试Run、当前身份恢复必须RECOVERY_IDENTITY，前后持久快照必须相等。 |
| [测试进程入口](../../tests/host_goal_probe.py) | 删除从local-only目录加载旧可执行源码的路径，新增小型 `legacy_goal` 适配函数，仅供固定公开问题/策略的测试Manifest投影。它校验query、relevance policy、阈值及goal hash，不是产品回退或模型工具；现有v2/v3测试模式保持不变。 |
| [公开legacy identity](../../tests/fixtures/rag/host-goal-legacy-identity.json) | 新增纯JSON合成夹具，保留pre-requirement-policy字段、原投影SHA与源文件SHA出处。没有任何历史Run、业务原文、Gold或人工审批记录。保留旧所有权查询的 `unsupported_requirements=true`，不按v4语义回填旧身份。 |
| [合同安全单元测试](../../tests/test_goal_scope_integrity.py) | 新增两项：仅复制公开JSON到无artifacts目录仍可读取；错问题/策略/阈值拒绝；相同问题旧/新goal身份不同，经原Backend.authorize拒绝且输入行不变。Mock连接明确是单元替身，不冒充真实PG。 |

所有Host确认均明确属于公开合成测试的宿主决定，不是独立人工审核签名。没有通用fixture自动确认、直接构造Attestation或修改reviewed。只有真实HTTP路径生成Web事件；库级测试复用已有可信Host接口。

## 保留的安全断言

本地AST审计 `artifacts/p7/ci22-contract-migration-v1/assertion-audit.json`：

| 代表函数 | 原assert数 → 现assert数 | 原pytest.raises数 → 现数量 | 核对结果 |
|---|---:|---:|---|
| Web purpose/审批/历史 | 14 → 17 | 0 → 0 | 13条原AST不变；仅幂等请求由简单confirmed改用相同精确HTTP决策，仍断言同一Run；所有原参数化终态不变。 |
| Citation篡改 | 2 → 4 | 2 → 2 | 原断言全部保留；增加有效原件与事实覆盖控制，四种篡改仍须抛异常。 |
| 预算跨进程恢复 | 11 → 11 | 0 → 0 | 原断言全部保留，包含wrong-version、无重发、预算与unknown分支。 |
| 旧Manifest拒绝 | 3 → 3 | 0 → 0 | 原断言全部保留，拒绝码与快照相等条件不变。 |

这只证明测试未被弱化，不能证明尚未执行的PG分支已通过。旧 `run_question` 保持低信任、不改签名；已确认的语义正向单元控制复用原Host/Coordinator路径，未改成literal查询绕过语义校验。

## 真实执行结果

日志/JUnit根目录：`artifacts/p7/ci22-contract-migration-v1/`；所有付费调用0，业务数据库写入0。

1. 新增legacy单元测试在适配实现前 **2 failed**（缺少legacy_goal），见 `legacy-before.log/xml`。这不是重新运行#22的PG失败；#22原JUnit仍完整保留在上轮目录。
2. 首次核对公开legacy投影时发现其草稿未保留旧 `unsupported_requirements=true`。逐项对照只读旧函数后修正新夹具，保留 `legacy-projection-audit-before.json` 和 `legacy-projection-audit-final.json`；最终两个策略对象与参考投影完全一致。没有复制旧可执行源码，也没有改旧文件。
3. 最终定向测试：

| Python | 单元/合同 | pytest报告耗时 | 四个PG代表用例收集 | PG实际执行 |
|---|---|---|---|---|
| 3.11 | **25 passed / 0 failed / 0 skipped** | 3.79秒 | 4 collected | **NOT_RUN**；原opt-in守卫4 skipped |
| 3.13 | **25 passed / 0 failed / 0 skipped** | 3.64秒 | 4 collected | **NOT_RUN**；原opt-in守卫4 skipped |

最终单元日志为 `final/unit-311.log/xml`、`final/unit-313.log/xml`；精确命令在 `final/verification.json`。包含：整个修改后的Goal身份安全模块、Web DTO/UI Mock HTTP控制、Host/Coordinator语义正向控制、父子预算序列化、已提交模型响应复用且不重发。不是完整pytest、真实浏览器或Live质量评测。

四个PG用例的收集与skip日志为 `collect-pg-311/313.log`、`pg-unavailable-311/313.log/xml`。只读Docker检查返回 `dockerDesktopLinuxEngine` 管道不存在；没有启动Docker、创建/Seed数据库或使用用户现有数据库。本轮没有添加skip或放宽marker，不能把这些skip算作PG通过。

Ruff对6个改动Python文件检查通过，6个文件格式检查通过；JSON、Markdown本地引用和 `git diff --check` 已核对。当前产品核心、workflow、依赖/迁移没有差异。工作区SHA、断言审计和本地提交记录存于同一忽略目录；原始失败和先前阶段日志没有覆盖。

## 可直接接续的PG验收

先恢复Docker，并配置原有CI/portable_pg支持的**全新隔离PG17+pgvector测试实例和完整用途角色**。不要只开启DB测试开关后读取项目 `.env` 指向用户库。不得删除现有数据库、Volume或历史Run。

经隔离配置验证后，分别用Python3.11/3.13执行下列同一有界集合，保存新JUnit与日志：

```powershell
python -m pytest -q -p no:cacheprovider `
  'tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[summary-completed]' `
  tests/test_document_fact_postgres.py::test_real_pins_and_scope_cannot_be_forged `
  'tests/test_phase4_postgres.py::test_compacted_durable_restore_keeps_known_results_or_blocks_unknown[None]' `
  'tests/test_host_goal_postgres.py::test_legacy_requirement_manifest_is_not_silently_reinterpreted[bge]' `
  --junitxml=<新的本地结果路径>
```

四项实际通过后，再决定扩大迁移。随后必要补验包括预算 `[model_response]` 的unknown分支、`[tool_committed]`复用、Web其余purpose，以及其他尚未迁移的Required/Supplement、Partial Evidence和引用验证。任何真实安全失败都停止扩大范围，不修改核心绕过问题。

## 剩余风险与准入判断

- 四项真实PG/MCP代表验收尚未执行，不能证明正式HTTP确认后的检索分数、事实覆盖、Ledger或跨进程恢复全部通过；当前**不具备直接扩大到60项或完整远端矩阵的验收依据**。
- Web参数化其他3种purpose、预算其他2个cut点、Qwen旧版本拒绝臂均未实测。可收集性不是成功执行。
- 本轮没有迁移所有59项A类失败。原legacy Web拒绝码、低信任语义入口、其他Host fixture仍按上轮归因保留，不宣称CI全绿。
- 独立人工质量审查、真实模型质量、Qwen资源验收和P7后续Gate不在本次范围。
- 没有生产API变化、第二套确认/恢复框架、P3/Report/Durable改动、检索参数调整或历史Gold/Seal/STOP修改。

完成本地独立提交后停止。未自动push、合并main或触发远端CI；原归因报告仍保留为本地未提交文件。
