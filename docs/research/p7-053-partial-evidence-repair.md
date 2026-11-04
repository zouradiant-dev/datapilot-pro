# 053 部分证据修复

日期：2026-11-04。**非付费修复与定向验收通过；新 Live 未执行。** 旧 053 Run `125d1d6b-fb5e-5015-b6b1-8e7afb375d4b` 仍严格失败，原十题批次保持 9/10，STOP、采集、Gold 和旧评分不变。

## 根因

原合同未启用已有 `partial-facts-v1`，因此 RAG 返回 `insufficient` 后，Report 不展示已确认的额度用途。原文确实被找到并读取；这不是空召回，也不是供应商故障。

评分还有两项旧假设：发布的 excerpt 必须等于整个 Chunk；Gold 的 `retrieval_expected=complete` 被作为唯一收据结果。前者不适用于宿主确认的短引述，后者没有表达“业务必须部分完成，已验证事实可显示，但检索仍诚实报告不足”的显式合同。

## 修改

- 新增 `evaluation/p7_v3_current/partial_evidence_scope.py`：宿主显式启用原 `partial-facts-v1` 并重新确认完整合同；原问题、指标、两个事实要求及全部 Source/IndexVersion 不变，不给 fact_2 补造证明。
- 新增 `evaluation/p7_v3_current/partial_evidence_scorer.py`：独立版本 **`p7-current-partial-evidence-v3`**，原 `scorer.py` v2 与冻结 v3 评分文件不改。
- 新增 `tests/test_p7_partial_evidence_scoring.py`：15 项公开合成正反例，无私有 Gold、数据库或付费依赖。

生产 Report 已实现所需的部分事实发布，本轮没有修改产品运行核心。

### 原文摘录核验

发布的短引述必须来自当前 RAG 任务实际取得的 artifact；artifact Hash、原完整 Chunk 文本 Hash、Source/版本、跨度、IndexVersion、模型和 chunker pin 仍匹配。短引述必须精确等于宿主已确认的 fact quotation，并存在于原 Chunk。任意 substring、修改后的原文或其他任务 artifact 都不能自行成为可信事实。

### 不足收据与部分业务结果

规则仅适用于显式 `partial-facts-v1` 且目标范围已有可信确认的合同。只有在以下条件同时满足时，`insufficient` 才与部分结果兼容：

- Gold 与实际业务终态都是 partial，Gold 明确记录缺失事实；
- 原收据及调用配对核验通过，RAG 状态仍为 unavailable、收据仍为 insufficient；
- 已知事实及 Gold 所要求的原文和引用确实发布，缺失事实保持未验证并列明原因；
- documents 未被加入 verified goals，数值、授权、协议、预算和恢复检查通过。

`complete` 仍是 Gold 原字段，评分输出同时保留原预期与实际不足收据，明确记录兼容解释。这是版本化的部分证据评分契约，不改 Gold 文件；不把 RAG insufficient 写成 RAG complete，也不接受整体 completed。没有 Case ID 特判。

## 实际验证

Python 3.11／3.13 各 **144 passed / 0 failed / 0 errors / 0 skipped**，含新评分控制、原引用评分、Partial Evidence、Goal 完整性、Citation Policy 和原收据版本测试。Ruff、format 和 `git diff --check` 通过。

真实专用 PG17/pgvector、MCP、BGE 加脚本 Worker 的三个新控制：

| 控制 | 新 Run ID | 实际结果 | 验收 |
|---|---|---|---|
| insufficient 收据 | `86230b2c-6fb7-526c-a756-965fb7a436c3` | 收入 744.33 CNY＋额度用途引述；fact_1=true、fact_2=false；partial；RAG 未完成 | PASS |
| complete 收据 | `1f883f95-d955-5966-86e8-dede51f8831a` | 收入与额度用途可显示；fact_2 仍缺失；partial | PASS |
| 去掉事实证明 | `5a0b3e2c-5b2d-59f7-b1bf-19c780a92af6` | 文档事实未发布；严格评分 False；不升级 completed | PASS（拒绝负例） |

实例为前轮专用 `datapilot-p7-g2-60-postgres-1`，数据库 `datapilot_p7`，宿主端口 55450。三个控制各 3 次 Fake 决策／45 个合成 Token，共 9 次／135 单位；**付费调用 0，unknown 0**。三个新签名采集 HMAC 均通过；原 Gold、旧 Live 与旧评分、STOP 的 Hash 复核未变。

另外只读诊断原 Live 053：即使用新版评分，其旧合同仍是 legacy、报告仍缺文档事实，因此仍失败。没有把原批次改成 10/10。

## 交付与下一步

- [机器结果、Run/P3 ID、JUnit 汇总与 SHA256](p7-053-partial-evidence-repair.json)
- 本地完整证据：`artifacts/p7/053-partial-repair-20261104/`
- 三个控制目录分别保存新配置、签名采集、评分。
- `py311.xml/log`、`py313.xml/log`：双版本测试。
- `historical-diagnostic-only.json`：原 Live 只读诊断，不覆盖原分数。
- `live-config.json`、`live-binding.json`：单题新 Run 的待授权绑定。
- `permit-template.json`：`authorized=false`，没有创建生效的付费 Permit。

初次单独运行新测试时，复用 fixture 的依赖漏导入导致 15 项 fixture 错误，已仅修正测试导入；后续真实双版本结果如上。此错误没有产生业务 Run 或模型调用。

修复已经具备申请一次单题 Live 补验的条件。预留的新 Run ID 为 `dd51cc3f-f7ca-5372-b86c-5c1f6334e130`，计划沿用 deepseek-flash／原端点、1 Run、8 calls／18,000 Token、串行及重试 0。该新 Run 尚未启动，本轮修复授权不挪用已结束十题批次的余量。

**新 Live：NOT_RUN；完整 CI：NOT_RUN；本轮未 Commit/Push，未恢复旧 Run，未改历史 Gold/Seal/STOP。**
