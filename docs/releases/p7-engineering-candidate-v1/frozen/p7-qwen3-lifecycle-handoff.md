> 公开脱敏副本。历史原件 `docs/research/p7-qwen3-lifecycle-handoff.md` 保持不变、仅本地保留。
> 原件 SHA256：`0720e9d368bb04a4c05d2d958e72f04223ede5399abb48f702b8c4bd50cc1514`。仅替换本机路径和不可公开工件链接，历史结论/分数不变。

# P7 Qwen3 Lifecycle — Quota-Safe Handoff

记录日期：2026-10-29。按负责人额度安全指令停止新增实验。本文件是开发交接，**不是最终验收、发布许可或 Implementation Freeze**。不调用 DeepSeek，不提交或推送 Git，不切换生产 BGE。

## 1. 当前结论与进程状态

- Phase 2A 生命周期：显式初始化/就绪、会话缓存、固定解释器绑定、超时清理已实现并有真实 Windows/Linux 验证。Linux 父进程硬退出的额外缺陷已复现、最小修复并完成定向复验。
- Phase 2B 部署可靠性：大量工程检查通过，**最终联合验收未完成**。不能宣称 release ready 或 Phase 2C 准入已通过。
- 最后只读检查时，`datapilot-qwen-lifecycle-linux-cpu-final` **仍在运行**，StartedAt=`2026-10-29T15:19:51.992856445Z`，尚未采集最终 JUnit。它是在额度交接指令前启动的已有测试，本轮没有为交接重新启动。下一轮先取结果，不能直接重复运行。
- Windows BGE/P3 3.11 的 81 项已结束且通过；Python 3.13 PG 回归**尚未启动**。
- `datapilot-p7-unified-postgres-1` 与 `datapilot-pro-postgres-1` 最后检查均健康。没有清库、删卷或停止业务容器。

## 2. Git 与当前修改的归属

工作目录：`<LOCAL_PATH>`

- 分支：`p7-ci-verification-20261028`
- HEAD：`f8b122438d2c67ab26e618ecded72ecc18454015`
- 工作区有大量本轮开始前就存在的未提交修改与未跟踪文件，**不得将整个 git diff 当成本轮改动，不得 reset/clean/全部 add**。
- 本轮起点全部文件 Hash：`artifacts/p7/qwen-lifecycle-v1/before.json`。
- 交接时完整状态清单：`artifacts/p7/qwen-lifecycle-v1/git-status-handoff.txt`。
- 交接时全部已跟踪文件 Diff：`artifacts/p7/qwen-lifecycle-v1/git-diff-handoff.patch`；未跟踪文件仍保留在原路径。
- 全部可见工作区文件 SHA、JUnit 汇总及历史 Seal 检查：`artifacts/p7/qwen-lifecycle-v1/handoff-inventory.json`。这是交接快照，不是最终发布 Freeze。本交接文档在该快照之后创建。

相对本轮 `before.json` 改动的原有文件只有以下七个：

| 文件 | 必要作用 |
| --- | --- |
| `AGENTS.md` | 追加本轮生命周期、固定环境、权限与清理约束 |
| `src/datapilot/rag/mcp.py` | 原 stdio 中增加显式宿主准备/就绪；缓存、可信 Runtime/PID 校验、Qwen 会话准入；保留 BGE 同步工具线程卸载 |
| `src/datapilot/rag/models.py` | 原工厂向 Qwen 传递生命周期 observer，默认仍 BGE |
| `src/datapilot/rag/qwen.py` | 固定环境验证、分阶段记录、CUDA/RAM 相关拒绝；模型、Recipe、阈值不变 |
| `src/datapilot/runtime/mcp_client.py` | 固定 `-I` 引导、超时/取消时有界清理；最后追加 Linux 父退出 SIGKILL 绑定 |
| `tests/qwen_delay_server.py` | 真实模型上的初始化/编码/GIL 延迟故障，不伪造检索向量 |
| `tests/test_qwen_migration_postgres.py` | 可选择 CPU 测试 Profile，补充超时、缓存、并发、PG 回滚、断连/退出测试 |

本轮新增（此前并不存在）：

- `src/datapilot/rag/lifecycle.py`：同一 stdio 模型缓存、可观测就绪、RAM/PG 容量准入和资源守卫。
- `src/datapilot/rag/qwen_runtime.py`：固定部署环境 attestation 与显式安装命令。
- `src/datapilot/runtime/owned_process.py`：OS 验证的自有进程句柄/pidfd 与 2 秒清理截止，不按进程名批量杀进程。
- `tests/test_qwen_lifecycle.py`：生命周期、环境/权限、断流和进程所有权契约测试；其中 stub 向量只用于单元测试。
- `tests/qwen_parent_exit.py`：一次性父进程硬退出故障夹具，复用实际隔离引导。
- `evaluation/qwen_lifecycle_probe.py`：可信工程探针，20 次直接 MCP 查询和资源采样，不是业务评测或第二套 Runtime。
- `requirements/qwen-mcp-linux.lock`、`Dockerfile.qwen`：独立 Linux 锁定部署，复用现有基础镜像/PG/MCP。
- 本交接文档，以及忽略目录 `artifacts/p7/qwen-lifecycle-v1/` 中的日志和私密工程文件。

`src/datapilot/rag/qwen.py`、Windows Qwen lock、0008、其他 P7 策略文件在 Git 中也可能显示未跟踪/已修改，但其中大量内容来自 Phase 1 或更早工作。不要删除。`docs/codex-prompts-v2.4.md`、v2.5 等负责人规划本轮没有修改。

## 3. 关键实现及边界

1. Qwen 先用固定解释器和 `-I` 加固定源码引导，校验授权 Manifest，再执行宿主控制 `prepare_embedding`。它不是 Worker capability；隐藏工具 Schema 不是权限机制。
2. 显式就绪总上限 60 秒；每次 MCP RPC 仍为原 10 秒。加载、Hash、CUDA、预热全部记录，READY 必须在真实模型/向量检查后出现。Search 不隐性加载模型，不自动重试或切 CPU。
3. 同一会话复用一次模型和 Goal 缓存；同一客户端最多两个 Qwen 待准入会话，同一部署数据库的 PG advisory lock `(7512,6001)` 只允许一个模型，CPU/CUDA 共用容量。它**不是跨数据库/跨主机全局 GPU 调度器**。
4. RAM 下限 CPU 4 GiB、CUDA 3 GiB；CUDA 可用显存下限 2 GiB。资源不足明确拒绝，不降低门槛制造通过。
5. 超时/取消/退出时由已验证的子进程句柄或 pidfd 执行 2 秒清理截止；Qwen 子进程只有 Reader，无 Journal、Registry、管理员或 Provider Key。进程退出不改变原 P5B unknown-outcome/账本规则。
6. 固定 `.venv-qwen`：Windows Python 3.11.16、Linux Python 3.11.14；Torch 2.8.0+cu128、Transformers 4.57.1、Tokenizers 0.22.2。Linux 与 Windows 分别使用各自 hash lock；安装后显式 `qwen_runtime --install` 建立 attestation，不能由 `.env`/PATH/模型参数选择任意解释器。
7. BGE 默认、512 索引、Qwen 1024 ModelSpec/Recipe/检索和 Goal 阈值、P3、Report 业务标准、Journal/Ledger/Checkpoint 均未在本轮改变。

## 4. Linux 父进程硬退出缺陷：已修复并定向验证

在真实 CPU 模型已就绪、编码持有 GIL 的同一故障中：

- 修复前：客户端 `os._exit(91)` 后 3 秒，模型 PID 39 仍存活；测试仅清理自己已确认的进程。
- 根因：父进程的清理 Timer 随客户端消失，子进程被 GIL 阻塞，无法及时处理 stdin EOF。
- 最小修复：仅在 Qwen 固定 Linux 引导中，导入模型前执行 `prctl(PR_SET_PDEATHSIG, SIGKILL)` 并核对父 PID 未在绑定期间变化；绑定失败就拒绝启动。没有新服务或恢复引擎。
- 修复后：相同 CPU Scope/GIL 故障，3 秒检查无存活子进程，`cleanup_passed=true`。
- Windows 同类硬退出探针也观察到 3 秒内全部自有子进程退出；不据此宣称所有操作系统/宿主崩溃组合都已验证。

原始证据：

- `artifacts/p7/qwen-lifecycle-v1/linux-parent-before.log`
- `artifacts/p7/qwen-lifecycle-v1/linux-perf/parent-crash-before.json`、`.log`
- `artifacts/p7/qwen-lifecycle-v1/linux-parent-after.log`
- `artifacts/p7/qwen-lifecycle-v1/linux-perf/parent-crash-after.json`、`.log`
- `artifacts/p7/qwen-lifecycle-v1/parent-crash-before.json`、`.log`（Windows）
- 补丁前客户端源码：`artifacts/p7/qwen-lifecycle-v1/pre-parent-death-mcp_client.py`。

该补丁之前的 runtime source SHA 是 `21022ad21b5da5da023a4c90c5234b3128fcddcf02a2683bb3973bb48cfba83f`；**不能把它写成当前最终源码 SHA**。当前逐文件 SHA 已存 handoff inventory，最终发布 Freeze 尚未建立。

## 5. 已通过结果与源码对应关系

统一日志目录：`artifacts/p7/qwen-lifecycle-v1/`。所有结果来自真实执行；Fake/脚本模型不是 DeepSeek Live。

| 已观测验收 | 真实结果 | 文件 |
| --- | --- | --- |
| Windows 非集成，Python 3.11/3.13 | 各 992 passed，0 failed/skip | `regression-py311-final2.xml/.log`、`regression-py313-final2.xml/.log` |
| Windows Qwen 真实 PG/MCP 原专项及延迟故障 | 17 passed | `qwen-win-r1.xml/.log` |
| 缓存/并发/已确认 PG statement_timeout | 1 passed | `qwen-capacity-r2.xml/.log` |
| 真实子进程异常退出、客户端断开 | 2 passed | `qwen-exit-r1.xml/.log` |
| Linux CPU：单元/兼容及全部 20 项 PG/MCP | 55 passed，0 failed/skip，451.72 秒 | `linux-cpu/linux-cpu-r1.xml`、`linux-cpu-r1.log` |
| Docker CUDA：Goal/Citation 与跨进程恢复 | 2 passed，18 deselected，95.12 秒 | `linux-gpu/linux-gpu.xml`、`linux-gpu-tests.log` |
| Windows BGE/P3/P5B 定向，Python 3.11 | 81 passed，816.49 秒；原 77 + 4 个证据恢复用例 | `pg-py311-r1.xml/.log` |
| 原 Qwen Run 重复跨进程读取恢复 | succeeded/completed，调用/Artifact/usage 不变，2 artifacts/6 journal calls | `old-qwen-recovery.json`、`old-qwen-recovery-r3.log` |
| Linux 父退出最小修复定向 | 前失败、后通过 | 上节 before/after JSON/日志 |
| 静态检查 | Ruff 全仓 check 通过；303 文件 format check 通过；git diff --check 通过，仅 CRLF 提示 | 已执行终端输出；Diff/文件 SHA 已保存 |

**版本警告：** 两版 992、Windows 20 个专项、Linux CPU 55、Docker CUDA 2，以及启动时的 Windows 81，均早于最后的 Linux 父退出引导补丁或尚未覆盖该补丁。不要直接合并称“最终冻结源码全部通过”。新增的一项 Worker capability 单元测试使最后正在跑的 Linux 集合也与此前 55 项不同。最终源码的 Linux CPU 测试已启动但交接时尚未收集；后续需按源码差异补必要验证，而非重跑全部已有可信实验。

### 性能与清理实测（不是 SLO 或业务成功率）

| 指标 | Windows CUDA | Linux CPU | Docker CUDA |
| --- | ---: | ---: | ---: |
| 显式就绪（含 transport，单次进程） | 9.48 s；另一次 11.78 s | 13.44 s | 16.19 s |
| 20 次 Search p50 / p95 | 49.7 / 68.4 ms | 189.3 / 266.9 ms | 37.4 / 63.7 ms |
| 关闭清理 | 0.390 s | 0.056 s | 0.079 s |
| 采样 Python 子进程 RSS 峰值 | 2.50 GiB | 3.98 GiB | 3.13 GiB |

Windows GPU 总用量采样峰值 1403 MiB，前后基线均 83 MiB；这是整张卡的采样值，不是 Torch allocator 精确峰值。退出后探针确认进程不存在。没有清 OS 缓存，不能称为断电后冷启动分布；旧 34 秒加载失败/长尾记录保留。

清理对照：

- 原 30 秒阻塞：工具在 10.016 秒超时，但额外清理 20.088 秒；初始化取消等待 0.206 秒、清理 29.934 秒。
- 修复后：编码超时 10.005 秒、清理 0.268 秒；编码取消 0.201 秒、清理 0.281 秒；GIL 阻塞超时 10.003 秒、清理 2.043 秒；初始化取消 0.210 秒、清理 0.016 秒。
- 数据：`before-direct.json/.log/.py`、`after-cleanup-windows.json`；新故障 JSON 原件在 `artifacts/tests/qwen-8b4660048b31429a8eab93f628269f3f/`。
- `before-cleanup.xml` 的“2 passed”只证明旧超时测试通过，**不代表旧清理上限通过**；其旧断言没有覆盖清理尾部。
- 性能原件：`windows-gpu-performance-r1.json/.log`、`linux-perf/cpu-performance.json`、`linux-perf/gpu-performance.json`，以及对应 `linux-*-perf*.log`。

## 6. 已完成与未完成的资源/部署负例

已完成：

- 会话内并发两搜索只允许一个运行，其余明确 `EMBEDDING_BUSY`；模型只加载一次，后续 Search 的 Goal 编码缓存复用。
- 同部署 CPU 已就绪时，另一个合法 CUDA Scope 被容量锁拒绝，未加载第二模型：`linux-profile-capacity.log`、`linux-perf/negative-capacity.json`。
- 真正 2 GiB cgroup 的 CPU 准入拒绝：`EMBEDDING_RESOURCE_LIMIT`，约 1.51 秒，未启动模型：`linux-low-memory.log`、`linux-perf/negative-low_memory.json`。
- Windows Docker 构建期间的低 RAM 两次拒绝保留在 `smoke-r1.log`、`smoke-r2.log`，不能删除或降低门槛消除失败。
- 单元/真实 PG 中的 owner/index/model/precision/策略/引用错绑负例通过；SDK BrokenResourceError 是**单元注入**，不冒称自然网络故障。

尚未完成或 NOT_RUN：

- 收集最后 `linux-cpu-final` 的结果并核对它的最终源码身份。
- 最后 Linux 引导补丁后的 Docker CUDA 定向回归及 Windows 适用回归。
- Python 3.13 的 81 项 BGE/P3 PG 回归；最终源码完整双版本回归是否需要重跑应先按差异核对，不能复用旧成功冒称完成。
- 通过真实产品连接器验收 CUDA 不可用、模型文件缺失/坏 Hash、实际部署环境漂移的剩余 Docker 负例；现有单元覆盖不能替代所有部署场景。
- `linux-perf/negative.py` 已写，只有 `capacity`、`low_memory` 执行过；其中 `cuda_absent` **未执行**。
- `missing-model/` 仅为空目录，**没有完成缺模型容器实验**。
- Linux GPU 父进程硬退出/资源回收完整组合未专项复验；CPU 父退出修复已通过，不冒称所有 GPU 崩溃场景通过。
- 最终的 `docs/research/p7-qwen3-mcp-lifecycle-reliability.md`、机器结果汇总、最终 Implementation/Result Seal **尚未交付**。
- 远端 GitHub CI、付费 Live、业务质量/Phase 2C、生产切换均 NOT_RUN/未授权。

保留其他失败记录：`qwen-capacity-r1.xml/.log` 首次命中原 500ms lock_timeout，得到 RAG_DATABASE_ERROR；测试改为 250ms statement_timeout 后验证预期 RAG_QUERY_TIMEOUT，**未修改生产错误码或超时**。`linux-cpu-perf.log` 首次缺 PYTHONPATH 的 ModuleNotFoundError，修正可信探针启动命令后 `linux-cpu-perf-r2.log` 成功；产品 MCP 继续使用 -I 固定引导。旧恢复 r1 的忙碌拒绝、r2 的宿主设置不一致拒绝均保留，r3 显式转发相同环境后通过，没有绕过 Manifest。

## 7. 数据库、镜像及历史保护

本轮新增且不可自动清理的两库，均在现有隔离 PG 端口 55441：

1. `datapilot_test_qwen_lifecycle_v1_20261029`：本轮 Qwen/P3/Artifact/Journal 及所有失败样本。
2. `datapilot_test_qwen_lifecycle_v1_py313_20261029`：为隔离 3.13 回归已新建、迁移至 0008、初始化 Checkpoint；**未 Seed、未开始测试**。

凭据只在忽略目录 `environment-private.json`、`environment-py313-private.json`、`linux-environment-private.env`。禁止打印、提交、复制进报告或传给模型。初始化脚本已执行，不能重跑以重建这些库。

不得修改/删除 demo 库（55432）、既有 unified/portability/Phase 1 数据库、Docker Volume。不要运行 db-init/seed/清理脚本，也不要 `docker compose down -v`。

镜像实际身份：

- `datapilot-qwen-lifecycle:release` = `sha256:420275aadc6a09eb3481791d4a83c0cc72268a6a6b7d0367e84842025ef3cd25`，包含 Linux 父退出补丁。
- `datapilot-qwen-lifecycle:final` = `sha256:03b4d8882527f8ddf9b325d0a94bf4383e9a136774629a3e88909e3046c8786d`，补丁前版本，**tag 中的 final 不表示当前最终版**。
- 日志 `docker-build-*.log` 全保留。不要 prune、覆盖或假称未执行镜像实验通过。

Phase 1 原 292 个 Seal 文件已在动代码前复制到 `phase1-snapshot-root/`，交接时再次逐项验证零差异。原 Seal 是 `58d9c7e1ed33dcd52067d2c0337af612b1eb090172c1131597e90a6c3b53f6ae`。由于本轮获准改变源码，不能再拿根目录当前源码冒称仍符合旧 Phase 1 Seal；应验证其保留快照。

历史 Seal 此次重新检查有效：

- Embedding A/B：77 文件，`c4e4cf1fd3706d2d4bab5eb8cca2a85246f8237338b592173912c334f9b803c9`。
- 原 Live Smoke：136 文件，`d6f86460a27ac4781cf2917afee28d4a79dda74f5f750dbb48aeafebe8ef17e7`。
- Scorer 修复：29 文件，`8b63aca91235bee9dc9fb1506637c985a8b59e88ec7324f2e203cdc29e3d2f56`。

原 Gold/Scorer/Seal/Freeze、历史 Run/Evidence/Journal 不得重写或重评；本轮未调用付费模型。原 Qwen 暂停 Run `387abd55-6006-4151-a777-b88306fe9af3` 在本轮新库中，已通过原接口恢复，重复读取报告与预算一致。不要为了复测重置该 Run。

## 8. 下一轮顺序与精确入口（本轮不执行）

### 8.1 先收集已有进程，禁止直接重跑

```powershell
Set-Location '<LOCAL_PATH>'
$env:PYTHONUTF8='1'
$docker='<LOCAL_PATH>'
& $docker --config .cache/docker-local -H npipe:////./pipe/dockerDesktopLinuxEngine inspect datapilot-qwen-lifecycle-linux-cpu-final --format '{{json .State}}'
& $docker --config .cache/docker-local -H npipe:////./pipe/dockerDesktopLinuxEngine logs datapilot-qwen-lifecycle-linux-cpu-final
Get-Content artifacts/p7/qwen-lifecycle-v1/linux-cpu-final.log -Tail 25
Get-Content artifacts/p7/qwen-lifecycle-v1/linux-cpu-final/linux-cpu-final.xml -Tail 3
```

XML 不存在且容器仍 running 就等待已有工作；若已退出则读 ExitCode/JUnit/日志，记录真实通过、失败、跳过和源码版本。不要因文件未刷新就重启。若故障存在，先定位，不能放宽断言。

### 8.2 补 3.13 PG 回归，使用已建的独立库

只在下一轮继续验收授权范围内执行；输出名若已存在先读，不覆盖：

```powershell
$privateEnv=Get-Content artifacts/p7/qwen-lifecycle-v1/environment-py313-private.json -Raw | ConvertFrom-Json
foreach($item in $privateEnv.PSObject.Properties) {
  [Environment]::SetEnvironmentVariable($item.Name,[string]$item.Value,'Process')
}
$env:DATAPILOT_LLM_MODE='fake'
$env:DATAPILOT_API_KEY=''
$env:DATAPILOT_RUN_LIVE_TESTS='0'
$pgTemp='artifacts/p7/qwen-lifecycle-v1/pg313-'+[guid]::NewGuid().ToString('N')
.venv-313/Scripts/python.exe -m pytest tests/test_semantic_integration.py tests/test_rag_postgres.py tests/test_recovery_versions.py tests/test_citation_policy_postgres.py tests/test_partial_evidence_postgres.py tests/test_original_query_postgres.py tests/test_cross_source_postgres.py::test_cross_process_metric_and_report_artifacts_restore_p3_verdict_unchanged tests/test_cross_source_postgres.py::test_p3_persisted_but_journal_unknown_blocks_resend tests/test_cross_source_postgres.py::test_rag_and_metric_references_survive_cross_node_checkpoint -q -p no:cacheprovider --basetemp $pgTemp --junitxml=artifacts/p7/qwen-lifecycle-v1/pg-py313-continue.xml *> artifacts/p7/qwen-lifecycle-v1/pg-py313-continue.log
```

不要用原 `pytest-run.py` 误以为它会自动选 py313 库：它当前固定加载 `environment-private.json`。上面的显式进程环境才指向新 py313 库。不要打印 `$privateEnv`。

### 8.3 必要的最终源码定向验证

先收已有 Linux CPU 结果，再决定差异验证；Qwen 测试要与其他 Qwen 会话串行，避免把容量拒绝误认成业务失败。已有 `DATAPILOT_RUN_QWEN_TESTS=1` 为显式本地工程开关，不能替代付费授权。

Windows host 3.13 可先补这两个现有用例（使用 base 私密环境，而非 py313 空库）：

```powershell
.venv/Scripts/python.exe artifacts/p7/qwen-lifecycle-v1/pytest-run.py qwen-host313-continue .venv-313/Scripts/python.exe tests/test_qwen_migration_postgres.py -k 'goal_binding or cross_process_replay'
```

重验 Linux 父退出的既有精确入口是 release 镜像里的：

```text
/app/.venv-qwen/bin/python /app/artifacts/parent-crash.py <新的结果标签>
```

容器须使用既有网络 `datapilot-p7-unified_default`、`linux-environment-private.env`、固定只读模型挂载 `/app/.cache/rag-models`，并把本轮 `linux-perf/` 挂载至 `/app/artifacts`；显式 `PYTHONPATH=/app/src` 仅用于可信诊断入口。产品 MCP 自身使用 -I，不依赖该变量。已有 `linux-parent-after.log` 已通过，不需无理由再跑。

剩余 Docker CUDA/文件/资源负例应参照已保留的具体 run 参数和原脚本，使用新容器名与新输出文件，不能重建旧库或改模型文件。需要 CUDA 时显式 `--gpus all`；不传 GPU 的 CPU 通过不能代表 CUDA 通过。最后才按实际源码差异决定完整双版本回归、冻结和最终报告，避免重复压测。

### 8.4 验收标准

- 10 秒工具超时和单独 60 秒准备上限不放宽；初始化、调用、清理分别计时。
- 无就绪误报、无未知调用自动重发、无成功收据伪造；P3/事实/引用/Required/Supplement 不变。
- 自有进程和资源有界清理，环境/模型/IndexVersion/权限错绑失败关闭。
- 明确区分最终通过、旧版本通过、未运行、正在运行；保留所有失败日志。
- 完成最终实际结果报告和源码/结果身份后，才讨论是否可进入非付费 Phase 2C；不能自动切生产或启动 Live。

## 9. NEXT CODEX SESSION PROMPT

```text
继续 DataPilot Pro P7 Qwen MCP Lifecycle 收尾。先读 AGENTS.md 和 docs/research/p7-qwen3-lifecycle-handoff.md，保留全部未提交修改与 artifacts/p7/qwen-lifecycle-v1/，不要重新实现已完成机制。
首先收集已运行的 datapilot-qwen-lifecycle-linux-cpu-final 的状态、日志和 JUnit，不重复启动；核对 handoff-inventory.json、当前 HEAD/分支和源码差异。Linux 父进程硬退出已实现 PR_SET_PDEATHSIG，before 留存/after 无存活进程的定向证据已保存，不要重新诊断整个项目。
按交接单只补未完成或受最后补丁影响的检查：独立 py313 测试库的 BGE/P3 81 项、最终 Qwen/Docker CUDA 定向、实际部署资源/坏模型/无 CUDA 负例。已有可信且源码未变的测试不重复压测。不要误用固定 base 环境的 pytest-run.py 访问 py313 新库。
不改默认 BGE、P3、阈值、Gold/Scorer/历史 Freeze、Journal/Ledger/Checkpoint；不调用 DeepSeek，不清库/Seed/删 Volume，不提交推送，不进入 Gate 3。发现新问题只做最小必要修复，保留失败证据，版本与状态如实标记。
最后补齐 docs/research/p7-qwen3-mcp-lifecycle-reliability.md、机器记录和新源码身份，说明 Phase 2C 准入是否实际满足。未通过不能写成已验收。完成后停止。
```

## 10. 2026-10-30 收尾补记（不覆盖上述历史快照）

已收集原 `linux-cpu-final`：56 passed、0 skipped、489.28 秒，没有重跑。上述“仍运行”和“未收集”是交接当时状态。

本次续接补齐：Python 3.13 真实 PG/MCP 81 passed；两版最终定向各 55 passed；3.13 宿主 Qwen 2 passed；最终 release 镜像 CUDA 2 passed；真实无 CUDA/缺模型/坏 Hash/清单漂移四个拒绝；GPU 父进程硬退出无残留子进程。产品源码与交接时一致，没有扩大实现范围。

最终报告与完整版本/限制说明见 [P7 Qwen MCP Lifecycle 交付](../../../research/p7-qwen3-mcp-lifecycle-reliability.md) 和同名 JSON。新工程 Freeze `qwen-lifecycle-v1-77ceb2a7eaca`，Runtime source SHA `e9e252b1b834d5cc3ce2271ef00af4f0e437096d9d1e113c5c756172a1d1222c`。py313 库已完成回归，不再是空库；不要重新初始化或覆盖结果。

受测本地工程准入通过，业务质量/远端 CI/付费 Live/生产切换未验收。本轮继续保持默认 BGE，不提交推送，不进入下一阶段。原交接中的 NEXT PROMPT 是历史接续入口，不应再次照单重复已经完成的测试。
