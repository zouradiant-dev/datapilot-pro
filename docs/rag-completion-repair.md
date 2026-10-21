# P6A 定向修复：RAG 完成协议与恢复

日期：2026-10-21；代码基线 `1d9e96e`。仅修复 P6A，不进入 P6B/UI/评测平台，不自动提交或推送。原负结果保留于 [P6A 历史交付](p6a-delivery.md)。决策见 [ADR-011](adr/0011-rag-completion-gate.md)。

下文原有本地测试、DeepSeek Smoke 和失败历史为**推送前交付快照**，指标保持原样。修复提交随后已按用户指令推送；当前远端 CI 状态以下述独立核验为准，不再以当时“尚未推送、CI 未运行”的记录表示当前状态。

## Post-push CI Verification

实际核验时间：**2026-10-22 00:03:55 +08:00（Asia/Shanghai）**。通过现有 GitHub Connector 只读调用 GitHub REST API，重新读取指定 workflow run、最新 attempt 的 jobs/steps 及远端 main；不是仅复述此前观察。

| 核验项 | GitHub 实际结果 |
|---|---|
| 仓库 | `zouradiant-dev/datapilot-pro` |
| 修复提交 SHA | `1cb329994b1caf52be0ec33edc2fdf3c23795ba5` |
| 本地 / 远端 | 本地 main、HEAD 与远端 main 均指向该修复提交 |
| 工作流 | DataPilot checks；`.github/workflows/test.yml`；push 触发 |
| Run / attempt | [39628335549](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/39628335549) / 1 |
| 整体 CI | completed / **success** |
| Python 3.11 | [checks (3.11)](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/39628335549/job/119319489022)：completed / **success** |
| Python 3.13 | [checks (3.13)](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/39628335549/job/119319489474)：completed / **success** |

两个 job 的 pytest、ruff check、ruff format --check 步骤均为 success。依据为 [Run API](https://api.github.com/repos/zouradiant-dev/datapilot-pro/actions/runs/39628335549)、[Jobs API](https://api.github.com/repos/zouradiant-dev/datapilot-pro/actions/runs/39628335549/jobs) 与 [main API](https://api.github.com/repos/zouradiant-dev/datapilot-pro/branches/main)；对应结构化结果见 [post_push_ci](research/rag-completion-validation.json)。

CI 使用 Fake/脚本化决策、HTTP Mock 及真实 PostgreSQL 17/pgvector 服务；工作流未启用 live API opt-in。这些结果不构成真实 DeepSeek API 测试，不能推导稳定成功率。原单次真实 DeepSeek Smoke 继续作为单独的历史实验，不改 Token、耗时或失败指标，也不把本地测试计数冒充本次远端统计。

本次只同步两份交付记录，验证 JSON/Markdown 引用与 diff；不运行付费实验或完整本地回归，不改业务代码，不自动 commit/push，不进入 P6B。初始工作区另有 `docs/codex-prompts-v2.4.md` 的用户修改，保持原样。上述 CI 通过适用于指定提交/Run，不表示本次未提交的文档修改已运行 CI。

## 原因与最小改动

此前真实 DeepSeek 已检索/读取，却用普通文本结束，触发 MODEL_OUTPUT_INVALID；另一次在两次检索后继续搜索，触发 RAG_ATTEMPTS_EXHAUSTED。原 Loop 无可纠正的完成出口；工具展示集合与 P5A 精确授权校验不允许简单删掉搜索 Schema。

保留外层 Planner/Scheduler/Worker/Verifier/Replan、原 Worker 子图和 Gateway。模型仍决定关键词、是否补查、何时读上下文及提交；没有固定 search→read→finalize 流水线。

| 原机制 | 当前机制 |
|---|---|
| search/read 后输出 FinalDecision JSON | search/read 后原生调用宿主 `submit_rag_result` |
| 普通文本直接格式失败 | Stop Hook 提示一次完成协议纠正 |
| 两次后仍展示搜索 | 宿主关闭搜索，保留合法 read/submit 出口 |
| 非空但不足缺少终态 | unavailable（实际为空）/insufficient（非空不足）/complete（满足检索契约） |

## 结束工具与安全阶段

`RagSubmission` 使用严格 Pydantic 契约：`artifact_ids: list[Digest]`（1–8 个、宿主检查唯一）和 `outcome: Literal["complete", "unavailable", "insufficient"]`。必须引用当前任务实际取得的 Artifact SHA，而非 chunk/document ID。控制工具只在显式授权真实 RAG adapter 下开放；SQL 和旧 fixture 契约保持原状。MCP 仍只有只读检索工具。

提交独占一轮；混合或多个提交整批不执行，逐项返回关联 ToolMessage。伪造/重复/跨任务引用、安全越权、取消、预算耗尽与 unknown-outcome 不走纠正。成功提交直接 END，无额外模型“确认完成”调用。

普通文本、可修复提交参数错误、超额旧搜索请求等**共享一次纠正**；再次出现纠正条件即 RAG_COMPLETION_REPAIR_EXHAUSTED。所有模型推理仍计入父子 Token/调用/Worker turns，SDK 不自动重试。

初始 search/read/submit → 两次真实搜索后 read/submit → 已接收后仅允许相同控制提交幂等重放。隐藏 Schema 不是权限：ContextManager 同时核对初始 Authority 和宿主当前阶段精确集合，Registry 运行时拒绝已关闭能力。恢复可读旧 Schema 对应的已提交缓存，但不能用它发出新的旧阶段模型请求。

## 检索完成不等于业务结论成立

仅允许确定性逐字定位会排除同义问答，已撤销此限制。当前检索验收包括：模型显式提交、授权/任务/版本、实际原件和跨度/hash、原始目标相关性，以及可支持的数量/范围要求。非空、有效 SHA 或模型自报完成都不足以通过。

- 原文定位按宿主原始目标中的引用词核对。
- 语义检索使用固定 BGE，将完整宿主原始目标与已返回片段做独立 cosine 相关性检查；模型自己的 query 不能替换目标。目标 SHA/score 由隔离 RAG MCP 计算，不接受模型参数传入。
- `bge-host-goal-cosine-v1` 的基准阈值为 0.55，且不低于 scope.min_score；策略/阈值随目标契约进入持久身份。该阈值是小样本工程启发式，不是语义证明或已校准的成功率。还须满足前述来源/权限/任务约束。
- “至少二/两/2至五/5份/篇/个文档”按不同 source_id 计数，重复 chunk 不充数；更大数量、针对文档的日期/最新/全量要求当前保守不足。整体业务分析的时间窗口不自动变成背景文档发布日期过滤；引用词中的“最新”也不冒充日期约束。这里是封闭的启发式需求提取，不是任意自然语言约束解释器。
- 原始目标超过固定模型输入上限时不截断补证；无可靠相关性元数据就不能语义 complete。局部 CPU 目标 embedding 单独记 usage，不增加 Evaluator LLM 或 MCP 检索次数。隔离 MCP 会话复用既有锁串行化该本地检索路径，防止并发 Worker 在目标向量初始化期间读到半成品；两个并发查询只计算一次目标向量。这限制单会话吞吐，未声称高并发优化。
- 完成收据记录 relevant_chunk_ids；对用户只展示符合条件的片段，完整候选保留在私密 Artifact。收据 `business_conclusions_verified` 恒为 false。

| 状态 | RAG 子任务 | 最终业务结论 |
|---|---|---|
| semantic_retrieval / literal_locator | 相关证据符合检索要求，succeeded | 未验证；无需在 RAG 独立证明因果 |
| empty / NO_RELEVANT_DOCUMENTS | 实际空检索，unavailable | 无法据此作答 |
| insufficient / EVIDENCE_INSUFFICIENT | 有真实文档但不满足检索要求，unavailable | 不得包装为成功 |
| 相关流失资料检索已完成 | RAG Verifier 可 passed | 原外层仍 blocked/P3_VERIFIED_EVIDENCE_REQUIRED |

因果/指标最终验证继续由外层与 P3/后续 P6B 承担。收据是 P4 Artifact 控制证明，不冒称 P3 Evidence ID。现有业务意图防护不是通用语义分类器。

## P5B 恢复修复

实际故障：在 submit 提交后、子图 checkpoint 前退出，新进程可能直接进入 Tools 节点；仅在 Decide 重建证据授权会丢失当前已闭合历史的 grant。修复为真实 RAG Tools 在重放前按该 checkpoint 的已闭合反馈重新对齐 Registry。没有重写 Saver。

结束收据绑定 tool_call_id、Artifact/目标契约、原生模型响应 SHA；原 Journal 校验它确实来自同账户已提交模型响应及对应工具参数。完成工具日志先提交，Registry 才接收完成；恢复重新校验来源/版本/范围与相关片段集合。

一次纠正是纯本地主机控制记录，在原 execution.calls 中原子提交，不建第二个账本；相同触发幂等，不同第二次触发拒绝。已提交搜索/收据复用、不再调用外部服务、不重复结算。未提交结果的 issued/uncertain 仍 RECOVERY_UNCERTAIN，不能假定未执行后重发。旧真实 RAG Run 缺少新协议身份明确 RECOVERY_IDENTITY；普通 SaaS 旧身份不变。

## 代码与验证

| 位置 | 改动 |
|---|---|
| orchestration/rag_completion.py、contracts.py | 单一确定性校验、目标/收据/三态契约 |
| tools.py、loop.py | 完成控制、一次纠正、完整 assistant/tool 配对、阶段收缩 |
| context.py、model.py | 当前阶段精确校验、仅提交允许的畸形参数反馈、旧缓存只读复用 |
| coordinator.py | 复用原 Verifier、来源任务重用验证、渲染相关引用 |
| persistence/journal.py、session.py | 原日志接收/对账、控制记录、恢复身份与直接 Tools 重放 |
| rag/mcp.py、storage.py、contracts.py、runtime/mcp_server.py | 宿主目标绑定与独立相关性元数据；无新 DB 迁移 |
| tests/test_rag_completion*.py、scripts/rag_recovery_probe.py | 单元、真实 SDK HTTP Mock、真实 PG/CPU/MCP 与独立进程故障 |
| scripts/measure_rag_completion.py | 单次有界 live 记录，只公开合成来源元数据 |

历史检索次数测试有一处明确契约更新：终止码允许一次纠正后变为 RAG_COMPLETION_REPAIR_EXHAUSTED；保留“真正执行搜索恰好两次”的强断言，额外请求只拒绝，不扩大检索预算。

最终执行结果如下；机器记录与 JUnit SHA 见 [rag-completion-validation.json](research/rag-completion-validation.json)。真实 PG 已启用，没有用替身数据库替代。

| 实际执行 | 真实结果 |
|---|---|
| Python 3.11.16 全量中间回归 | 501 passed, 1 skipped，522.24s；在最后三项用例及对应加固前启动，不能冒称与最终版完全相同 |
| Python 3.11 最终控制单元/SDK HTTP Mock | 34 passed，2.75s |
| Python 3.11 新真实 PG 控制/语义用例 | 10 passed，148.76s；随后并发目标初始化用例单独 1 passed，4.71s |
| Python 3.13.15 最终本地/协议 | 396 passed，9.04s |
| **Python 3.13.15 最终完整回归** | **504 passed, 1 skipped，542.77s**；含 108 项真实 PG 集成与全部新增故障恢复用例 |
| Ruff check / format / git diff --check | 通过；180 个 Python 文件格式符合规范 |
| 双 Python uv sync --locked --offline / compileall | 通过；依赖和锁文件未更改 |
| health | PG 17.11 / pgvector 0.8.6 / migration 0005 / 原 240 客户保留 |

最终新覆盖 45 项：34 项脚本化/真实 SDK HTTP Mock，11 项真实 PG/本地神经 Embedding/MCP。单独的模型 live pytest 未开 opt-in，因此跳过一项；下述获授权 smoke 单独记录。3.11 中间全量与最后小修的针对性验证如实区分，最终整套代码由 3.13 全量覆盖。**推送前快照：当时远端 CI 未运行，该轮修复尚未提交/推送；此句保留历史事实，当前状态见上方 Post-push CI Verification。**

```powershell
$env:PYTHONUTF8 = '1'
$env:DATAPILOT_RUN_DB_TESTS = '1'
.venv-313\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider --basetemp artifacts/rag-completion/final-313 --junitxml artifacts/rag-completion/final-313.xml
.venv\Scripts\python.exe -m pytest tests/test_rag_completion.py tests/test_rag_completion_transport.py -q
.venv\Scripts\python.exe -m pytest tests/test_rag_completion_postgres.py -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
git -c core.safecrlf=false diff --check
```

开发中新增 PG 测试曾因把 Artifact 导出字典当列表、负面查询实际为空而非非空无关失败；修正测试读取方式及使用已有高相关账单查询后通过，没有降低相关性阈值。实际跨进程 grant 重建缺陷通过上文 Runtime 修复解决；原负测试安全断言保留。

## 唯一获授权的真实 DeepSeek Smoke

完整本地回归通过后，严格执行一个 Run，无自动重跑、无 Replan；限制 8 次模型调用 / 18,000 Token。使用原失败实验的同一自然语言目标“仅检索客户入门培训相关文档片段，保留实际来源引用”与原先授权的三份合成文档索引；没有改成逐字定位问题来制造通过。

```powershell
.venv\Scripts\python.exe scripts/measure_rag_completion.py --scope artifacts/p6a/first-scope.json --output artifacts/rag-completion/deepseek-once.json --live
```

以上是**已执行且仅执行一次**的付费命令，输出路径使用独占创建，重复执行会拒绝；不要把文档示例当作再次授权。

| 指标 | 实测 |
|---|---|
| 模型 / Run | deepseek-flash，462ccd40-d6f1-400a-996e-9bd421c67483 |
| 终态 | succeeded / completion.completed；收据 semantic_retrieval |
| 模型调用 | 5（规划 1、Worker 决策 4），未重跑 |
| input / output / total Token | 7,105 / 460 / **7,565** |
| 供应商 cache-read Token | 3,840；不推导费用节省 |
| 实际工具 | search 2、read_context 1、submit 1；成功提交后直接 END |
| Stop Hook | 0；真实 API 本例未触发，纠正路径仅由脚本化/HTTP Mock/真实 PG 故障测试验证 |
| 总时延 / 模型耗时合计 | 10,073.63 ms / 5,782.00 ms |
| 本地 embedding | 3 次计算（两次 query + 缓存一次宿主目标），112 个本地 tokenizer Token；无 Embedding API |
| 引用 | onboarding.md，字符 [0,136)、行 1–5；原件 SHA、片段 SHA、版本/索引/目标绑定均复核 |
| 相关性 | 模型搜索 score=0.596842；独立宿主目标 score=0.645252；来源和任务验收同时通过 |
| 业务结论 | business_conclusions_verified=false；没有生成/验证经营因果结论 |
| 费用 | null，缺少账单，不编造货币金额 |

5 次调用比历史两个失败 Run 的 4/3 次更多，7,565 Token 也高于历史 5,476/2,716；这些不是固定随机/完全相同提示的 A/B，不能归因净增量或宣称节省。控制 Schema、目标/引用元数据及自主补查增加上下文；本次获得合格交付，但不能从一个样本估计稳定成功率。原 MODEL_OUTPUT_INVALID 与 RAG_ATTEMPTS_EXHAUSTED 负结果继续保留。

结论仅是**这一次 P6A 真实模型、有界合成语义检索 Smoke 通过**，不能扩展为任意业务问题、完整 P6A 质量基准、因果分析或 P6B 报告验收。没有额外 Evaluator 模型；记录脚本后来仅修正汇总为两次搜索的全部 CPU embedding usage，通过读取同 Run 原 Journal 补齐，额外模型/MCP 调用为零。

## 风险和停止点

单次纠正及两次搜索会限制探索，模型仍可能过早提交或错报不足；确定性验收能防明显假引用/无关命中，不能证明任意语义充分性。目标向量增加少量 CPU 计算与 citation Token；控制提示、工具 Schema、纠正会增加输入及延迟，成功提交省去末尾模型确认但未预先承诺净省费。原件、完整历史、Checkpoint 均为私密存储。跨服务 exactly-once 不承诺；未知执行需人工对账。完成后停在 P6A，P6B/P6C/生产多租户另行授权。
