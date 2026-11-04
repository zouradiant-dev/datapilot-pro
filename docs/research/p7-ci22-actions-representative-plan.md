# CI #22：Actions隔离PG定向验收计划

2026-11-01。本轮主线恢复为修复候选分支完整CI。停止Docker历史盘调查、备份准备及恢复；既有诊断记录保留，不把历史数据恢复作为CI前置条件。

## 当前实际状态

- 分支 `p7-engineering-candidate-v1`，HEAD `645be24a18870f3cbce570e18dede610f891cafa`，比本地origin记录领先1个提交，未推送。
- 已有迁移成果：最终Python3.11/3.13各25 passed，原日志/JUnit在 `artifacts/p7/ci22-contract-migration-v1/final/`，本轮没有无故重复执行。
- 本轮分别检查 `desktop-linux` 与 `default` 两个既有Docker端点；Server均null，分别缺少 `dockerDesktopLinuxEngine`、`docker_engine` 管道。因此没有创建本地PG、访问既有Volume/数据库或执行四项真实PG测试。应用能显示窗口与Engine可用性不同，本轮不继续调查Docker。
- #22原60 failed / 265 passed / 63 skipped（每版本）继续作为原始结果保留。没有新PG成绩，不能推断已有提交已修好全部失败。

## 最小后备方案：现有Actions服务，临时且明确的代表模式

完整可审阅补丁保存在本地忽略目录：

`artifacts/p7/ci22-actions-representative-plan-v1/representative-workflow.patch`

其SHA256为 `ac254a382378b0d26d4e054050aab69de58a121446eac41a33d0e1fa612f6d81`。候选完整YAML、四个Node ID和机器计划分别为同目录 `test.representative.yml`、`nodeids.json`、`plan.json`。**补丁未应用，也未提交或推送。**

补丁仅修改原 `.github/workflows/test.yml`：

1. 工作流名称标注 `DataPilot CI22 representatives - NOT FULL CI`；Job名称改为 `ci22-representative (Python版本)`，不冒充原完整检查。
2. 原身份采集步骤新增 `test-scope.json`，记录 `scope=ci22-representative`、`full_ci=false`、`planned_pg_tests=4`。
3. 原集成pytest调用增加四个精确Node ID，保留 `python -m pytest`、`-m integration`、JUnit、coverage与所有既有参数；不改测试或断言。

原PG17/pgvector镜像及digest、用途角色、服务网络、临时存储、迁移/runtime初始化、全体非集成测试、测试收集、Ruff、格式与always()上传全部保留。每个Actions矩阵Job使用自己的新服务实例；不绑定用户VHDX、历史Volume、旧Run/Journal/Ledger或项目 `.env`。Provider Key为空，Fake模式，Live关闭。原服务在隔离runner内初始化/Seed只作用于新CI数据库，不是用户库。

这是临时的有界验证方案，不是删测试、放宽完整CI门槛或发布准入。部分模式通过后，必须恢复完整工作流再做最终矩阵；不能把四项成功记成完整CI绿。

## 触发方式与下一次推送范围

当前工作流仅有push/pull_request。旧Run #22绑定 `607e68c`，rerun无法执行本地 `645be24`。不使用旧Run成功伪装当前代码验证。

不以新增workflow_dispatch作为本轮捷径：GitHub要求手动触发工作流位于默认分支，本轮不需要改main。沿用候选分支既有push触发，GitHub按推送关联ref的工作流执行。[手动触发要求](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)、[工作流与事件ref](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflows)

下一次推送需负责人明确确认，具体范围为：

1. 重新核对HEAD与补丁基线；应用上述单文件补丁，复核Diff与现有工作流契约。
2. 创建独立本地CI配置提交；仅推送 `p7-engineering-candidate-v1`，包含现有645be24及临时定向配置。原本地归因/恢复诊断记录不顺手纳入。
3. 不合并main、不force push、不创建付费实验；监视新Run，下载两版完整日志/JUnit、源码身份与scope文件。
4. 四项PG必须每版 **4 passed / 0 failed / 0 skipped**，并核验实际测试身份和断言执行。仅收集成功或skip不算通过；整体工作流即使success也只表明代表模式通过。

## 四个冻结用例

```text
tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[summary-completed]
tests/test_document_fact_postgres.py::test_real_pins_and_scope_cannot_be_forged
tests/test_phase4_postgres.py::test_compacted_durable_restore_keeps_known_results_or_blocks_unknown[None]
tests/test_host_goal_postgres.py::test_legacy_requirement_manifest_is_not_silently_reinterpreted[bge]
```

分别检验真实HTTP目标确认与独立执行审批、有效原件控制后Citation篡改拒绝、预算/持久恢复/版本拒绝、公开legacy identity的不兼容恢复拒绝。所有原有断言保留；本轮未修改这些测试。

## 本轮已运行的验证

候选YAML复用原 `tests/test_ci_workflow.py` 的5个原始测试函数，另验证：

- 候选env与services和原工作流完全相等，无用户Volume挂载；四个精确测试参数之外，其余集成pytest参数逐项不变。
- 工作流/Job名称及scope工件明确说明不是FULL CI。

本地候选配置检查：Python3.11 **7 passed，0.65秒**；Python3.13 **7 passed，0.60秒**，均非PG测试。JUnit为同目录 `contracts-311.xml`、`contracts-313.xml`，完整日志保留。`git apply --check`通过，实际工作流文件未改变。这些检查不能替代Actions服务启动或四项PG执行。

## 代表测试通过后的分批迁移顺序

以下本轮暂不实施，避免跳过真实PG门槛：

1. A1：其余Web旧创建/历史授权/拒绝码用例，走合法Host/HTTP事件；保留legacy请求拒绝与独立审批，不给Outbox手写授权。
2. A2：有限公开Host/RAG合同，在最终Dataset/Metric/Source/policy固定后显式确认。未知范围、缺事实、因果及越权负例保守，不做全局自动Attestation。
3. A3/A4：继续引用篡改、Required/Supplement、Partial Evidence、预算与跨进程cut-point；包含unknown-outcome不重发和账本不变。确认后若仍有安全错误，单独归因为真实缺陷，不弱化断言。
4. A5：旧run_question保持低信任；语义正向控制使用已有Host/Coordinator，不改产品API或改成literal查询绕过语义。
5. 各批代表通过后，撤回临时工作流范围限制，恢复原完整测试命令/名称，执行Python3.11/3.13完整非集成与集成矩阵。是否真正全绿以新Run完整JUnit为准，不用旧CI或代表模式替代。

本地Docker仍不可用时，分批执行继续复用同一Actions临时PG机制；每次远端推送均在负责人授权范围内，不以恢复历史Docker为依赖。

## 交接状态

| 项目 | 状态 |
|---|---|
| 本地迁移提交645be24 | 已核对，未推送 |
| 原25项合同回归 | 两版已通过，源码未变化，结果复用 |
| 新后备配置合同 | 两版各7 passed |
| 四项真实PG | NOT_RUN |
| 剩余旧测试迁移 | 等待四项真实验收，不盲目扩大 |
| 新GitHub Run | NOT_RUN，尚无推送确认 |
| 产品核心/历史数据/冻结内容 | 未修改或访问 |
| Docker历史恢复 | 已停止，记录保留 |

当前真正的下一步是确认一次有界候选分支推送以取得四项PG证据，而不是恢复旧数据盘。完成代表门槛后再扩大迁移，最终目标仍是原完整Actions双版本通过。
