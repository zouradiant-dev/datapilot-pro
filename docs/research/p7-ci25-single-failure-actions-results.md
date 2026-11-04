# CI #25 单项修复：推送后真实 PG 验收

2026-11-01。**双版本单项真实 PG/MCP PASS；原 60 项失败累计 29 项完成验证，31 项尚未迁移；Full CI NOT_VERIFIED。**

本记录是[推送前修复报告](p7-ci25-single-failure-repair.md)与[当时 Handoff](p7-ci25-single-failure-handoff.md)的后续状态，不覆盖它们的历史 NOT_RUN/等待批准快照。

## 推送与远端身份

- 用户本轮明确批准仅推送 `b3328e003cf5e1fc997c28c2228bf23209562699`。
- 推送前重新确认分支 `p7-engineering-candidate-v1`、本地 HEAD、父提交以及 GitHub 远端基线 `c7606be7d8838433abc1fb3a9aa643516e07fdf6`；已跟踪工作区干净。
- 仅一个 fast-forward 提交、六个已审查文件。推送后 GitHub Commit API 返回的父提交和六文件清单一致；六份既有未跟踪 Docker/CI 记录未上传。
- 未使用 Force Push、Rebase 或合并。`main` 在推送前后均为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`。
- [Actions #26 / 41295087030](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41295087030)，名称 **DataPilot CI25 Single Failure - NOT FULL CI**，push 触发，attempt 1，结论 **success**。
- UTC 2026-11-01 **09:53:55–09:55:44**，北京时间 **17:53:55–17:55:44**。没有手动重跑或第二次派发。

## 实际结果

| Python | Job | 非集成回归 | 唯一 PG 集成 | JUnit PG 耗时 |
|---|---|---|---|---|
| 3.11 | [124814138569](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41295087030/job/124814138569) | **1334 passed / 0 failed / 0 skipped** | **1 passed / 0 failed / 0 skipped** | 8.432 秒 |
| 3.13 | [124814138378](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41295087030/job/124814138378) | **1334 passed / 0 failed / 0 skipped** | **1 passed / 0 failed / 0 skipped** | 6.575 秒 |

两版非集成 JUnit 耗时分别 39.909 / 35.002 秒。相较 #25 的 1332 项，增加的是已审查的两条合同/运行期单元反例，不改变原 PG 分母。

两份 PG JUnit 都仅含以下一个精确身份，没有执行其余 14 项 PG，也没有执行完整集成矩阵：

```text
tests/test_citation_policy_postgres.py::test_real_supplement_only_and_forged_quotes_cannot_fill_required_sources
```

每个 Job 使用 GitHub Actions 自带的新隔离 PostgreSQL 服务；初始化日志确认 **PostgreSQL 17.11 (`170011`)、pgvector 0.8.6、迁移 0008、固定 BGE `pinned_model_verified`**。原角色隔离、Schema 初始化、合成 Seed 与模型校验在该临时服务执行，没有访问开发者/历史数据库或 Docker 数据盘。依赖安装、测试收集、Ruff、格式、coverage/JUnit 上传均 success；格式检查记录 349 个 Python 文件。

## 两层安全断言确实到达

依据是精确 Node 的无 skip 成功 JUnit、实际 pytest 命令日志，以及与提交逐文件匹配的源码；没有另造内部异常响应或业务执行结果。

| 控制 | 本次已执行断言 |
|---|---|
| 合法原件 | 原 Host 确认后真实 MCP 检索报告 completed，Required Fact 有覆盖；恢复原合同后再次 completed。 |
| Supplement 限制 | 仅 Supplement 仍 unavailable，并保留 `required_document_source_missing`；伪造 quotation 不进入 Supplement 覆盖。 |
| 非法合同 | Required Source/Fact IndexVersion 矛盾时，原正式确认抛出 `ValidationError: Required facts cannot be relabelled as supplementary`。 |
| 运行期篡改 | 合法原合同与 RagScope 不变，只替换不可信结果 Citation 的 IndexVersion；`service.build` 必须抛出 `AgentFailure`，错误码 **DOCUMENT_NOT_AUTHORIZED**。 |
| 身份未变 | 篡改拒绝后，合同与 Reader 授权 JSON 均与控制前一致。 |

原七条业务 assert 和运行期 `pytest.raises(AgentFailure)` 保留；没有用构造阶段异常代替运行期拒绝。没有更改或重新签造 Attestation，也没有改变产品守卫。这里证明真实 PG/MCP、固定本地 Embedding 与报告校验；不代表 DeepSeek 自主推理、浏览器 Smoke 或完整业务质量评测。

## 工件与完整性

本地完整证据目录：`artifacts/p7/ci25-single-failure-actions-v1/`。

| Python | Artifact ID | ZIP SHA256 |
|---|---|---|
| 3.11 | 13078898548 | `fac6193a833deef4cec7ac0b6c127d3ed2f1a11229a566e4992cae2c56eaf690` |
| 3.13 | 13078853595 | `2d9eadc1f30aec86a6041f078e2b8c59173c0235e7fce6f993b8e316ca8f1edd` |

两份 ZIP 均已下载，实际字节 SHA 与 GitHub Artifact digest 一致；解包有路径/大小/符号链接检查。两版 `commit.txt` 都是目标提交，`test-scope.json` 都为 `ci25-single-failure / full_ci=false / planned_pg_tests=1`。**每版完整 634 个源码文件 SHA 与原始 Git blob 完全一致**，未用 Windows CRLF 工作副本替代 Linux 字节。

保留 `github-start/final/jobs/artifacts.json`、推送与远端身份、两份完整 `job-py*.log`、原 ZIP、解出 JUnit/coverage/依赖/初始化/Ruff/格式日志、`cases-311/313.json`、`verified-results.json`、`progress.json` 与 `RESULT-SEAL.json`。原 #22/#23/#24/#25 结果、Seal、失败日志及本轮修复前记录保持原值。

本地只读核验脚本首次误把 Actions 的 Step 显示名当作原始 Job 日志必须含有的文本，产生一次检查器断言失败；已保留 `verify-ci-v1.py` 与 `inspection-v1-error.json`。实际 Step 身份从原 Jobs 元数据核对，Commit/精确命令从原日志核对，随后离线检查通过；没有修改产品/测试、覆盖下载原件或重跑 CI。不能把这个读取器假设错误归为产品或 CI 失败。

## 当前进度与停止边界

- 原 #23/#24 累计验证 14 个原失败身份；#25 已验证另 14 个，历史仍为 14 passed / 1 failed。
- 本次 #26 只新增验证原失败编号 **7**，累计 **29/60**；不是在 #26 重新执行过 Batch 3 全部 15 项。
- Batch 3 的 15 个身份现在分别由 #25 的 14 项与 #26 的 1 项获得双版本真实验证。
- 剩余 **31 项：A2 29 项、A5 2 项**，精确身份与集中迁移方案保留在[修复机器记录](p7-ci25-single-failure-repair.json)；本轮没有迁移或执行。
- 产品源码、Goal v4、P3、Report、Durable、Embedding、Gold/Seal/STOP 未修改；没有调用付费模型或接触历史 Docker 数据。

**Single Failure Repair：PASS；Runtime Tamper Safety：PASS（上述有界真实 PG 场景）；Real PG/MCP：PASS；GitHub Push：COMPLETED；Full CI：NOT_VERIFIED。**

本结果文档和新工件仅在本地保存，未追加提交或推送。下一步是另行授权剩余 31 项的测试前置合同迁移，然后再独立安排完整 CI；本轮到此停止。
