> 公开脱敏副本。历史原件 `docs/research/p7-demo-acceptance.md` 保持不变、仅本地保留。
> 原件 SHA256：`5632b544c3a36dd81208fd43af7bf22ee74dc5f53ec851eee4cf9bea832644e4`。仅替换本机路径和不可公开工件链接，历史结论/分数不变。

# P7 最小 Demo 验收

2026-10-31，`p7-engineering-candidate-v1`。**Engineering Demo Candidate: ACCEPTED**；**Independent Business Quality: PENDING**；**DeepSeek Live Gate: PENDING**。

本结论只覆盖五个新合成 Run 的七项工程控制，不是七条独立经营质量任务，也不是自然语言成功率或 DeepSeek 自主推理验收。源码及恢复边界见 [工程冻结](p7-engineering-freeze.md)，未完成项见 [Backlog](p7-post-freeze-backlog.md)。机器结果：demo-acceptance.json（local-only：`artifacts/p7/engineering-demo-v1/demo-acceptance.json`；原件不上传）。

## 真实环境与可复核输入

使用现有隔离 PG17/pgvector 服务中的**新数据库** `datapilot_test_engineering_demo_v1_20261031`；迁移 `0008`，原 runtime-init/隔离角色；无 Seed、无历史库覆盖。API `127.0.0.1:8029`，UI `127.0.0.1:8529`。源文件经真实 HTTP 上传/确认/入库及文档摄取；Worker 使用真实 MCP。

Dataset `05b70614-7582-54fe-bafc-e73b4262e6a2` v1，Semantic/Metric v1，指标 `paid_invoice_revenue`，单位 CNY，整数分存储。时间窗口 `[2026-06-01,2026-07-01)`。两条 paid/CNY 账单 `100025 + 43200` 分，独立 CSV/Decimal 与受限 MCP SQL 均得到 **1432.25 CNY**；另外三条分别为 unpaid、7月和 USD，均不进入该指标。不是 MRR、汇率换算或模型心算。

| 固定资产 | SHA256 / 身份 |
|---|---|
| CSV 原件 | `0211d016d75328b89fcc92776ef234fd9897b14928a4276bb15d4b965ec1b3e1` |
| Semantic 定义 | `86b2f2882cddf2de59519603e6bcbedea1b14c1b51b58c8a4af6f3957009f418` |
| Metric 定义 | `4a9462fcdec6d3103dbba0989c74c5f25fce3b37784b809b14bde9ed0a2d3a79` |
| `billing-guide.md` 原件/Source SHA | `7071a8c5ab817da22c5fa74bad8e22912293f1f5963843358367b737821b2ebb` |
| Corpus | `77d54581-7957-4bd0-8a70-567f0866280c` |
| Source | `5414e20970aa82719d6059bdcdef6fdf74c0b87e0214f68a1e56ee3363e78b62` |
| Document | `dad7687155821191c62ceb63b5cd6c705d5b18ac96170ab6c3d1e031158952d3` |
| IndexVersion | `4e728df8bf22d81d7e8b08723b7ac72fac6107bb25ef3aab9e3dd54861366cbb` |
| Chunk，行1–1 | `5de7049818c84bb7e3bcf9110dd95bf8e1062a54974ec785837f6249f6fc13b5` |

模型为已有 BGE 512 固定模型/版本；`embedding_fixture=false`，完整模型与策略绑定由原 Manifest 持久保存，默认未切换 Qwen。原件、计划、范围及具体版本见 [公开计划](../../../../tests/fixtures/demo/engineering-v1/plan.json)、binding（local-only：`artifacts/p7/engineering-demo-v1/binding.json`；原件不上传）、Decimal Gold（local-only：`artifacts/p7/engineering-demo-v1/decimal-gold.json`；原件不上传）、MCP SQL 对照（local-only：`artifacts/p7/engineering-demo-v1/gold-check.json`；原件不上传）。

## 五个实际 Run

| 场景 | Run ID | 真实终态 | 验收依据 |
|---|---|---|---|
| SQL-only | `a14f5091-0908-48f7-920b-8fa51f0fbd03` | completed | 1432.25 CNY；P3 六层 verified |
| RAG-only | `cb6f5a65-48a4-4c8e-a67f-af3ada81d274` | completed；随后合同撤回 | 原 Goal 确认、独立执行审批、真实文档/引用；撤回后不能发布 |
| SQL+RAG | `37768ae4-04e7-430a-a48e-f2ef2261c8aa` | completed | 同页显示精确 CNY 数值及授权 Chunk 引用；不推导因果 |
| 证据不足 | `e5aa8869-8528-48b9-8a9c-374b1393c4ff` | unavailable | 文档没有下一年度退款比例，不编造该事实 |
| 合成未知调用 | `484e2995-2cf4-487c-9d6b-74654e52975f` | blocked / RECOVERY_UNCERTAIN | 一次 Fake attempt，禁止自动恢复/重发，保守计账 |

证据不足的缺失项为 `matching_document_or_metric_evidence_missing`、`required_document_source_missing`、`document_fact_unverified:future_refund`，无发布引用。实际证明的是 **unavailable** 分支；没有另建 partial 正例，不把该场景描述成“相关背景命中后仍保留 partial”。

SQL Evidence `94455a25-d4e2-4039-b2eb-eeeda30120dd`，Verification `e6c9161a-c530-4edc-b4b5-c22ef37e8602`。组合 Evidence `cc959e8d-ef49-445c-9e78-0fe795013d77`，Verification `1157e7ba-018b-4894-bdcc-d9498bb73806`。通过原 scoped MCP 重新读取 Evidence/Verification，safety、shape、semantics、recomputation、references、coverage 六层全 passed；Hash 与发布报告一致，详见 p3-audit.json（local-only：`artifacts/p7/engineering-demo-v1/p3-audit.json`；原件不上传）。

## 确认、审批、浏览器与恢复

1. RAG/组合/证据不足使用原 v4 Goal 和服务器合同，固定原问题、Dataset/版本、Source/IndexVersion、事实及限制。RAG 在真实浏览器展开合同后，分别勾选三项确认，再创建 Run；初始 `awaiting_review`、模型调用 0，随后单独点击原执行审批。其他场景由合成工程测试角色经相同 FastAPI/Journal 接口确认和审批。
2. SQL-only 复用已确认 Semantic/Metric 与时间窗口；仍独立审批，没有伪造 RAG 合同。自动化工程确认不是独立人工质量审核，不写入虚构审核人/签名。
3. 浏览器实际显示 RAG 授权原文、行号、Chunk，重启后又实际显示组合报告的 **1432.2500000000000000 CNY** 与文档引用。候选消息由 HTTP 预先提交，浏览器实际操作的是合同确认、执行审批、报告查看和撤回；不声称完整原问由浏览器键入。
4. 真正终止并重启本轮 API/UI 自有进程，未重启 PG。Python 3.11 前采集、独立 Python 3.13 后采集，验证 HMAC 后比较五个 Run 的 message、payload、view、Manifest、Journal 调用、Ledger、Artifact ID 和 Report，全相同。每个 Artifact 的内容 Hash 也验证，报告读取走原 Inspector/P3/RAG 校验，没有重新执行 Worker。见 restart-integrity.json（local-only：`artifacts/p7/engineering-demo-v1/restart-integrity.json`；原件不上传）。这不是“PG 故障恢复”测试。
5. 重启后通过浏览器撤回 RAG 合同。服务端先变 rejected，页面点击“刷新真实任务进度”后隐藏报告；HTTP `403 GOAL_REVOKED`。原 Inspector 诊断只读仍可验证保留的原报告/工件，使用既有 `report_view` 比较公共投影一致，预算与 SQL P3 引用不变。见 withdrawal-integrity.json（local-only：`artifacts/p7/engineering-demo-v1/withdrawal-integrity.json`；原件不上传）。本轮验证撤回路径，合同修改/旧版本取代的既有 PG 用例沿用前轮记录。
6. unknown 模型调用为本地故障替身，不访问 Provider。一次 Fake attempt 后调用状态 uncertain、usage incomplete；恢复 HTTP `403 WEB_RESUME`，Runtime 原因仍为 `RECOVERY_UNCERTAIN`、要求人工对账。恢复前后调用和 Ledger Hash 相同，实际重启后仍相同；没有清账本或再次发送。见 unknown-guard.json（local-only：`artifacts/p7/engineering-demo-v1/unknown-guard.json`；原件不上传）。

## 真实执行与日志

所有路径以仓库根目录为基准；日志在 `artifacts/p7/engineering-demo-v1/`，私密采集包在其中 `private/`，不公开凭据、密钥或完整运行上下文。

| 已执行 | 真实结果 | 日志/工件 |
|---|---|---|
| 新库原初始化/迁移/runtime-init | 成功，0008；无 Seed | `initialize.log` |
| HTTP 导入、真实 BGE 摄取、独立 MCP Gold | 成功 | `prepare.log`、`gold-check.json` |
| 五 Run 原 Outbox/MCP/Graph/Report | 三 completed、一 unavailable、一 blocked | `sql.log`、`rag-init.log`、`rag-executed.log`、`combined.log`、`insufficient.log`、`unknown.log` |
| P3 scoped MCP 引用审计 | 两组六层 verified，Hash 一致 | `p3-audit.log/json` |
| 重启前/后采集及断言 | 五个签名行一致 | `snapshot-*.log`、`check-*.log`、`checks-*.json`、`restart-integrity-fixed.log/json` |
| 撤回与原 Inspector | 403 GOAL_REVOKED，原报告/用量/P3 不变 | `withdrawal-integrity.log/json` |
| Python 3.11 / 3.13 定向 pytest | 各 **3 passed、0 failed、0 skipped** | `unit311.log/xml`、`unit313.log/xml` |
| Ruff / format | 通过 | `ruff-check.log`、`ruff-format.log` |
| OpenAPI | 原 `/api/v1/openapi.json` HTTP 200 | `openapi-check.json` |
| Diff / 源码 / 历史 | 通过；2222 路径无新差异 | `git-diff-check.log`、`final-source-integrity.log/json` |

双版本最终 pytest 只选择 `tests/test_web_goal_confirmation.py` 中以下三个真实用例，分别以 `.venv/Scripts/python.exe`、`.venv-313/Scripts/python.exe -m pytest -q ... --junitxml=...` 执行：

```text
test_confirmation_dtos_never_accept_host_attestation_or_actor
test_ui_pending_reload_requires_three_explicit_decisions_and_preserves_original
test_legacy_host_hash_stays_stable_until_profile_is_explicit
```

真实 PG/MCP 工程场景用 `.venv/Scripts/python.exe scripts/p7_engineering_demo.py` 的 `prepare`、`run-http --case ...`、`worker` 原入口实际执行。**这些是已完成的一次性执行记录，不是让下一轮再次运行的清单**。未重复全量 pytest、前轮各81项定向测试或8/3项PG测试；产品源码 Hash 相同，前轮 JUnit 与失败均在 [Phase 2C.7 报告](../../../research/p7-goal-confirmation-quality-validation.md) 保留。

只读重启比较脚本初次因模块搜索路径缺少 `scripts/` 导入失败，原 `restart-integrity.log` 保留；仅修正非产品诊断脚本路径后，`restart-integrity-fixed.log` 成功。交付脚本首次在创建结果 Seal 之前检查指向该 Seal 的链接而停止，`finalize-delivery.log` 保留；后续仅续做静态检查和封存，验证已有机器结果一致而不覆盖。没有因此重跑业务 Run，也没有覆盖原日志。浏览器截图仅有本会话原生采集，没有独立导出图片工件；报告不虚构截图路径。

已确认的 Fake 模型调用10次、Mock reported Token 150；另一次合成 unknown 调用保守计账3375、reported 0、usage incomplete。总模型预算调用11次、计账3525，**均不是 Provider 实际 Token**。真实 Provider 调用/Token/费用为0；未做付费账单、性能或缓存收益评测。

## 重现与保留边界

这是当前已锁定本地环境的可核对候选，不声称已完成干净机器一键安装。需要原锁定 Python 环境、完整 BGE 缓存、PG17/pgvector 与用途隔离角色，以及本轮私密宿主配置。初始化复用了现有隔离测试身份配置；跨机器凭据配置与可移植打包仍是发布待办，不导出本机私密配置。

当前专用 API/UI 已停止，数据库与所有记录保留。如只需本机查看保留的 SQL/组合报告，在端口空闲、身份/时效仍有效且另获查看安排后，可使用薄启动器的新唯一标签启动只读浏览器入口：

```powershell
Set-Location -LiteralPath '<LOCAL_PATH>'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe artifacts/p7/engineering-demo-v1/start.py review-next
```

这是未来命令，本轮没有执行；`review-next` 日志不得已存在。启动器仍 `dispatch=False`，仅查看，不调用 `prepare/run-http/worker`，不恢复 unknown，不更换身份或放宽时效。组合对话为 `0748ab9f-f0d9-4f03-a09d-942296f46334`；RAG 对话 `5a2ff0c2-3620-43fb-adab-d95308f6c682` 已撤回，不能再次公开报告。原宿主 TTL 为24小时，过期必须失败关闭，不能延长旧确认冒充有效；新演示需另建有界身份并另行安排，不覆写本次结果。

## 未运行与验收限制

未新测 partial 正例、合同修改浏览器路径、真实 Provider unknown、PG 全实例重启、Linux/Docker、远端 CI 或 Qwen；本次没有新增性能测量。既有安全用例和原失败记录保持，见 [Backlog](p7-post-freeze-backlog.md)。

独立人工语义审查 **NOT_VERIFIED**，正式40观测 A/B 仍0/40。Phase 2C.4 安全 STOP 未解除，原质量/Live Gate 不因本 Demo 被判通过。本轮没有 False Completion、越权发布、P3 错误发布、身份漂移或 unknown 重发的观测；这个有界结论不构成全表达空间安全证明。
