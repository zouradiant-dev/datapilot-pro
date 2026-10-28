# P7 Remote CI Verification & Release Readiness

**当前候选 remote CI：not_run；发布验收：blocked，等待候选提交/推送与实际远端验证。** 本轮完成远端事实核对、现有工作流审计与证据保留补强。未将旧 Run 或本地通过结果当作当前候选的 GitHub Actions 通过。

## 远端身份与触发核验

2026-10-28 通过连接的 GitHub API 实际读取仓库、main 分支、工作流目录、工作流原件、最近 Runs、旧 Run 的 jobs/logs/artifacts。

- 仓库：`zouradiant-dev/datapilot-pro`，private，连接具备仓库写权限；阻断不是权限不足。
- 本地 HEAD、origin/main 缓存及 API 实际 main 均为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`。
- 唯一远端工作流 `.github/workflows/test.yml` 的 Git blob ID 为 `db438cba9e4c57159c7b30c539919944f23efdae`，只声明 `push`、`pull_request`，没有 `workflow_dispatch`、`repository_dispatch` 或独立验证工作流。
- 当前工作区还有未提交/未跟踪的 P7 Runtime、测试、脚本和记录；其中20份 src 文件与 HEAD 不同。这些既有改动不是本轮新写，但远端旧提交不包含它们。
- Re-run 只能重跑旧提交，不能把本地工作区传给 Actions；创建空提交/PR也不能补上未提交源码。没有触发一个旧 Run 来冒充本次执行。

按本轮“无法通过现有方式触发则标记 not_run”的约束，未创建提交、推送、分支、PR、空提交或远端文件写入；没有擅自发布积累的工作区。工具支持写入并不等于当前候选已经完成发布范围审查。

| 当前候选 Python | Remote 状态 | 当前候选 Commit SHA | 新 Run URL | Passed | Failed/Error | Skipped |
|---|---|---|---|---|---|---|
| 3.11 | **not_run** | 未生成；仅有上述 base HEAD | 未产生 | 未观测/null | 未观测/null | 未观测/null |
| 3.13 | **not_run** | 未生成；仅有上述 base HEAD | 未产生 | 未观测/null | 未观测/null | 未观测/null |

未运行不是0次失败或成功。当前候选的远端完整非集成、真实PG/MCP、三策略联合、安全门控和Artifact上传均未获本轮远端证据。

## 已核实的旧 CI：仅历史参考

最近的[历史 Run 40096866653](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/40096866653) 对应上述旧 HEAD，事件为 push，2026-10-24 创建，整体 success。

| 历史 Job | 真实日志统计 | 耗时 | 状态 |
|---|---|---|---|
| checks (3.11)，job 120880849144 | 709 passed / 17 skipped，无失败 | 1668.26秒 | success |
| checks (3.13)，job 120880848945 | 709 passed / 17 skipped，无失败 | 1392.27秒 | success |

旧工作流未生成可下载JUnit证据，API返回 artifacts=[]。旧709/17不是当前901项本地非集成集合，更不是当前P7修复的验证。API核验摘要保存在忽略目录 `artifacts/p7/remote-ci-readiness-v1/github-verification.json`；不保存或公开带临时授权的下载URL。

## 初始化与权限审计

复用原 `DataPilot checks`、ubuntu-latest、两个Python矩阵和原PG服务，没有第二套数据库/容器部署。GitHub每个job的服务容器均为新建的一次性环境，不挂载用户或历史评测卷。

| 环节 | 审计结论 |
|---|---|
| 依赖 | astral-sh/setup-uv@v6，uv0.12.5，`uv sync --locked`；不改pyproject或uv.lock。 |
| PG/向量 | `pgvector/pgvector:0.8.6-pg17@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`，专用datapilot_test_ci，healthcheck指向同名库。 |
| 角色 | 13组显式DSN：admin/owner/seed/reader/ingest/upload_reader/registry/runtime/checkpoint_owner/rag_ingest/rag_reader/web/maintenance；同一host/port/database，继续隔离MCP/Registry/Runtime权限。CI口令仅是该一次性服务的测试值。 |
| Schema | 原db-init创建pgvector及saas/rag/catalog/uploads/execution/checkpoints；原migrate升级Alembic至0007并授精确权限，不改历史迁移。 |
| Checkpoint | 原runtime-init由独立checkpoint_owner运行官方Saver setup；当前锁定版本期望checkpoint_migrations最大值9；runtime无DDL权限。 |
| Seed/健康 | 仅新CI库执行原Seed42/240客户；health核对PG17、vector、迁移、只读角色和Seed。原测试继续检查非空库拒绝Seed，不在用户/历史库执行初始化。 |
| Embedding | 宿主显式model-fetch；固定512维BGE、revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，原ONNX/tokenizer SHA和推理recipe不改。不自动回退向量/模型。 |
| 生成模型 | Fake/脚本/HTTP Mock；显式DATAPILOT_API_KEY为空、RUN_LIVE_TESTS=0。Live用例保留可见skip，不连接DeepSeek。 |

原ONNX SHA为`1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38`，tokenizer SHA为`48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26`。这些是配置/源码审计；本轮没有宣称远端已实际下载或执行初始化。

## 现有工作流的必要补强

只修改原工作流：

1. fail-fast=false，避免一个Python失败就取消另一个矩阵任务。
2. 保留原初始化命令，按依赖/非集成/初始化/真实集成/静态检查拆分证据；非集成失败不隐藏可运行的PG/静态结果，初始化失败则明确不运行依赖它的集成。
3. 所有shell显式`set -euo pipefail`，日志经tee留存而不吞掉失败；不设置continue-on-error，不删测试或降低断言。
4. collect-only记录完整测试身份；JUnit分为unit.xml/integration.xml；覆盖率继续合并记录。保留所有成功/失败/skip，不通过重试刷全绿。
5. always()上传范围只限artifacts/ci，包括日志/JUnit/源码Commit与SHA清单/覆盖率；不上传整个artifacts、私密原件、.env或模型缓存。按Python/RunID/attempt分开命名，不覆盖旧attempt；留存周期遵守仓库设置，不能宣称永久保存。
6. 使用[官方upload-artifact v4当前提交](https://github.com/actions/upload-artifact/tree/ea165f8d65b6e75b540449e92b4886f43607fa02)固定SHA；本轮已通过API核对tag指向。仓库token仅contents:read；真实上传权限和行为仍待远端执行。

CI启用原P7非付费故障标志后，发现两个旧意图Mock测试内部还调用冻结Runner的Docker守卫。仅在测试边界用已有portable_pg实际PG/角色校验及固定测试环境校验替代该宿主检查；原Runner、候选、MockTransport、Journal/账本和unknown-outcome断言不改。旧Smoke账本组件测试同样使用原portable_pg Runtime连接，不再以私密配置缺失为由跳过。没有启用正式Live、修改Permit或读取封存Gold。

## 本轮真实本地验证

| 执行 | Python3.11 | Python3.13 |
|---|---|---|
| 本轮首批工作流/旧P7非集成定向测试 | 57 passed，3 integration deselected | 后续完整集合覆盖 |
| 首轮干净Linux定向：14 HTTP Mock + 2意图Mock + 1账本 + 5工作流契约 | 20 passed / 2 failed | 20 passed / 2 failed |
| 守卫适配后的相同22项（新目录，保留首轮） | **22 passed，5.74秒** | **22 passed，6.04秒** |
| 最终Windows完整非集成集合 | **901 passed，14.72秒** | **901 passed，15.18秒** |

首轮两项失败的实际原因是冻结Runner内部仍调用Docker路径，错误为FileNotFoundError；保留首轮源码目录、JUnit和日志。修正仅是测试的可信环境适配，不修改Runner或将断言改为skip。唯一warning来自原bad_usage畸形数据注入，未被忽略成通过或改写原usage。

另在断网容器用固定失败码7的假uv执行7段工作流shell，均首错终止、保留失败日志、返回码7；证明tee没有掩盖错误，不代表Actions调度/上传已实际运行。Ruff全仓通过、277份Python文件格式通过、git diff --check返回0。完整collect-only记录1,157个测试身份，901项非集成通过、256项集成/Live在Windows分区deselect。本轮不重复远端无法触发的完整PG全集，也不把22项定向测试加成新的业务任务数。机器摘要见 [当前状态与结果](p7-remote-ci-release-readiness.json)。

此前三项策略联合已由上一轮干净Linux各62项（51真实PG/MCP+11环境契约）、Windows各896非集成及4项Smoke验证；本轮生产源码保持其Hash，故不重复一小时PG全集。Required/Supplement、Partial Evidence、Original-query-first、P3、Journal/Ledger/Durable和安全拒绝的这些本地证据均保留，不能替代本轮远端完整验证。

## 完整性与发布阻碍

本轮生产源码、P3、Gold、Scorer、Seal、历史数据及业务参数不改。只读核对106份生产文件的开工Hash，1,994份更早Gold/Scorer/Seal/历史结果归档未变；旧隔离历史库121,808条记录与上轮结束快照逐行一致。不初始化、Seed、覆盖或重建用户/历史库。非付费定向测试只在已明确创建的datapilot_test_portable_*测试库追加新组件记录，不清库/删卷。

本轮既有文件增量仅`.github/workflows/test.yml`及`tests/test_p7_gate2.py`、`tests/test_p7_smoke.py`；新增5项工作流契约测试、本报告和机器摘要。已有477份仓库文件中其余文件保持Hash，未提交内容保留、暂存区为空。日志、JUnit、两轮干净目录闭包、源码原件和差异保存在忽略的`artifacts/p7/remote-ci-readiness-v1/`。未修改AGENTS、规划、依赖、迁移、Docker镜像/Compose或历史实验记录，没有建立新的付费Freeze或Permit。

当前发布仍有以下阻碍：

- 当前修复没有远端候选Commit；必须先明确包含Runtime、测试、公开夹具、脚本和工作流的提交闭包，排除私密文件与无关既有工作，再获得明确提交/推送安排。不能只推工作流或遗漏未跟踪脚本。
- 当前候选远端Run/JUnit/初始化/固定模型下载/Artifact上传都未观测；必须在发布后的准确SHA下实际核验两版完整结果、所有skip原因和Source Hash一致性。
- 英文控制仍错误空召回，Web默认策略仍legacy，真实模型对新首查约束的遵循率/质量/成本未实测。这些历史限制不因CI配置补强而消失。

下一步建议先完成受审查候选提交与推送的明确授权，再运行已补强的现有工作流，下载并核对两个矩阵Artifact，补写当前候选的Run URL、Commit SHA和通过/失败/跳过数量。通过前不宣称Release Ready，不进入Gate3、英文检索优化、付费Smoke或后续产品阶段。本轮结束时停止。
