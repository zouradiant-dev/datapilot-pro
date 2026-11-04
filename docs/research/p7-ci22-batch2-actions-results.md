# CI #22 Batch 2 — Actions #24 真实定向验收

**Batch 2 PASS；NOT FULL CI。** 仅推送已审查的一个提交，没有补提交、第二次推送、失败重跑或合并 main。

## 执行身份

- 分支：`p7-engineering-candidate-v1`。
- 推送前通过 GitHub API 核对远端基线 `25a44c2325889e393d76df960d3ff47452740944`。
- 实际推送 Commit：`be880d1415f6d5069c914a09417732f5d501805e`。
- [Actions #24 / Run 41278805564](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41278805564)，push / attempt 1，`completed / success`。
- 工作流：`DataPilot CI22 Batch 2 - NOT FULL CI`；两份 scope 均为 `ci22-batch2`、`full_ci=false`、`planned_pg_tests=11`。
- 起止：2026-11-01 13:56:10–14:01:18，Asia/Shanghai（UTC 05:56:10–06:01:18）。
- 结束后再次通过 GitHub API 核对候选分支为 be880d1；main 仍为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`。

实际提交仅为既有六个测试文件、定向 workflow 和两份 Batch 2 交付记录。原五份未跟踪 Docker/CI 本地记录没有纳入提交。本轮没有 Git add/commit、Force Push、Rebase 或其他分支写入。

## 下载后核实的真实结果

| Python | 非集成回归 | 真实 PG/MCP 定向集成 | 集成 pytest 耗时 | Job |
|---|---|---|---|---|
| 3.11 | **1332 passed / 0 failed / 0 skipped** | **11 passed / 0 failed / 0 skipped** | 199.196 秒 | [124766306058](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41278805564/job/124766306058) |
| 3.13 | **1332 passed / 0 failed / 0 skipped** | **11 passed / 0 failed / 0 skipped** | 158.644 秒 | [124766305872](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41278805564/job/124766305872) |

安装、完整收集、非集成回归、PG/角色/迁移/运行时初始化、固定 BGE 校验、Ruff、格式和 always 上传均成功。两份 health 实际记录 PostgreSQL `170011`、pgvector `0.8.6`、迁移 `0008`、`pinned_model_verified`。数据库来自每个 GitHub Job 新建的服务容器；没有历史数据盘或用户数据库挂载。

模型决策为 Fake/脚本；数据库、CPU Embedding、MCP 子进程、FastAPI TestClient/ASGI HTTP 和 Durable 链路是真实执行。Provider Key 为空、Live 关闭、付费调用 0。不是新的浏览器 Smoke、真实 DeepSeek 推理或业务 Holdout。

## 11 项逐项断言验收

精确 Node ID、参数、顺序均与已批准清单相等；以下每项两版均 passed，没有 skip、替换、重试或减少断言。

| #22 原 ID | 测试/参数 | 实际保留并通过的业务与安全断言 |
|---|---|---|
| 1 | `test_corpus_listing_cap_must_not_revoke_existing_run_authority` | HTTP 合同确认后，第 101 个真实 Corpus 即使不在列表预览中也保留 Run 授权；精确查询有效；新测试 pin 的 hash 损坏仍抛异常 |
| 21 | `test_legacy_creation_and_source_injection_do_not_grant_confirmation` | legacy 缺 Goal 确认被拒；当前 HTTP proposal 对未知 Corpus 返回 WEB_SCOPE；非法 document_ids 返回 422；没有创建 Run |
| 60 | `test_real_document_upload_retrieval_report_and_source_ref` | 原完整问题、Dataset/Metric/Semantic/窗口不变；HTTP Goal 确认与 Journal 审批分开；真实上传/Embedding 和来源 SHA；报告 completed；公开 Trace 无正文/SQL且明确 Mock |
| 2 | `test_real_policy_report_terminal_reuse_preserves_citations_p3_and_budget[cp09]` | Required/Supplement 引用生效；completed；重复恢复后报告、usage、Artifact/调用/账本快照相同 |
| 3 | 同上 `[cp07]` | Supplement 不补齐缺失 Required 事实；保持 partial，documents 不标 verified；P3 指标与 Verification 仍 verified；终态重复恢复无变化 |
| 4 | `test_new_policy_survives_cross_process_cut_without_model_reissue[rag_submission_committed]` | 真实子进程在提交后退出，恢复 completed；无新增模型调用/预算消耗，原 Artifact 不变 |
| 5 | 同上 `[report_artifact_committed]` | 报告工件提交后退出，恢复保留补充引用；调用、预算和已有工件不被重复处理 |
| 6 | 同上 `[checkpoint]` | 真实 pause/resume，补充引用保持；原模型调用、预算和工件保持 |
| 48 | `test_real_partial_receipt_report_and_terminal_cross_process_reuse[cp04]` | 缺 Required 来源/赔付事实仍 insufficient/partial；已有事实可保留，documents 不升级 verified；重复恢复无调用或账本变化 |
| 49 | 同上 `[cp06]` | 缺离线规则仍 insufficient/partial；真实局部事实覆盖保留，引用与恢复快照不变 |
| 原通过控制 | 同上 `[cp07]` | 文档送达保证不足仍 partial；P3 数值与 Verification 保持 verified，单位 CNY，Evidence/Verification ID 存在；恢复不重复计账 |

这些结论来自实际 pytest 断言成功、JUnit 身份与该提交源码的联合核对，未把「执行步骤显示成功」代替断言检查。测试子进程完整私密 Run 快照没有另外上传，不能提供不存在的离线逐 Run 数据包或虚构 Run ID。未知外部模型响应的恢复场景不在本批 11 项内，不能由本轮结果扩张保证。

## 工件及源码身份

| Python | Artifact ID | ZIP SHA256 |
|---|---|---|
| 3.11 | 13072910114 | `3b60d9a1d23ed0c2af8ec70a0d8a4b29511b52c3201cce412dfbcd43a2268738` |
| 3.13 | 13072133671 | `ee4c23c6d595debff61b57f919a74783db8fb4b48d56965a7583386ccd2343f7` |

下载 ZIP 摘要均匹配 GitHub Artifact digest；`commit.txt`、scope、全部 JUnit 用例身份逐项匹配。两份 `source-sha256.txt` 各 **629 个路径与 SHA**，全部精确匹配 be880d1 的原始 Git blob；不是比较 Windows 工作区换行后的文件。

本地核验辅助脚本第一次使用 Windows `git archive`，其文本导出应用 CRLF 转换，造成校验假失败。随后用同一文件的原始 blob、CI SHA 与 archive 字节证明原因，再通过 `git cat-file --batch` 读取全部原始 blob；未修改任何源码、下载工件、CI 配置或预期 Hash。该辅助核验失败与诊断保留为 `identity-initial-mismatch.json`、`identity-diagnostic-proof.json`，不计作产品或 CI 失败，没有触发重跑。

忽略目录 `artifacts/p7/ci22-batch2-actions-v1/` 保留：

- 推送前/后远端身份、九文件审核 SHA、一次推送记录。
- GitHub Run/Job/Artifact 元数据、两份完整 Job 日志、原 ZIP及解包日志/JUnit/coverage/源码清单。
- `cases-311.json`、`cases-313.json`、`verified-results.json`：所有实际测试状态与逐项结果。
- 本地身份校验诊断与 `RESULT-SEAL.json`。封存只是本地文件 SHA 清单，不冒称人工签署或新的 P3 Evidence。

## 失败与剩余迁移状态

**本批 CI 测试失败 0，无新增产品/安全失败可归因。** 没有因此修改产品、补提交、再次推送或重跑。

原 [#22](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41218164036) 仍为 attempt 1 / failure，其 60 failed / 265 passed / 63 skipped 历史结果原样保留；[#23](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41276968565) 仍为 attempt 1 / success。对应本地归因、结果和 Seal 的 SHA 与开工快照一致。

原 60 项失败中，#23 证明 4 项、本批新增证明 10 项，累计 **14 项原失败已获双版本定向 PG 验证**。另 1 项是原通过控制，不重复记作修复失败数。其余 **46 项尚未纳入已执行的定向矩阵**：A1 3、A2 37、A3 2、A4 2、A5 2；这不是本轮完整重跑后的 46 failed。

下一批可另行授权剩余 Web purpose、Required/Supplement 篡改、Partial Evidence 节点/unknown 恢复。A4/A5 仍按原边界单独处理；不修改低信任 run_question 或借测试迁移改产品 API。本轮已经停止，不进入 Batch 3，不恢复完整集成矩阵。候选分支完整 CI 仍需后续全范围验收，不能以此次定向成功宣称已完成。

本结果报告和新校验记录仅保存在本地；已推送的准备文档保留其推送前 NOT_RUN 快照，没有补提交改写历史状态。
