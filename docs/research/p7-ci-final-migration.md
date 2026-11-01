# CI Final Migration：剩余 31 项本地契约迁移

2026-11-01。**本地定向回归 PASS；双版本各 31 项精确收集 PASS；本批真实 PG/MCP NOT_RUN；未 Push；Full CI NOT_VERIFIED。**

## 基线、历史与身份冻结

分支 `p7-engineering-candidate-v1`，开工本地与重新读取的远端均为 `b3328e003cf5e1fc997c28c2228bf23209562699`。开工已跟踪工作区干净，七份既有未跟踪 CI/Docker 报告全部保留并排除本次提交。

已读取 AGENTS、#22 归因及机器记录、Batch 1/2/3、CI25 修复与 Handoff、ADR-018/019、Engineering Freeze/Demo Acceptance，以及 #23–#26 实际下载结果。历史结论保持：#23 验证 4 个原失败，#24 验证另 10 个并有 1 个 P3 控制，#25 验证另 14 个且 1 个构造失败，#26 修复最后这 1 个。原 #25 的 failure 不被覆盖。

[Actions #26](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41295087030) 双版各 1334 非集成和 1 PG passed 是历史证据，不冒充本次测试结果。当前原失败分母仍为 **29 已获双版真实 PG 验证 / 31 待验 / 合计 60**。

修改前从原 #22 两份真实 JUnit、失败分类与 #26 进度逐项核对剩余身份：共 31，全部存在于原 60 个失败中，与已验证 29 项无交集。完整原 Node ID、参数、期望终态、依赖和逐项断言审计索引在[机器记录](p7-ci-final-migration.json)，未改名或另造替代身份。

冻结清单 `artifacts/p7/ci-final-migration-v1/nodeids.json` SHA256：

```text
b40ea5dc24dfdf22cfa9272b28e2e5e2c232a9e990fa610c4f93b2a6b1f01a0d
```

原断言完整表达式、原 pytest.raises、失败摘录与函数源码在修改前 `before.json`；修改后对应表达式在 `audit.json`。这些忽略工件不上传，不将静态表达式一致称为运行期已经到达。

## 29 项共享前置条件迁移

| 原 #22 编号 | 数量 | 修改位置及保留语义 |
|---|---:|---|
| 9–14、16 | 7 | `test_cross_source_postgres.py`：五指标、跨节点、注入测试的最终完整合同走原 Host 确认。注入 Corpus 完成绑定后才确认检索范围；原 P3 Gold、六层验证、证据、图表、partial 与禁用工具断言不变，确认不认证恶意正文。 |
| 24–27 | 4 | `test_document_fact_postgres.py`：把明确审阅的 absence/partial/summary/causal 加入既有确认分支。保留 missing/year 原流程；不改事实、引述或 Worker，确认不补事实与因果证据。 |
| 29–32 | 4 | `test_host_goal_postgres.py`：只在 complete/partial/causal 正向有限用例及恢复用例确认。missing/exhaustive/unrelated_required 不自动确认，共享 `configured` 不变。 |
| 34–39 | 6 | `test_host_goal_safety_postgres.py`：仅对 complete/negative/partial/required_gap/causal 显式确认，未知集合和穷尽负例不确认。恢复用例的正式确认同时适用于同函数的旧 v2 拒绝分支，原拒绝和快照断言不变。 |
| 42–47 | 6 | `test_original_query_postgres.py`：最终 cp12、四 cut-point 及第二次搜索配置固定后确认。不改原问题、搜索词、Top-k、预算、四次切点、调用次数、Artifact 或 Journal 断言。 |
| 52 | 1 | `test_partial_evidence_postgres.py`：仅给这一跨节点 partial 用例确认，原 Required/Fact 不足、refs 和预算复用断言保留。 |
| 54 | 1 | `test_phase12_postgres.py`：明确固定 `causal_requested=False` 后确认，原真实 P3、文档、Inspector、Evidence/Verification 不变断言保留。 |

所有确认调用复用原 `confirm_finite_scope`；没有新增共享审批器，没有更改 `host_scope`、`scope_for`、`scenario`、`configured`、`config_for`、`new_config` 或 session fixture，没有直接创建 Attestation、修改 reviewed 或手写授权 Hash。这些是公开合成测试的显式 Host 决定，绝非独立人工语义审查。

有限因果问题仅确认“需要检查什么”，仍不能证明因果成立。Required Source/Fact、Semantic/Metric/window、原 Gold 与全部预期终态未变。参数化函数的这些构造也可能作用于未来显式 opt-in 的 Qwen 参数，以及上述 legacy=True 控制；本轮只收集指定 BGE/False 身份，不执行额外 PG 参数，也不声称那些参数已新验收。

## 两项低信任入口裁决

**58：语义相关性与原目标绑定。** 原测试要验证语义相关/不相关、来源 goal hash 和篡改拒绝，并非赋予 facade 自动审查权限。新增同原问、同模型搜索词的旧 `run_question` 负向控制，必须 blocked，提交 insufficient。正向结果改由已有 `Coordinator(rag_task_scope=...)` 与正式 Host 确认的同一完整问题提供。原 receipt、completed/blocked、相关性、错目标与篡改 raises 全部保留；不改成字面定位问题。

**59：语义检索的 Durable 恢复。** 先以旧无确认入口建立另一个新测试 Run，必须 blocked 且无 succeeded 任务；然后以同一原始语义问题，通过既有 `run_durable(report_scope=...)` 开始独立的已确认 Run。原 cut-point、3 次模型调用、两次 resume、调用表/usage 相等、语义 receipt、搜索次数和 Trace 不泄漏断言保留。

为第二项，仅给既有测试探针 [scripts/rag_recovery_probe.py](../../scripts/rag_recovery_probe.py) 增加可选 `--report-scope`：读取测试宿主已确认的 ReportScope JSON，交给原 Durable；没有在探针签发确认。参数仅用于 semantic 场景，不提供时保持旧行为。收到宿主 report-plan Prompt 时复用现有 `ReportDecisions` 的计划生成；RAG Worker 搜索/提交、usage、错误和 cut-point 逻辑不变，不新增调度器或 Agent。

产品 `run_question`、`run_durable` API 均未变。旧 facade 自主语义 completed 的权限不恢复，合法能力由可信 Host 正向路径覆盖，因此不需要修改产品协议或把这两个身份删除/skip/xfail。**真实 PG 下的新接线与 3-call 恢复尚待验收，不能只凭本地单元宣布兼容完成。**

新增的两个非集成控制位于 `test_rag_completion.py`：相关文本没有 Host 确认仍须经过一次原纠正后拒绝，Ledger 包含 Planner 共 4 次 Fake 调用；测试探针复用的 Host 计划仍包含原 rag 和依赖它的 report，usage 与既有脚本一致。这些是明确的测试替身，不是真实模型。

## 原断言和修改范围

31 项逐项 AST 核对：原 assert 与 pytest.raises **删除或修改 0**。原终态、金额/单位、P3 Gold、6 层验证、Source/Fact、tool call ID、调用次数、预算、切点和错误码均保留。31 个参数身份共用 15 个测试函数；同一函数的表达式按每个参数留有独立审计记录。真实 PG 前，是否到达下游安全层仍记录 NOT_VERIFIED。

修改仅 11 个既有文件：八个 PG 测试模块、一个非集成 RAG 测试模块、一个既有测试探针及一个现有 workflow；另加本轮三份交付。没有改产品 `src/`、依赖/锁、数据库迁移、测试夹具、Gold/Scorer/Seal/STOP 或 AGENTS。原控制与共享工厂 AST 保持，未出现需要保留的新通用抽象或可删除的重复确认框架。

检查了 **117 份**既有诊断/交付/Actions 工件及 Seal 引用文件，SHA 与开工记录一致。完整性限于实际检查的文件及 Git 修改范围，不冒充历史数据库或全部历史文件树复验。未连接或写入任何数据库，未启动 Docker 或接触 VHDX。

## 实际本地验证

最终测试与后续静态审计的源码 SHA 一致：

| 检查 | Python 3.11 | Python 3.13 |
|---|---|---|
| 14 个相关模块的定向合同/安全回归 | **281 passed / 0 failed / 0 errors / 0 skipped**，8.10 秒 | **281 passed / 0 failed / 0 errors / 0 skipped**，8.60 秒 |
| 原 31 项精确 collect-only | **31 collected**，2.69 秒，身份/顺序相同 | **31 collected**，2.59 秒，身份/顺序相同 |
| 本批真实 PG/MCP | **NOT_RUN** | **NOT_RUN** |

非集成回归另有 6 项被 `not integration and not live` marker 排除，不计为通过或这 31 项的跳过；31 项独立收集没有 skipped/deselected 或额外身份。最初新增的两个控制在 Python 3.11 单独 **2 passed**，其后已包含于双版 281 项中，不能重复计为额外业务成绩。

日志、JUnit、命令与工作区 SHA：`artifacts/p7/ci-final-migration-v1/` 内 `controls-py311.*`、`final-py311/313.*`、`collect-py311/313.*`、`before.json`、`audit.json`。可复核命令入口为本地 `run_local.py`；已有结果禁止覆盖或无故重跑。

`ruff check .`、`ruff format --check src tests scripts migrations evaluation`（349 文件）、YAML/JSON、Markdown 本地引用与 `git diff --check` 通过。准备阶段的历史结果 Schema 键、YAML dedent/UTF-8 读取假设错误和首次 import 排序提示均留有本地记录；它们不是产品失败，没有因此重写旧结果、放宽断言或启动 PG。

## 定向 CI 准备与提交

复用 [.github/workflows/test.yml](../../.github/workflows/test.yml)，名称 **DataPilot CI Final Migration — 31 Cases — NOT FULL CI**。双版矩阵、PG17/pgvector 固定镜像、角色/迁移/新服务初始化、BGE、锁定依赖、完整非集成、marker、coverage、JUnit、pipefail 与 always 上传均保持；只改身份/Scope 与 31 个精确 PG 选择器。

机器范围：`scope=ci-final-migration-31`、`planned_pg_tests=31`、`full_ci=false`。Unicode 参数转义以原 JUnit/pytest Node 为准，YAML 单引号和 CLI 列表均逐项保留；不靠缩小 testpaths 隐藏其他测试。

本报告随独立本地 `fix(test): migrate final 31 CI contracts without changing trust boundaries` 提交。完整 SHA 由最终答复和本地 `commit-verification.json` 记录，避免向文件写入它所属提交的自引用 SHA。提交白名单仅 11 个修改文件及本轮三份交付；七份既有未跟踪报告与所有私密/大型工件不暂存。

**未 Push、未触发本批远端 CI。** 必须等待用户明确回复“确认最终31项定向推送”，再重新核对远端仍为基线、唯一提交及白名单，普通 fast-forward 推送，不强推/合并/PR。定向执行失败只收集完整证据归因，不自动补提交或重跑。

## 完整 CI 恢复方案及风险

当前累计真实验收仍是 **29/60**，不能因 31 项收集通过更新成 60/60。若后续这 31 个精确身份均获双版真实 PG 证据，才另行申请完整统一回归。

完整工作流须恢复原 #22 的全部集成命令（移除临时 Node 选择器，保留 `uv run --locked python -m pytest -m integration` 的全部原有 JUnit/coverage/marker/退出状态参数），继续完整非集成、HTTP/RAG/P3/Report/Durable、双 Python、Ruff/format、锁定依赖与独立 PG 初始化；不得只跑最近的 60 项。Qwen/CUDA 与付费 Live 继续原 opt-in，不暗中转为必跑或削除测试。完整 CI 必须由下一次独立授权启动。

主要风险：真实 pgvector 召回、P3 引用、已确认合同持久绑定、注入报告拒绝和新 Host 报告接线的 3-call 跨进程恢复未在本轮执行，补前置条件后仍可能暴露真实问题。没有发现需要改变产品协议的确定性阻碍；也不能据此保证 31 项全部会通过。若安全失败，应保留日志并 STOP，不继续扩大修复。

**Final Migration Local：PASS；31 Test Collection：PASS；Low-trust API Compatibility：NOT_VERIFIED（本地合同控制 PASS，真实恢复待验）；Real PG/MCP：NOT_RUN；Safety Regression：NONE_OBSERVED（本地定向范围）；GitHub Push：AWAITING_APPROVAL；Full CI：NOT_VERIFIED。**

接续步骤见 [Handoff](p7-ci-final-migration-handoff.md)。本轮完成本地提交后停止，不自动执行完整 CI 或后续 P7 阶段。
