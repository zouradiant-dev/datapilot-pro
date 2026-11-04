# CI Final Migration：31 项推送后双版本真实验收

2026-11-01。**本批31项全部通过；原CI #22的60个失败身份已累计获得双版本真实PG通过证据。NOT FULL CI，完整统一回归仍为 NOT_VERIFIED。**

本记录更新[本地迁移报告](p7-ci-final-migration.md)及[当时Handoff](p7-ci-final-migration-handoff.md)的推送前快照，不覆盖历史 NOT_RUN/等待批准，也不将原 #22/#25 的失败改写为成功。

## 授权、提交与运行身份

- 本次明确授权只推送 `2f2f1694525cf2d677d9df13a449090836f1e731`，分支 `p7-engineering-candidate-v1`。
- 推送前本地HEAD、父提交、GitHub远端基线 `b3328e003cf5e1fc997c28c2228bf23209562699` 与14文件白名单逐项匹配；工作区已跟踪文件干净。
- 一次普通 fast-forward Push；七份旧未跟踪报告与忽略工件未上传，没有Force Push、Rebase、合并main或追加提交。
- 推送后及交付前远端仍为上述目标提交；main仍为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`。
- [Actions #27 / Run 41297581713](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41297581713)，名称 **DataPilot CI Final Migration — 31 Cases — NOT FULL CI**，push事件、attempt 1、结论 **success**。
- UTC **2026-11-01 10:27:42–10:33:45**；北京时间18:27:42–18:33:45。没有重跑、修复提交或第二轮实验。

## 真实结果

| Python | Job | 完整非集成回归 | 精确PG/MCP集成 | PG JUnit耗时 |
|---|---|---|---|---|
| 3.11 | [124821577143](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41297581713/job/124821577143) | **1336 passed / 0 failed / 0 errors / 0 skipped** | **31 passed / 0 failed / 0 errors / 0 skipped** | 265.802秒 |
| 3.13 | [124821577357](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41297581713/job/124821577357) | **1336 passed / 0 failed / 0 errors / 0 skipped** | **31 passed / 0 failed / 0 errors / 0 skipped** | 258.842秒 |

非集成JUnit耗时分别32.105/34.860秒。两版PG的31个Node ID及顺序均与预冻结清单完全一致，无额外、缺失或被替换身份。没有运行全量PG集成矩阵。

两版初始化日志确认 **PostgreSQL 17.11 (`170011`)、pgvector 0.8.6、迁移0008、BGE pinned_model_verified**；使用GitHub Actions各Job的新隔离服务及原角色/Schema初始化，非历史数据库。锁定依赖、全测试收集、Ruff、格式、coverage/JUnit上传及服务清理均success。

这是实际PG/MCP/本地Embedding及脚本/Fake Worker的工程验收，不是付费DeepSeek或自主推理业务质量评测，也不是浏览器Smoke。

## 两项低信任入口专项核验

| 原#22编号 / 精确Node | 3.11 | 3.13 | 源码绑定下实际执行的断言 |
|---|---:|---:|---|
| 58 `tests/test_rag_completion_postgres.py::test_real_semantic_retrieval_checks_original_goal_not_model_search_keywords[True]` | passed，2.416秒 | passed，2.497秒 | 同原问/同模型查询的旧run_question必须blocked且提交insufficient；正式Host确认后Coordinator路径保留semantic_retrieval、completed、原目标/来源Hash、相关性及错目标/篡改拒绝。 |
| 59 `tests/test_rag_completion_postgres.py::test_committed_rag_control_restores_across_process_without_duplicate_calls[semantic-rag_submission_committed-3]` | passed，15.119秒 | passed，15.233秒 | 无确认独立Run必须blocked、无succeeded任务；已有run_durable(report_scope)正向路径在原cut-point后恢复，仍为3次模型调用、1次成功搜索、0次额外纠正，重复resume的结果/usage/调用记录不变，语义Receipt与引用存在且不宣称业务因果verified，Trace无原文泄漏。 |

没有给产品run_question新增确认能力或签名参数；没有自动Attestation。Scope由公开合成测试Host通过原正式接口显式确认，不冒充独立人工审查。

证据来自两个无skip成功JUnit、实际精确命令，以及完整637个提交源码文件的字节SHA核对；上述中间断言结果未另行导出为数据库快照，因此不伪造额外Ledger/Receipt签名包。预算和恢复断言通过由实际测试执行证明。

## 60项原失败的累计证据

重新读取原#22身份清单和#23–#26每版实际PG JUnit，按原Node ID取双版本passed交集，再与本次31项连接；没有仅依据旧报告标量相加。#24原通过的P3控制不计入60个原失败分母。

| 定向运行 | 本次新增原失败身份通过数 | 累计 |
|---|---:|---:|
| #23 | 4 | 4 |
| #24 | 10（另1项P3控制不计） | 14 |
| #25 | 14；原1项failed保留 | 28 |
| #26 | 1 | 29 |
| #27 | 31 | **60/60** |

全部60个唯一原失败身份均有Python3.11和3.13的真实passed证据，无重复凑数，待迁移原失败0项。逐项Node/原编号/证据Run/双版状态保存在新目录的 `case-statuses.json` 和 `progress.json`。

这是**跨多个定向Run和提交的累计证据**，不是一次在最终HEAD执行全部60项，更不是全量集成通过。原#22的265项原通过测试及其他完整矩阵仍需在最终HEAD统一回归。

## Artifact、源码及历史保护

完整本地证据：`artifacts/p7/ci-final-migration-actions-v1/`。

| Python | Artifact ID | ZIP SHA256 |
|---|---|---|
| 3.11 | 13079647841 | `198cb420d34f77ca11771c12bddb8fec76794c3f17546d0274abc64226030941` |
| 3.13 | 13080465383 | `4c392ecad15284a5546154db71ea9b4b4e1c45caa562b37955204d2b28d558e2` |

两份完整Job日志、ZIP与解包后的JUnit/coverage/初始化/依赖/静态/源码清单均已保存。ZIP实际SHA与GitHub digest一致，解包检查路径/大小/符号链接；两版 `commit.txt` 一致，`test-scope.json` 均为 `ci-final-migration-31 / planned_pg_tests=31 / full_ci=false`。

**每版全部637个源码文件SHA与原始Git blob完全一致**，未用Windows CRLF工作副本代替Linux字节。原assert/raises保留审计与本次匹配源码相符，未通过改变Gold、预期状态、预算或测试范围获得绿色结果。

新机器记录包括 `verified-results.json`、`history-reconciliation.json`、`case-statuses.json`、`progress.json`、`delivery-validation.json` 与 `RESULT-SEAL.json`。原历史工件及先前本地封存文件149份在开工和交付时保持原SHA；完整性限于实际检查的文件与Git范围，不冒称历史数据库全量复验。

本轮产品核心、测试、workflow、依赖、Goal/P3/Report/Durable、Embedding、旧Gold/Seal/STOP均未修改；没有调用付费模型、触碰历史Docker、访问用户数据库或重新运行历史测试。只新增本地交付与忽略的核验工件，不自动提交或推送这些结果。

## 完整CI恢复条件与停止

**具备申请恢复完整CI的工程前提**：原60项失败契约迁移已全部取得双版本定向真实PG证据，本次非集成与静态全绿，没有本次失败需要归因。

下一步须另获明确授权，再恢复原完整PG/MCP测试命令，移除临时31项Node选择器；保留全非集成、HTTP/RAG/P3/Report/Durable、Python3.11/3.13、锁定依赖、角色/迁移/隔离服务、Ruff/format、JUnit/coverage/失败上传，以及原Qwen/CUDA/付费Live的opt-in条件。不能用本次31项或累计60项代替完整矩阵，也不能承诺全量回归一定成功。

**31项定向CI：PASS；Low-trust Compatibility：PASS（已验工程范围）；累计原失败：60/60；GitHub Push：COMPLETED；Full CI：NOT_VERIFIED。** 本轮到此停止，没有自动启动完整CI或下一阶段。
