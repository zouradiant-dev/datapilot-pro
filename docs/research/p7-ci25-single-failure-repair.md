# CI #25：单项合同构造修复与推送前验收

2026-11-01。**本地单项修复 PASS；真实 PG/MCP NOT_RUN；运行期真实设施安全验收 NOT_VERIFIED；推送等待授权；不是完整 CI。**

## 远端事实与历史证据

- 分支 `p7-engineering-candidate-v1`；本轮开工 HEAD 与重新读取的远端均为 `c7606be7d8838433abc1fb3a9aa643516e07fdf6`。
- [Actions #25](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41280918261)，工作流 `DataPilot CI22 Batch 3 - NOT FULL CI`，attempt 1，实际结论 **failure**。UTC 2026-11-01 06:27:38–06:33:30。
- [Python 3.11 Job](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41280918261/job/124772494987) 与 [Python 3.13 Job](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41280918261/job/124772494751) 各 **1332 非集成 passed；14 PG passed / 1 failed / 0 skipped**。不是完整集成矩阵。
- 两版初始化、依赖、Ruff、格式和固定 BGE 均成功；原日志的 PostgreSQL 为 `170011`，pgvector `0.8.6`，迁移 `0008`。
- 两份 ZIP 的实际字节与本轮 GitHub API digest 一致，内部 JUnit、Commit、Scope 和源码清单与缓存原件一致。两个完整 Job 日志均已读取；未修改原失败记录。历史 631 项 Linux 源码清单与原提交 Git blob 的核对记录保留，不用 Windows CRLF 工作副本冒充同一字节序列。

| Artifact | ID | ZIP SHA256 |
|---|---|---|
| Python 3.11 | 13073541133 | `946b8a398166baafea07517294e989594624c2331bd4e334162ee9eec5ce41a7` |
| Python 3.13 | 13073208284 | `f6b3795a555445a56c28d7920bcdb49a8b4055311b819972a849528105afaaf1` |

原件仅保存在本地忽略目录 `artifacts/p7/ci22-batch3-actions-v1/`，包括 ZIP、`job-py311.log`、`job-py313.log`、两版 `integration.xml`、`unit.xml` 和 `verified-results.json`。此前没有完成的 #25 交付 Seal/Handoff，不补造为历史记录。

## 唯一失败与两个安全边界

精确身份：

```text
tests/test_citation_policy_postgres.py::test_real_supplement_only_and_forged_quotes_cannot_fill_required_sources
```

原测试先确认有效有限合同，验证真实报告 completed、Supplement 不能替代 Required、伪造 quotation 不能发布。最后却先把 **可信合同**的 Required Source IndexVersion 改成全零，再在 `pytest.raises(AgentFailure)` 之外重新确认。Required Fact 仍引用原 IndexVersion，因此 `confirm_finite_scope` 的 `ReportScope.model_validate_json` 在构造层抛出 `pydantic.ValidationError: Required facts cannot be relabelled as supplementary`，未进入最后的 `service.build`。

这是该迁移测试的构造层与运行层混用；这次 ValidationError 不构成假引用被发布的证据，也不能替代运行期安全覆盖。

修复只改变测试构造：

1. **非法合同负例**：复制原合法合同，仅替换 Required Source IndexVersion、保留 Required Fact 原身份，明确要求正式确认接口抛出上述 `ValidationError`。
2. **合法原件控制**：保留第一次真实 Host 确认的深拷贝，恢复该原合同，再次以真实检索原件建立 completed 控制。
3. **运行期篡改负例**：只修改不可信检索结果中 `quota.md` 的 Citation IndexVersion，替换值来自同一公开夹具已经存在的另一索引（`cp06`）。未修改合同、RagScope、Manifest、原确认或授权；未重新摄取 Corpus。
4. 候选结果经原 `ArtifactStore.put` 生成正常 SHA/ref，然后调用原 `service.build`。必须抛出 **`AgentFailure` / `DOCUMENT_NOT_AUTHORIZED`**，并证明合同与授权序列化不变。它不能以 `REPORT_SCOPE_INVALID`、Artifact 哈希不匹配或重新确认失败来代替运行期拒绝。

运行期目标为 [MCPRetrievalTools.validate_result](../../src/datapilot/rag/mcp.py) → [verify_result](../../src/datapilot/rag/storage.py) 的原 Source/IndexVersion 绑定检查。[ReportService](../../src/datapilot/reporting/service.py) 与 [ReportScope](../../src/datapilot/reporting/contracts.py) 均未修改。

## 最小修改与断言保留

| 文件 | 实际修改与必要性 |
|---|---|
| [tests/test_citation_policy_postgres.py](../../tests/test_citation_policy_postgres.py) | 只修复上述函数并新增 ValidationError 导入；拆开两层负例，增加合法原件、精确拒绝码和权限不变检查。 |
| [tests/test_citation_policy.py](../../tests/test_citation_policy.py) | 新增两个公开合成单元测试，分别验证确认拒绝和结果验证层确实被调用；复用原测试夹具，无新框架。 |
| [.github/workflows/test.yml](../../.github/workflows/test.yml) | 临时收窄到同一个精确 PG Node，改名 `DataPilot CI25 Single Failure - NOT FULL CI`。原双版本、非集成回归、PG17/pgvector、初始化、BGE、Ruff、格式、coverage/JUnit/always 上传均保留。 |

修复前三个文件合计 Diff 为 **88 additions / 22 deletions**，其中工作流减少的是本轮禁止执行的另外 14 个临时 PG 选择器，不删除测试或改变其断言。原失败函数的 **7 条 assert 全部保留**，原 `pytest.raises(AgentFailure)` 仍存在；其他 PG 函数/辅助逻辑与既有单元测试 AST 不变。没有新增共享确认器、持久字段或产品抽象；不存在需要保留的重复测试框架。

没有 `src/`、`scripts/`、`evaluation/`、迁移、依赖、锁、夹具或 AGENTS 变更。旧 Gold/Seal/STOP 在 Git Diff 中无变化；62 份既有诊断/交付/结果文件 SHA 与原记录一致。没有访问或改变历史数据库、Docker 磁盘、Run、Journal 或 Ledger；这不是重新验证历史数据库全量健康。

## 本轮实际验证

原失败证据为 #25 的双版真实 PG JUnit，各 1 failed；不将其记为本轮重新执行。新增两个单元反例在 PG 测试修复前先执行，Python 3.11 **2 passed**，证明原产品分别存在两层守卫。

最终源码冻结后，运行：

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m 'not integration and not live' tests/test_citation_policy.py tests/test_goal_scope_integrity.py tests/test_ci_workflow.py --junitxml=artifacts/p7/ci25-single-failure-repair-v1/final-py311.xml
.venv-313\Scripts\python.exe -m pytest -q -p no:cacheprovider -m 'not integration and not live' tests/test_citation_policy.py tests/test_goal_scope_integrity.py tests/test_ci_workflow.py --junitxml=artifacts/p7/ci25-single-failure-repair-v1/final-py313.xml
```

| 验证 | Python 3.11 | Python 3.13 |
|---|---|---|
| 定向单元/合同 | **64 passed / 0 failed / 0 errors / 0 skipped** | **64 passed / 0 failed / 0 errors / 0 skipped** |
| 同一精确 PG Node 收集 | **1 collected** | **1 collected** |
| 本轮真实 PG 执行 | **NOT_RUN** | **NOT_RUN** |

本地以 Fake/明确的 Source double 验证两种拒绝；运行期单元测试证明 `validate_result` 被调用恰好一次，错误码准确，合法原件仍 completed。**它不能证明真实 PG/MCP 的运行期篡改验收已经通过。**

本轮未启动本地 PG、未探查/恢复旧 Docker VHDX、未调用任何付费 API；也未运行另外 14 项 PG 或完整 pytest。本地 driver 清除继承的 `DATAPILOT_*`，显式禁用 DB/Live。

Ruff check、format check 和 `git diff --check` 通过；YAML、JSON 和本次 Markdown 本地链接检查见机器记录与静态日志。两版 JUnit、采集身份、测试时的源码 SHA 与最终源码一致，没有用早期测试冒充后续变更的验证。

本轮日志：`artifacts/p7/ci25-single-failure-repair-v1/`，包括 `design-py311.*`、`final-py311.*`、`final-py313.*`、`collect-py311.*`、`collect-py313.*`、`audit.json`、`static.json`、`delivery-validation.json`。源码 SHA、剩余精确身份见[机器记录](p7-ci25-single-failure-repair.json)。这些忽略工件不会随提交上传。

## Git 与下一次定向验收

本报告随独立本地 `fix(test): separate CI25 contract and runtime citation guards` 提交；完整 SHA 由最终答复及忽略目录 `commit-verification.json` 记录，避免向提交内容写入其自身 SHA。开工六份未跟踪 Docker/CI 旧报告原样保留，全部排除提交。提交白名单仅上述三个文件与本报告、机器记录、[接续文档](p7-ci25-single-failure-handoff.md)。

**尚未推送，也未触发远端 CI。** 授权推送前须重新核对分支、远端基线与仅一个待推送提交，不 Force Push、不合并 main。新 Run 仅执行这一个 PG Node 的 Python 3.11/3.13，保留全非集成、静态与工件上传；失败只下载日志归因，不热修/重跑。新真实 JUnit 两版均通过以后，才可把 Batch 3 原 15 项认定为“原 #25 的 14 项 + 新定向验收的 1 项”全部验证；不伪称同一新 Run 执行过 15 项。

## 剩余 31 项集中迁移准备（只读方案）

原 60 项中，#23/#24 累计 14 项、#25 再增加 14 项，当前 **28 verified + 1 repaired/pending PG + 31 outside scope = 60**。当前未充分验收为 32 项。若本次双版 PG 通过，才变为 29 verified / 31 remaining。

已对剩余测试构造作只读审查：**A2 29 项、A5 2 项**。机器记录保留完整原 pytest Node ID，包括 Unicode 参数转义；以下编号沿用原 #22 60 项分类，不创建新的用例分母。

| 共享前置条件 / 原编号 | 数量 | 后续最小迁移与必须保留的断言 |
|---|---:|---|
| Cross-source：9–14、16 | 7 | 在最终 Dataset/Metric/Required facts/causal 配置固定后，为确实有限的公开合成合同调用原 Host 确认；保留五指标独立 Gold、P3 refs、checkpoint、注入和禁用工具检查。 |
| Document Fact：24–27 | 4 | 对 absence/partial/summary/causal 的有限事实范围显式确认；确认不是因果证明，原事实不足及状态断言不改。 |
| Host Goal：29–32 | 4 | 在 `configured` 完成所有策略和源绑定后，限定正向/partial/causal 用例确认；不在 session fixture 全局自动批准。保留原问所有权和预算恢复。 |
| Host Goal Safety：34–39 | 6 | 只确认审阅过的有限目标；否定/required-gap/因果仍按原证据检查。保留旧版本不兼容与新版本重复恢复，不偷换身份。 |
| Original Query：42–47 | 6 | 在最终 `new_config` 上确认；保留首问与第二次搜索、四 cut-point、模型/工具调用次数和不重复结算。 |
| Partial Evidence：52 | 1 | 只在该跨节点用例明确确认有限合同；共享 `config_for` 不统一自动确认，partial refs/hash/恢复仍核验。 |
| Phase 1/2：54 | 1 | 先固定可信 `causal_requested=False` 再确认，保留真实 P3/文档、Inspector 与原 Evidence 不变检查。 |
| 旧低信任入口：58–59 | 2 | `run_question` 不增加新参数或权限；另在现有 Host/Coordinator 路径提供合法有限合同正向控制，保留旧入口拒绝及语义相关性、跨进程收据、预算和无重复调用。相关测试探针如需接线，只改测试设施。 |

预计影响为这八个测试模块、必要的现有测试探针与工作流选择器；不新建通用审批框架。优先复用原 `confirm_finite_scope` 和已迁移的测试构造。任何 final fields 改变都应先完成再确认；不直接注入 Attestation，不把未知集合自动批准为有限事实。

后续集中迁移必须另获授权：先冻结 31 个身份、逐项保留 AST 断言与原期望，然后定向双版真实 PG；真实安全失败立即停止。只有 60 项旧失败全部有验收后，才另行恢复完整 workflow 的原全量集成命令，保留全非集成与全部 PG、原 Qwen/CUDA/付费 Live 的 opt-in 条件，下载完整 JUnit 核对分母及 Skip 原因。当前不执行上述步骤，不承诺补确认后没有其他失败。

## 当前结论与风险

- **Single Failure Repair：PASS（本地最小修复与合同验证）**。
- **Runtime Tamper Safety：NOT_VERIFIED（真实 PG/MCP 待验；单元层 PASS）**。
- **Real PG/MCP：NOT_RUN（本轮）**。
- **GitHub Push：AWAITING_APPROVAL**。
- **Full CI：NOT_VERIFIED**。

主要剩余风险是新 PG 负例尚未真实执行，以及后续 31 项在补足可信前置条件后可能暴露新的下游错误。不能用 #25 旧的 14 passed 或本轮 64 单元通过替代这两项。完成本地交付后停止。
