# P7 Phase 2C.4 Batch-Safe Handoff

**最终状态：BLOCKED，硬安全 STOP 已触发。下方早期执行入口和在途快照仅作历史记录，全部被文末最终交接取代；不得继续 batch/one、另一个配对臂或任何新 Runtime。**

## 历史：首次预登记快照

当前阶段：输入/Gold已冻结，首个正式Batch尚未启动；无付费调用，不修改v3/阈值/历史记录。

- 分支 p7-ci-verification-20261028，HEAD f8b122438d2c67ab26e618ecded72ecc18454015；全部既有未提交修改保留。
- 数据与Gold SHA `9d689ae660a3416ad31cb2945f6eff186d184d54341a312c7214660ab5f5e226`。
- 初始数据预登记 SHA `55ee2e2387adddbb3e3ef40d5b5c14b9563422ba1f472983152bddcfc3d5cf40`。
- 最终执行清单 SHA `037948a38cb09c51bef87151315ebe12f188a824607c2743e2d326e1944b8f89`；首版兼容清单/执行包装快照保留，仅修正Windows采样路径和独立入口STOP守卫，未改Gold/Scorer。
- 模型/200个IndexVersion/原件/SQL/Metric绑定 SHA `1610ab0541c7353c013876b87bb16a9617105ffe2890426a114ab9ef4fe3f16c`。
- 新正式库 datapilot_test_fresh_validation_v3_20261030；新回归库 datapilot_test_fresh_controls_v3_20261030。不清理、不Seed、不写旧库。
- `artifacts/p7/fresh-validation-v3/` 保存 preflight.json、10份原P3 verified预检、独立性审查、源文件、输入草案、日志/失败历史；私密env与collector key不公开。
- 双版本417项定向回归通过；新控制库PG准入12项通过，兼容回归另见 controls/compatibility-pg311.xml。不能把控制测试算作100条质量任务。

## 历史：停止前的正常顺序（现已禁止执行）

仓库根目录执行，每批前必须检查 STOP/stopped.json、冻结Source、上一批seal和原始score。若任何硬安全/unknown/身份/预算/评分异常，禁止新派发，转只读交付。

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -u -m evaluation.qwen_fresh_validation.runner batch --index 0
.venv/Scripts/python.exe -m evaluation.qwen_fresh_validation.summarize --index 0
```

上一批complete/offline_equal=true且stopped=false，才对index1/2/3/4分别执行同样两条命令。先读取现有日志/JUnit/进程，不重复启动任何已有批次。batch manifest或dispatch已存在时禁止重新运行相同batch/one覆盖结果；若中断到未完成状态，先依据签名collector/调用状态只读对账；未确认的调用不得重发。

任何情况下不重新运行old Phase2C2的125 not_run。独立Validation不得看结果后改产品/Gold/Scorer/阈值。最高200观测，planned100/arm，固定20 Dev/80 Validation，各类10。

## 已知限制与异常

AI作者而非独立人工盲审；近似与事实结构依赖详见 independence-review/adjudication.json。十个新SQL样本共享同一paid-invoice配方，不能叫十种独立算法。新的225个文档完整正文均独特，无共享噪声原件。最初Qwen模块导入/预检脚本导入失败均在任何正式Runtime前，原日志保留；没有自动重跑已执行任务。GPU遥测缺失必须null，不复用旧测量。

## 交付

每批即刻离线复评/保存JUnit及seal。结束或STOP后产出 p7-qwen3-phase2c4-fresh-validation.md/.json、性能/资源分阶段统计、全部失败/200状态、P3/Artifact/账本只读审计、历史1872及新增C3 seal完整性，最终Source/结果seal。STOP后不再启动PG/业务Runtime，只读封存。

NEXT SESSION PROMPT：继续本轮Phase2C.4，先读用户附件524be623与本交接及实际日志。保留全部修改，先收集已有批次，不重复启动。核对canonical registration.json与registration-r2.json身份；继续仅未执行且明确可安全派发项。若STOP存在，绝不续跑，完成只读审计交付。无付费、不切BGE、不改产品/Gold/Scorer/旧记录、不提交推送、不进入Gate3。

## 准入前修订说明

首版 fresh-validation-v3 在正式 Runtime=0 时撤回，因独立AI审查发现fr008/fr081要求政策理由而原件仅有规定。原Gold/225文档/200索引/10P3预检及清单全部保留；没有任何评测结果驱动修订。活动输入现在为 cases-r2.json，活动输出 artifacts/p7/fresh-validation-v3-r2，新正式库 datapilot_test_fresh_validation_v3r2_20261030。原问题、状态、类别及Scorer均不变，仅两份文档及其事实引用补充明确的规范性理由；不是经验因果结论。新数据/实现冻结与绑定按活动目录为准。之前记录的旧路径SHA属于初稿，不是当前身份。正常CLI模块名不变，未来Batch实际OUT由common.py绑定r2。

## 历史：活动执行在途快照（已结束）

活动版本r2，Batch0正在运行，已落盘17/200个score；先收集61933对应的工具会话及 `batch-0-runner.log`，禁止重复启动。活动Gold SHA `a5c035b73726a6b511b39235263e9f030993f96fd481b3ec08325c18438f05e8`，数据Seal `b8d38c07aa23a1af1c256f9257e0faeb76ef45ab42ddbf8e869faec146973abd`，实现 `b2ea43d0c9cd09dab252238e9103f850cbbecbea653e128fac853b53f729440b`，绑定 `16fbb2badc5987d97f088b84e9060b69e85ab6a562ff186e45df2baf4f7ff7fc`。STOP以活动目录实际文件为准。本段为在途快照，后续可能已结束/停止；继续前必须读取实际状态。

## 最终交接：硬安全 STOP，禁止续跑

停止时间 `2026-10-30T11:14:30.175374+00:00`（北京时间19:14:30）。活动目录为 `artifacts/p7/fresh-validation-v3-r2/`，`stopped.json` 保存 fr002/Qwen 的三个标签：`unsupported_fact_or_citation`、`false_completed`、`unsupported_retrieval_goal_completed`；这是一个安全失败观测，不是三起独立事故。

- 全部200个计划观测：21 observed、179 not_run；21个实际Runtime，预执行拒绝0。Dev 21/40，Validation 0/160。Batch0未完成，Batch1–4未启动。
- BGE 8/10严格正确、90 not_run；Qwen 10/11严格正确、89 not_run。十个完整配对为8都对、2仅Qwen对；另有未配对的fr002/Qwen错误完成，不能从安全结论中删去。BGE同题从未派发。
- 已独立离线复评21条，与运行时评分完全一致。Batch0 JUnit为18 passed、3 failed、19 skipped（not_run），不能写成整批通过。
- 最终冻结源码定向回归Python3.11/3.13各417 passed；独立控制库真实PG/MCP为12 passed及4 passed。控制测试不加入21条业务分母；完整pytest/远端CI/付费Live本轮未运行。
- 正式库21 Runs、21 Ledgers、128 Calls、44 Artifacts、405 Events；调用complete，无issued/uncertain、无pending预留。44工件Hash有效。12份P3验证中10份是数值预检，仅2份属于正式业务任务。
- 问题在共享Host Goal将尚未确认的规则集合默认为bounded。真实引用/有效Hash/高相关性不证明目标充分；不属于Qwen越权或引用伪造。没有修改产品或热修复后续跑。
- Gate A FAILED；Gate B/C缺完整Validation，未建立。当前不具备下一轮DeepSeek Live申请条件。默认BGE不变，不表示其对未执行同题安全。

当前分支和HEAD保持开头所列值；所有原有未提交修改保留，本轮无commit/push。活动Gold/数据/实现/绑定SHA沿用上段r2值；结果文件另由活动目录`result-seal.json`封存。新评测文件在`evaluation/qwen_fresh_validation/`、`tests/test_qwen_fresh_validation.py`；交付在本文件及同目录`p7-qwen3-phase2c4-fresh-validation.md/.json`。

关键只读记录：`summary-batch-0.json`、`batch-0-results.json`、`batch-0-seal.json`、`batch-0-business-quality.xml`、`batch-1-not-run.json`至`batch-4-not-run.json`、`post-stop-quality-audit.json`、`telemetry-summary.json`、`database-final-audit.json`、`historical-integrity-final.json`、`withdrawn-initial-revision-audit.json`。单元日志/JUnit为活动目录`regression-py311.*`和`regression-py313.*`；PG控制日志在原目录`artifacts/p7/fresh-validation-v3/controls/`。原始失败、旧Gold/Seal和初版零正式Run的数据均保留。

只读核对命令（仓库根目录；不是续跑入口）：

```powershell
Get-Content artifacts/p7/fresh-validation-v3-r2/stopped.json
Get-Content artifacts/p7/fresh-validation-v3-r2/batch-0-seal.json
git status --short
git diff --check
```

不得重启batch0、手工派发fr002/BGE、启动batch1–4、清库或重新摄取。后续若修复Host Goal，应取得独立授权、冻结新实现和新验证方案；不能把新结果合并到本次停止实验。是否复用未观察题集也需另行决策。

**NEXT CODEX SESSION PROMPT**：继续DataPilot Pro时先阅读本文件最终STOP段和`docs/research/p7-qwen3-phase2c4-fresh-validation.md/.json`，核验活动`stopped.json`、`batch-0-seal.json`和`result-seal.json`。Phase2C.4已因fr002/Qwen错误完成安全停止，21/200 observed、179 not_run，Validation未启动；严禁恢复当前Campaign或派发另一臂。保留全部未提交修改、原始失败、Gold/Seal/Run及数据库，不调用付费模型、不改默认BGE、不提交推送、不进入Gate3。若无新的明确修复授权，仅汇报已有证据；Host Goal范围确认修复及新独立验证须另获授权，不能只补该句型或重用旧实验刷分。
