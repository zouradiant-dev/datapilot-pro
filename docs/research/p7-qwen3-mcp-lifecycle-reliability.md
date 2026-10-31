# P7 Qwen3 MCP Lifecycle & Deployment Reliability

验收日期：2026-10-30（Asia/Shanghai）。本次是可信本地单用户、Windows/WSL2 Docker 的工程验收。**受测配置满足进入独立 Phase 2C 业务质量验收的工程前提；业务质量、生产切换和付费 Live 尚未批准或验收。** 本阶段结束，不进入 Gate 3。

## 身份与范围

- Git 基线：`p7-ci-verification-20261028` / `f8b122438d2c67ab26e618ecded72ecc18454015`；全部既有未提交修改保留，没有 commit/push。
- 新工程 Freeze：`qwen-lifecycle-v1-77ceb2a7eaca`，335 个源码/测试/配置文件；Manifest 文件 SHA256：`776a2f11b9d3a28509391dd6c4c5eaa7f48e16354ef85b97f90f93b447fd2d4b`。
- Freeze payload SHA256：`77ceb2a7eaca547c4945d24c770138d89041cfd62ea75ea37c72ba8816ccc5f2`；它与 Manifest 文件 SHA 是不同校验对象。
- 实际宿主与 release 镜像的 Runtime source SHA 均为 `e9e252b1b834d5cc3ce2271ef00af4f0e437096d9d1e113c5c756172a1d1222c`。
- 实测镜像：`sha256:420275aadc6a09eb3481791d4a83c0cc72268a6a6b7d0367e84842025ef3cd25`（`datapilot-qwen-lifecycle:release`）。旧 `:final` tag 是父退出修复前的镜像，不能据 tag 名认作最新。

完整计数和机器记录见[结果 JSON](p7-qwen3-mcp-lifecycle-reliability.json)。本地私密证据目录为 `artifacts/p7/qwen-lifecycle-v1/`；源码快照在 `final-source/`，Manifest 在 `implementation-freeze.json`。这是新的工程冻结，没有替换任何旧 Holdout/Gold/Scorer/Freeze。

## 实际修改与设计原因

相对 Phase 1 起点 `before.json`，七个原有文件发生变化：

| 文件 | 作用 |
| --- | --- |
| `rag/mcp.py` | 同一个 FastMCP/stdio 的显式宿主准备、READY 校验、可信 Runtime/PID 绑定；保留 BGE 原同步工具执行方式 |
| `rag/models.py` | 原工厂向 Qwen 传入可观测 observer；默认模型不变 |
| `rag/qwen.py` | 固定解释器和依赖验证；记录导入、Hash、CUDA、权重、预热；资源不足拒绝 |
| `runtime/mcp_client.py` | 固定 `-I` 引导、自有进程清理；Linux 导入模型前绑定父退出信号 |
| `tests/qwen_delay_server.py` | 真实模型初始化/编码/GIL 阻塞的测试故障，不制造检索向量 |
| `tests/test_qwen_migration_postgres.py` | CPU/GPU 可选择的既有夹具，补缓存、并发、超时、断连和退出验证 |
| `AGENTS.md` | 固定本轮权限、部署与生命周期边界 |

新增产品实现只有三块：`rag/lifecycle.py` 管当前会话模型缓存与资源守卫；`rag/qwen_runtime.py` 管固定环境 attestation；`runtime/owned_process.py` 管 OS 验证的进程句柄/pidfd。新增部署文件是 `Dockerfile.qwen`、`requirements/qwen-mcp-linux.lock`；新增测试/探针是 `test_qwen_lifecycle.py`、`qwen_parent_exit.py`、`evaluation/qwen_lifecycle_probe.py`。

没有新 MCP 服务、Scheduler、Verifier、Journal、预算账本或恢复引擎。当前续接仅补验并写交付记录，没有再修改产品源码。私密工程辅助脚本仅用于显式验收，不注册模型工具。

## 生命周期与时间线

实际链路为：固定解释器 → `-I` 固定源码引导 → MCP handshake → Scope/索引/Runtime/PID 校验 → 宿主 `prepare_embedding` → 容量/RAM 校验 → 后台模型导入/文件 Hash/权重/CUDA → 显式预热及向量校验 → READY → Search → 关闭。

`health.protocol=ready` 只表示协议可用；模型状态另分 `not_started/loading/ready/failed/stopping`。没有就绪就调用 Search 会拒绝，不能隐性加载。准备总上限 60 秒；每次准备/health/Search RPC 仍受原 **10 秒**限制。`prepare_embedding` 不是任何 Worker 的 capability，模型不能选解释器、初始化服务或扩大 Scope。

以下为完整性能探针的单个新进程样本；磁盘/OS 缓存未清除，不代表断电冷启动分布：

| 阶段 | Windows CUDA | Linux CPU | Docker CUDA |
| --- | ---: | ---: | ---: |
| spawn 到 Python bootstrap 首条记录 | 未单独取得同源起点 | 31.1 ms | 32.1 ms |
| transport：启动、框架导入、handshake | 记录于原始 startup trace | 1.344 s | 1.264 s |
| 显式就绪，总计含 transport | 9.48 s；另一次 11.78 s | 13.44 s | 16.19 s |
| 20 次实际 MCP Search，p50/p95 | 49.7/68.4 ms | 189.3/266.9 ms | 37.4/63.7 ms |
| 会话关闭清理 | 0.390 s | 0.056 s | 0.079 s |
| Python 子进程采样 RSS 峰值 | 2.50 GiB | 3.98 GiB | 3.13 GiB |

bootstrap 时间包含进程创建及少量标准库导入，不伪称纯解释器指令耗时。transport、准备、工具调用和退出分别记录，不能把它们都写成 Search 延迟。p50 为中位数，p95 为 nearest-rank，不将分位数相加当 Run 延迟。

最终源码的 Linux CPU 容量用例另保存了完整分阶段记录：imports 约 3.97 秒、模型文件 Hash 约 4.66 秒、tokenizer 约 0.29 秒、权重约 6.32 秒、设备转移约 0.002 秒、预热约 0.275 秒；就绪含连接 17.12 秒，关闭 0.057 秒。原始 `capacity-and-cache.json` 在 `linux-cpu-final/tests/qwen-*/`。其他完整时间线在 `windows-gpu-performance-r1.json/.log`、`linux-perf/*-performance.json` 和 `linux-*-perf*.log`。

性能探针早于最后的 Linux 父退出绑定；最后补丁没有调整推理/检索参数。最终源码 CPU 记录、CUDA 引用/恢复和 GPU 父退出已另验，未为重新制造性能分数重复压测。旧 34 秒冷加载长尾保留：本次解决的是可观察、有界的独立准入，**没有把所有冷启动优化至 10 秒以内**。

## 超时、取消与硬退出

| 真实故障注入 | 调用响应 | 后续清理 |
| --- | ---: | ---: |
| 修复前 30 秒编码阻塞 | 10.016 s 超时 | 20.088 s |
| 修复前初始化取消 | 0.206 s | 29.934 s |
| 修复后编码阻塞 | 10.005 s 超时 | 0.268 s |
| 修复后编码取消 | 0.201 s | 0.281 s |
| 修复后 GIL 阻塞 | 10.003 s 超时 | 2.043 s |
| 修复后初始化取消 | 0.210 s | 0.016 s |

以上为原产品连接器、真实 PG/MCP、真实模型上的受控延迟，不是业务质量实验。原 `before-cleanup.xml` 的两项通过只覆盖调用返回，未约束旧清理尾部；实际不满足清理目标的旧日志不删除。

父进程用已验证句柄/pidfd 设置 2 秒硬清理截止，不按进程名批量终止。Qwen 子进程只有 Reader，没有 P3/Journal 写凭据，因此清理不能半提交业务写入。异步 SDK 关闭错误保持明确 TOOL_ERROR；BrokenResourceError 另有单元注入覆盖，不能冒称全部真实网络故障已经验收。

Linux 硬退出曾出现额外反例：客户端 `os._exit(91)` 后，GIL 阻塞的模型进程在 3 秒检查仍存活。最小修复是在固定 Linux 引导中执行 `PR_SET_PDEATHSIG(SIGKILL)`、核对父 PID 未变化；失败则拒绝启动。原故障 before JSON 为 false，最终 CPU 与本轮真实 CUDA 复验的 `cleanup_passed` 均为 true，无存活子进程。证据在 `linux-perf/parent-crash-{before,after}.json`、`gpu-parent-after-20261030.json`；Windows 同类硬退出也有原始通过记录。

异常子进程退出、客户端断开、PG 查询执行超时、同会话超时后已确认回滚均通过真实测试。已 issued 的工具未知结果恢复继续返回 `RECOVERY_UNCERTAIN`，没有自动重发或生成成功收据。P5B Journal/Checkpoint/Ledger 核心未改。

## 并发与资源竞争

同会话只加载一次模型；第一 Search 的 query/goal 编码两次，后续只编码 query，Goal 缓存确实复用。会话内并发搜索有界拒绝，第二模型会话也明确返回 `EMBEDDING_BUSY`。原 Worker 两次检索预算没有变化；20 次性能调用是可信宿主直接探针，不是模型业务 Run。

复用 PG 会话 advisory lock `(7512,6001)` 管同一部署数据库的模型容量，CPU/CUDA 共用；客户端最多两个待准入 Qwen 会话，失败不排队重试。CPU 已就绪时另一个合法 CUDA Scope 的真实拒绝已验。它不是跨库、跨主机全局 GPU 调度器。

CPU/RAM 准入下限分别为 4/3 GiB，CUDA 可用显存下限 2 GiB；没有为通过测试降低门槛。实际 2 GiB cgroup 在约 1.51 秒返回 `EMBEDDING_RESOURCE_LIMIT`，加载次数零。构建期间两次 Windows 低 RAM 拒绝日志保留。资源锁失效由会话守卫失败关闭。

目标实机为 i9-14900HX、16 GiB RAM、RTX 5060 Laptop 8151 MiB、驱动 582.05；Linux 容器限制 4 CPU、8 GiB，并使用只读根/模型挂载。Windows GPU 总用量采样峰值 1403 MiB，前后基线均 83 MiB；这不是 Torch allocator 精确峰值。模型退出后探针确认进程不存活。压力准入与受测并发通过，不据此宣称无限并发、通用 OOM 保证或产品 SLO。

## Linux、Docker 与可信环境

固定 `.venv-qwen`：Windows Python 3.11.16、Linux Python 3.11.14；Torch 2.8.0+cu128、Transformers 4.57.1、Tokenizers 0.22.2。Windows/Linux 独立 lock，模型六文件、Tokenizer、1024 维 ModelSpec/Recipe 与 policy SHA 保持 Phase 1 原值。

可信部署先按平台 hash lock 安装，再显式执行 `python -m datapilot.rag.qwen_runtime --install`。验证固定 prefix、解释器/base binary、venv 配置、依赖锁、完整包版本清单及模块来源；子进程实际绑定还需与宿主一致。MCP 不自动安装、下载、改 attestation 或从环境/PATH/模型参数选择解释器。父宿主可以持有管理配置，但 Qwen stdio 只传 RAG Reader、Scope 和有限基础环境，不传 API Key/管理员/Registry/Runtime 凭据。

本轮四项真实部署负例通过，均未到 READY、无自动重试、结束后没有存活子进程：

| 负例 | 路径与结果 |
| --- | --- |
| 无 CUDA 运行 CUDA Profile | 完整 rag_session；实际 cuda_available=false，EMBEDDING_NOT_READY，不切 CPU |
| 模型缺失 | 新容器只读覆盖空目录，原缓存不动，EMBEDDING_NOT_READY |
| 模型坏 Hash | 新容器只读覆盖六个合成非法文件，原权重不动，EMBEDDING_NOT_READY |
| 环境清单漂移 | 新容器覆盖合成错误 Torch 版本清单，约 0.009 秒拒绝，未派发模型 |

原始 JSON/日志与可复验辅助脚本在 `deployment-checks/`、`deployment-negative-v2.py`。其中原字段 `model_requests=0` 指远端模型 API，没有否认本地初始化尝试。没有把坏模型转成 fixture 向量或将 CPU 通过冒充 GPU 通过。

镜像复用原 pinned Python/uv 基础配置与现有 PG17/pgvector 网络，独立 Qwen lock；未引入新数据库类型或第二套测试服务。恢复 Docker 引擎后只启动原隔离 PG 容器，未迁移、Seed 或清理原库。这不是 Gate 3 的故障注入实验。

## 回归结果与版本归属

| 验证 | 真实结果 | 版本说明 |
| --- | --- | --- |
| Windows Python 3.11/3.13 非集成全回归 | 各 992 passed | 最后 Linux 父退出引导之前；保留，不冒称补丁后重新全跑 |
| Windows CUDA 专项 | 17 + 1 + 2 个不同用例通过 | 原 20 项，补丁之前；Windows 执行行为未变 |
| 最终源码 Python 3.11/3.13 定向 | 各 55 passed | Lifecycle/ModelSpec/RAG/真实 SDK 协议，补丁之后 |
| 最终 Windows 3.13 宿主 Qwen | 2 passed | 真实 CUDA Goal/Citation、跨进程恢复；子解释器固定 3.11 |
| 原 Windows BGE/P3 3.11 定向 | 81 passed | 原 77 + 4 个持久证据/unknown 用例；始于 Linux 补丁之前，原 BGE 路径不使用该分支 |
| 最终 Windows BGE/P3 3.13 定向 | 81 passed，805.51 s | 使用预建的独立 py313 库；P3/引用/恢复真实 PG/MCP |
| 最终 Linux CPU | 56 passed，0 skipped，489.28 s | 已收集上轮已启动容器，**没有重跑**；含全部 20 项真实 Qwen PG/MCP |
| 最终 Docker CUDA | 2 passed，18 deselected，106.88 s | 父退出补丁后 Goal/Citation、跨进程恢复 |
| CPU/GPU 父退出 | before 失败；after 通过 | 原始反例、CPU 修复后与本轮 GPU 均保留 |
| 四个真实部署负例 | 4/4 按预期拒绝 | 不属于业务完成率 |

不把这些交叠的单元/集成计数相加当独立业务任务分母。全部完整日志/JUnit 名称由结果 JSON 列出。真实向量、PG/MCP、宿主确定性或 Fake/脚本模型的工程结果，与真实 DeepSeek 自主多轮质量严格分开。

本轮没有重跑已有可信的全套 992 或 Linux CPU，按最后补丁范围补验。最终源码与交接文件清单逐项一致；宿主/release Runtime source SHA 一致。Ruff check、format 和 Diff 的最终检查见结果封存。

## 失败历史、数据与持久兼容性

保留 `qwen-capacity-r1` 的 1 failed：首次触发既有 lock_timeout，错误为 RAG_DATABASE_ERROR；测试改为在 500ms lock_timeout 前触发 250ms statement_timeout，后续通过，未改生产超时或错误分类。保留探针首次缺源码路径、Windows 低内存、旧恢复忙碌/宿主身份不匹配等失败；没有删除测试或降低断言。

旧 Qwen Run `387abd55-6006-4151-a777-b88306fe9af3` 的原 Artifact/调用记录/预算重复恢复不变：2 artifacts、6 journal calls，succeeded/completed。原 BGE 与 P3 跨节点/跨进程恢复用例验证 Evidence/Verification ID、hash、verdict 不变；unknown 不能重发。这里没有重新执行历史 Holdout 或修改旧 Evidence。

仅在既有隔离实例 55441 中使用本轮两库：`datapilot_test_qwen_lifecycle_v1_20261029` 和 `datapilot_test_qwen_lifecycle_v1_py313_20261029`。py313 新库没有 Seed，本轮已完成 81 项回归；测试按原夹具追加/操作自己的合成记录。没有向 demo 55432、历史评测库或旧业务数据发出写操作，没有删库/卷。

Phase 1 Seal 的 292 文件在改动前快照中逐项一致；原 A/B 77、Live Smoke 136、Scorer 修复 29 文件的 Seal 再次通过。原 Gold、失败、31 observed/29 not_run、旧付费记录和模型响应不改。P3、Reporting、Persistence、SQL 安全及迁移目录与本任务起点 Hash 一致；原用户 v2.4/v2.5 规划不改。

原 Phase 1 Seal 校验其 `phase1-snapshot-root/`，新源码校验本次 Freeze，不能混称旧 Seal 对当前根目录仍全部成立。

本地结果封存首次读取 Linux pytest 的 `tmp-r1/*current` 临时符号链接时遇到 Windows WinError 1920。错误记录保留为 `seal-build-attempt1.log`；最终只排除 pytest 临时目录/别名及私密凭据，原件不删除，JUnit、真实结果、故障日志和源码快照继续校验。这是封存辅助步骤的失败，不改写为测试失败或测试通过。

## 复验入口与剩余边界

Windows 定向命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_qwen_lifecycle.py tests/test_qwen_migration.py tests/test_rag_contracts.py tests/test_mcp_protocol.py -q -p no:cacheprovider
.venv-313/Scripts/python.exe -m pytest tests/test_qwen_lifecycle.py tests/test_qwen_migration.py tests/test_rag_contracts.py tests/test_mcp_protocol.py -q -p no:cacheprovider
```

真实 PG/MCP 的 81 项清单及私密环境加载方式见[交接记录](p7-qwen3-lifecycle-handoff.md) §8；它是历史交接快照，末尾已追加实际收尾状态。不要重跑初始化或覆盖原输出。Docker 可按以下原命令结构复验，执行前确认模型已显式部署且 env-file 只绑定获授权的新隔离测试库；本次不再执行：

```powershell
$root=(Get-Location).Path
$resultDir=Join-Path $root ('artifacts/p7/qwen-lifecycle-v1/recheck-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $resultDir | Out-Null
docker run --name ('qwen-recheck-'+[guid]::NewGuid().ToString('N')) `
  --network datapilot-p7-unified_default --memory 8g --cpus 4 --read-only --tmpfs /tmp:rw,size=512m `
  --env-file "$root/artifacts/p7/qwen-lifecycle-v1/linux-environment-private.env" `
  -e PYTHONDONTWRITEBYTECODE=1 `
  --mount "type=bind,source=$root/.cache/rag-models,target=/app/.cache/rag-models,readonly" `
  --mount "type=bind,source=$resultDir,target=/app/artifacts" `
  sha256:420275aadc6a09eb3481791d4a83c0cc72268a6a6b7d0367e84842025ef3cd25 `
  /app/.venv/bin/python -m pytest tests/test_qwen_lifecycle.py tests/test_qwen_migration.py tests/test_qwen_migration_postgres.py `
  -q -p no:cacheprovider --basetemp=/app/artifacts/tmp --junitxml=/app/artifacts/result.xml
```

上例是 CPU。CUDA 复验显式加 `--gpus all -e DATAPILOT_QWEN_TEST_PROFILE=qwen3-cuda-fp16-v1`，并按需要选既有用例，不能把 CPU 通过算作 GPU 通过。部署负例 helper 与原件在 `deployment-checks/`；只读嵌套挂载分别覆盖模型目录或 attestation 文件，原模型绝不修改。探针代码/结果均纳入本地封存，凭据文件不入 Seal 或报告。

边界：每个新 stdio 会话仍会冷加载，模型不跨 Run 常驻；容量保护限同部署库，非全主机调度；本机小样本长尾不代表并发 SLA；锁定的独立环境升级需重新验收，3.13 宿主通过不表示 Qwen 依赖也支持 3.13；远端 CI、其他硬件/容器平台、Gate 3 故障矩阵、真实业务质量与付费 Live 均 NOT_RUN。现有 GPU/CPU 和取消/硬退出结果只覆盖记录的配置与故障。

结论：受测的本地 Phase 2A/2B 工程能力通过，允许以此为依据申请下一阶段独立业务质量验收；不自动进入 Phase 2C、不切生产、不发起付费请求。本轮停止。
