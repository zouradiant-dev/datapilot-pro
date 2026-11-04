# CI #22迁移：Actions #23四项代表验收

**代表性工程Gate通过；不是完整CI通过。** 本轮按用户明确回复“确认本次定向推送”执行一次推送，没有二次push、rerun或合并main。

## 提交与执行身份

- 分支：`p7-engineering-candidate-v1`。
- 已推测试迁移提交：`645be24a18870f3cbce570e18dede610f891cafa`。
- 本次单文件CI提交：`25a44c2325889e393d76df960d3ff47452740944`，仅 `.github/workflows/test.yml`，5行新增/3行替换。
- [Actions #23 / Run 41276968565](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41276968565)，push / attempt 1，`completed / success`。
- 工作流：`DataPilot CI22 representatives - NOT FULL CI`；两个Job均为 `ci22-representative`，上传的 `test-scope.json` 为 `full_ci=false`、`planned_pg_tests=4`。
- 开始/结束：2026-11-01 13:26:40–13:29:56（Asia/Shanghai；UTC 05:26:40–05:29:56）。
- 推送后通过GitHub API确认候选分支指向上述新提交；main仍为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`。

推送包含原645be24的8个测试/公开夹具/交付文件和本次workflow文件，没有推送本地Docker恢复、CI归因或后备方案记录。预检曾将Windows CRLF原始补丁Hash与LF计划Hash直接比较而安全停止；随后确认规范化LF内容逐字节等于已批准补丁，保留两种Hash，没有修改补丁内容来绕过校验。

## 真实结果

| Python | 非集成 | 本轮真实PG/MCP代表 | 集成pytest耗时 | Job |
|---|---|---|---|---|
| 3.11 | 1331 passed / 0 failed / 0 skipped | **4 passed / 0 failed / 0 skipped** | 95.56秒 | [124760994006](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41276968565/job/124760994006) |
| 3.13 | 1331 passed / 0 failed / 0 skipped | **4 passed / 0 failed / 0 skipped** | 86.61秒 | [124760994193](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41276968565/job/124760994193) |

这是四个独立测试在两个Python环境重复验证，不是八个新业务Holdout任务。模型决策为Fake/脚本；PG17、pgvector、MCP、持久存储及FastAPI TestClient协议是真实基础设施。不声称验证了真实DeepSeek推理或新的浏览器Smoke。Provider Key为空，Live关闭，付费调用0。

两版锁定安装、完整测试收集、非集成测试、隔离PG初始化、固定BGE文件验证、Ruff、格式与always上传均成功。GitHub服务是每个Job新建的隔离实例，无用户历史数据库或Volume绑定；本机Docker及历史VHDX未使用。

## 四个精确用例及保留的断言

两版JUnit实际身份和以下顺序逐项一致，无skip、重试或替换：

1. `tests/test_document_confirmation_postgres.py::test_confirmed_document_purpose_survives_chat_review_and_durable[summary-completed]`：简单confirmed请求被拒；通过原HTTP精确Goal合同确认事件创建Run；独立Journal审批后执行；重复确认关联同Run，原报告和历史保持。
2. `tests/test_document_fact_postgres.py::test_real_pins_and_scope_cannot_be_forged`：真实有效原件首先completed且有事实覆盖；原四类Citation/source/version/hash篡改必须抛异常，错误Owner仍拒绝。
3. `tests/test_phase4_postgres.py::test_compacted_durable_restore_keeps_known_results_or_blocks_unknown[None]`：真实跨进程pause/resume；错IndexVersion拒绝；重复恢复不调用模型、报告/usage不变，调用记录不变，原五次Fake调用与搜索/读取次数断言成立。
4. `tests/test_host_goal_postgres.py::test_legacy_requirement_manifest_is_not_silently_reinterpreted[bge]`：使用公开legacy JSON而非私密源码启动新的测试Run；当前身份恢复返回RECOVERY_IDENTITY，持久快照不变。

第3项只覆盖 `[None]`，**没有执行 `[model_response]` unknown-outcome或 `[tool_committed]` cut-point**；不能从本次4/4推导所有故障恢复已通过。Web其他purpose和Qwen臂也不在本次集成集合。

## 工件与完整性

| Python | GitHub Artifact ID | ZIP SHA256 |
|---|---|---|
| 3.11 | 13071023999 | 2215f759ac5c5fdf4dbd848f6e1e9cb782e2faa695851c1f26f6bbea1651efcd |
| 3.13 | 13072070343 | e45f183d0a3713dd6b2ad03dc3cb97588e40490961675e1c60953bf29d574e1a |

原ZIP、两份完整Job日志、解包JUnit/测试日志/初始化记录/源码清单和逐Case机器记录保存在忽略目录 `artifacts/p7/ci22-actions-representative-run-v1/`。`verified-results.json`给出真实数量、身份和通过判定；`push-verification.json`、`preflight.json`保存推送范围及审批依据。

实际核验：GitHub ZIP digest匹配；两份 `commit.txt`匹配25a44c2；两份scope均标明非完整CI；四个JUnit Node ID与冻结清单精确相等；对16个关键工作流/测试/夹具/Goal/Report/Journal/Durable/Host文件，比对Linux源码SHA与该提交Git blob SHA256，一致。

通过的恢复/审批/引用断言是实际pytest执行证据。不过测试子进程的完整Run快照留在临时目录，未全部加入原上传路径；本轮不能提供未上传的逐Run调用包或虚构Run ID，也不在CI完成后重建数据库追造证据。原断言与JUnit、源码身份一起保留。后续如需额外离线审计，可只增加有界脱敏测试摘要，避免导出原始Prompt、业务行或凭据。

## 剩余失败与下一步

原#22每版60 failed / 265 passed / 63 skipped为历史结果，保持原值。本轮只真实证明这四条迁移代表通过；**其余失败没有在#23执行，不宣称剩余56项均通过或给出未经执行的新失败数**。

本轮满足开始下一批迁移的工程前提。按已授权CI主线，后续应分批处理其余A1 Web确认与拒绝入口、A2有限Host/RAG合同、A3引用负例、A4预算恢复和A5低信任入口的测试构造，保留真实安全断言，不改Goal v4/P3/Report/Durable。历史Docker恢复不再是前置条件。

下一次推送仍需负责人确认。本次“一次定向推送”的授权不延用于后续提交、重跑或扩大测试。后续批次验证后必须撤回临时四项选择和NOT FULL CI名称，再跑原完整双版本矩阵，才可宣布候选分支完整CI通过。当前临时工作流保留在候选分支，不合并main。

本报告仅在本地保存，未再次commit/push。旧Gold/Scorer/Seal/STOP和历史数据库未改，未调用付费模型或开展新P7业务实验。
