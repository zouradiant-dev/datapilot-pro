# Final Full CI Recovery：恢复与推送前验收

2026-11-01。**Full CI Collection：PASS；Python 3.11/3.13 Full CI：NOT_RUN；Product Core Changes：NONE；GitHub Push：AWAITING_APPROVAL。**

本轮仅恢复完整CI配置、核对身份并准备独立本地fix(ci)提交，不进行P7功能开发、业务实验或新的测试迁移。

## 基线与历史结果

- 分支 `p7-engineering-candidate-v1`；开工本地与重新读取的GitHub远端均为 `2f2f1694525cf2d677d9df13a449090836f1e731`，已跟踪工作区干净。
- 已读AGENTS、原 #22 workflow、#23–#27下载结果与Seal、Final Migration Handoff。开工八份未跟踪CI/Docker报告原样保留，不纳入本次提交。
- 原始完整workflow取自 #22 提交 `607e68c988121e0e686ee36f740e601a5f8e0e86` 的Git blob，原件保存在本地 `artifacts/p7/full-ci-recovery-v1/ci22-original-workflow.yml`。
- 重新通过GitHub API确认 [#27](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41297581713) attempt 1/success/目标SHA。此前 #23 的4项、#24 的10项、#25 的14项、#26 的1项、#27 的31项累计覆盖原60个失败身份，原失败与STOP记录不覆盖。
- [31项验收记录](p7-ci-final-migration.md)的本地快照和同名Actions后续结果分别保留；累计60/60是跨Run/提交证据，不是完整CI结果。

## 最小配置恢复

唯一既有修改文件为 [.github/workflows/test.yml](../../.github/workflows/test.yml)，Diff **4 additions / 37 deletions**：

1. 名称恢复 `DataPilot checks`，删除临时Job名称。
2. 移除全部31项Node白名单，PG步骤恢复原名称和**完全相同**的完整命令：

```bash
uv run --locked python -m pytest -m integration -p no:cacheprovider --junitxml=artifacts/ci/integration.xml --cov=datapilot --cov-append --cov-report=term-missing --cov-report=xml:artifacts/ci/coverage.xml 2>&1 | tee artifacts/ci/integration.log
```

3. 原证据步骤新增完整范围元数据：`scope=full-ci`、`full_ci=true`、`planned_tests=1724`、`planned_pg_tests=388`、`planned_nonintegration_tests=1336`。**full_ci=true表示计划执行范围完整，不表示CI已经通过。**

移除此元数据行后，新workflow与原 #22 完整workflow逐字节相同。Python3.11/3.13、PG17/pgvector镜像digest、独立服务、全部角色与DSN、迁移/runtime-init/新CI库Seed/健康检查、固定BGE、uv锁定版本、完整非集成marker、Ruff、格式、JUnit/coverage、pipefail/退出码、always工件上传及权限都保持原版。没有新增基础设施、默认重试、continue-on-error、忽略规则或隐藏选择器。

## 双版本完整身份核对

| 检查 | Python3.11 | Python3.13 |
|---|---:|---:|
| 全量 `--collect-only` | **1724 collected**，3.48秒 | **1724 collected**，3.36秒 |
| 全量 integration 收集 | **388 collected**，3.36秒 | **388 collected**，3.28秒 |
| 原60个失败身份在完整integration中 | **60/60** | **60/60** |
| 既有workflow合同测试 | **5 passed / 0 failed / 0 errors / 0 skipped**，0.10秒 | **5 passed / 0 failed / 0 errors / 0 skipped**，0.10秒 |
| 完整CI实际执行 | **NOT_RUN** | **NOT_RUN** |

Integration收集的1336 deselected是命令原有 `-m integration` 正常排除非集成测试，不是从完整范围删除测试，也不计作PG通过。当前预计非集成1336项；本轮本地只执行必要的5项workflow合同检查，不冒称重新运行了1336项。

两版388项集成身份及顺序**严格一致**，SHA256：

```text
d3fbd0dfb3141f3277d6775973671a93a9353af507f04d7ea2b8a82a8d9f604d
```

原 #22 全量1717项与当前1724项比较：没有删除原测试，增加的7个单元控制来自此前已批准的迁移提交，本轮没有增删测试。

有且仅有一个原有动态参数需要显式比较说明：

```text
tests/test_qwen_lifecycle.py::test_process_metadata_cannot_target_current_or_system_process[PID]
```

其源码在 #22 与当前提交字节完全一致，参数为 `[0, 1, -1, os.getpid()]`。原 #22 收集PID为2621，#27为2634，本地双版分别26856/17132。原始身份全部保存；比较时只给该唯一self-PID参数使用 `<current-process-pid>` 标签，0/1/-1三个安全负例及其余所有身份仍严格比较，不更改测试、pytest参数或报告。初次原始集合比对因这个动态值停止，诊断记录保留，没有用修改测试掩盖差异。

除此self-PID差异外，本地全量身份与 #27 一致；两版规范化全量清单SHA均为 `0069093b2512897a8bd2be780f0a9d101fd8873e6dea281b19fdde50e4a85e32`。原60项均不需要任何身份别名。

## opt-in、skip与安全边界

测试文件、Marker、skip/xfail、testpaths、Goal v4/P3/Citation/Report/Durable/Journal/Ledger、BGE/Qwen配置、业务源码、依赖与锁均未改；没有新增skip或缩小测试路径。

保留 `DATAPILOT_LLM_MODE=fake`、空API Key、Live开关0；Qwen/CUDA仍遵守原独立opt-in，没有强制GPU或付费调用。本地driver清除继承的DATAPILOT环境并关闭DB/Live/Qwen执行；收集不执行数据库fixture，没有连接用户数据库或Docker数据盘。

**历史 #22 的合法skip为63项，不是本轮实际skip结果**：

| 原skip理由 | 历史项数 |
|---|---:|
| Explicit real CUDA Qwen test opt-in required | 10 |
| Explicit real Qwen CUDA opt-in required | 18 |
| Explicit local Qwen integration opt-in required; never substitutes vectors | 20 |
| Explicit real CUDA test opt-in required | 13 |
| Explicit local CUDA opt-in required | 1 |
| Live model inference requires DATAPILOT_RUN_LIVE_TESTS=1 and API credentials | 1 |

合计62项Qwen/CUDA opt-in及1项Live opt-in，63个原身份仍在完整388项中。在相同环境下预计继续由原守卫处理；真实完整CI执行前，不能宣称63 skipped或325 PG passed已经发生。推送后须逐项读取实际JUnit，任何新的skip/缺失/xfail或失败都要单列说明。

## 静态、完整性与证据

`ruff check .`、`ruff format --check src tests scripts migrations evaluation`（349文件）、YAML解析与原版等价检查、JSON/Markdown本地引用、`git diff --check`均通过。

本轮实际核对203份已有交付/诊断/Seal引用文件，SHA保持原值；完整性限于这些文件与Git修改范围，不冒称历史数据库或全部历史文件树复验。没有修改旧Gold/Scorer/Seal/STOP或历史Run。

本地证据目录 `artifacts/p7/full-ci-recovery-v1/` 保存原workflow、`before.json`、完整原始Node清单、双版all/integration collection日志与JSON、双版5项JUnit、静态日志、`audit.json`、交付与Commit记录。摘要见[机器记录](p7-full-ci-recovery.json)，接续见[Handoff](p7-full-ci-recovery-handoff.md)。

## 本地提交与推送计划

创建独立 `fix(ci): restore complete dual-version regression workflow` 提交，白名单仅workflow和本轮三份交付文件。完整SHA由最终答复与本地 `commit-verification.json` 记录，避免自引用提交Hash。八份既有未跟踪报告、私密工件及大型文件不暂存；不使用 `git add .`。

**当前没有Push，没有新的完整Actions Run。** 等待用户明确确认完整CI推送后：

1. 重新确认分支、唯一本地提交、远端仍为本轮基线及四文件白名单，普通fast-forward Push，不强推/合并main。
2. 让同一workflow仅由这次push触发一次双版本完整运行；不额外dispatch或重跑。
3. 下载两版完整Job日志、JUnit、Artifact，验证ZIP digest、Commit、scope=full-ci、源码SHA、1724个完整身份、388项PG及全非集成分母；收集与unit阶段的self-PID参数可依上述唯一规则不同，其他身份严格验证。
4. 若成功，分别报告真实非集成/PG passed、failed、errors、skip及理由；若失败，保存精确Node/异常和日志，只归因，不修改、补提交、重跑或扩大开发范围。

完整回归可能暴露定向运行未覆盖的顺序/隔离或其他真实问题，不能预先承诺全绿。本轮完成本地提交后停止。
