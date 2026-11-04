# Final 50：十题可信范围确认复验

日期：2026-11-04。范围仅为此前对账中标记“共享确认缺陷，待逐题复验”的十题。此次为非付费工程复验，使用真实隔离 PostgreSQL 17/pgvector、MCP、BGE 和 Fake 决策 Worker；不是新的 DeepSeek 质量成绩。

## 实际结果

| Case ID 后缀 | Gold 业务终态 | 实际业务终态 | 严格结果 | 剩余问题 |
|---|---|---|---|---|
| 031 | partial | partial | PASS | 缺失的 fact_2 仍未被升级为已验证 |
| 032 | partial | partial | PASS | 缺失的 fact_2 仍未被升级为已验证 |
| 033 | unavailable | unavailable | FAIL | 报告多引用一份不在 Gold 相关文档集合中的授权文档 |
| 035 | partial | partial | FAIL | 同上 |
| 051 | partial | 未执行 | BLOCKED | ReportScope 与 RagScope 的 Dataset 范围不同 |
| 052 | partial | 未执行 | BLOCKED | 同上 |
| 053 | partial | partial | FAIL | 报告多引用一份不在 Gold 相关文档集合中的授权文档 |
| 054 | partial | partial | PASS | 指标验证成立，因果结论仍受限制 |
| 068 | completed | completed | FAIL | 报告多引用一份不在 Gold 相关文档集合中的授权文档 |
| 069 | completed | completed | FAIL | 同上 |

完整前缀均为 `p7-holdout-v3-`。合计 **3 PASS / 5 FAIL / 2 BLOCKED**，没有把终态符合 Gold 等同于严格通过。8 个实际执行案例的业务终态均符合原 Gold；5 个失败的唯一 False 评分维度为 `citations`。本轮采集评分没有报告授权违规或错误完成；该结论仅适用于这些 Fake 决策控制。

## 确认与执行方式

原问题、指标请求、文档子问、Required Facts、引用定位和 Gold 均沿用原件。复验脚本逐题检查 Dataset 源 Hash、Semantic/Metric definition Hash、Corpus/IndexVersion、Source/Chunk 和原文引述，随后调用现有宿主接口 `confirm_finite_scope`。没有直接构造或注入 Attestation，没有因缺证明而补写事实。

8 题通过可信范围确认并进入原 `run_durable`、P3、文档验证、Report 和 Collector 链。051、052 被原确认接口拒绝，模型调用为 0。Fake Worker 只提供执行决策，业务数字和文档来自真实基础设施。

隔离实例为 `datapilot-p7-g2-60-postgres-1`，数据库 `datapilot_p7`，宿主端口 `55450`。此次通过原 Ingestion 路径追加 6 个原冻结 Corpus 身份，源文件字节、Manifest 和 IndexVersion 与原 pins 一致；未清库，未访问历史业务数据库。

## 两类剩余缺口

五题的引用问题：033、035、053、068、069 的报告包含额外的授权文档，超出冻结 Gold 的 `retrieval.relevant_document_ids`。授权正确不等于相关性正确，因此保留严格失败。Fake 决策会提交检索 artifact；此次结果不足以判断真实 DeepSeek 是否也会选择这些多余引用，也不足以据此修改 Gold 或降低引用要求。

两题的合同问题：051、052 的 ReportScope 含两个 Dataset，而 RagScope 只含一个。`confirm_finite_scope` 抛出 `ValueError: A reviewed finite document contract needs its exact authorized scope`。本轮保留原范围，没有通过扩充 RagScope、清空指标关联或改 Gold 绕过；后续应检查指标与文档关联的合法合同构造。

下一步应分别处理引用选择和这两题的范围/关联前置条件，再定向验证。无需重跑已通过的三题，也不需要重启历史 Campaign。

## 评分与证据身份

旧评分入口按旧合同重建 ReportScope，且未将确认后的 RAG/Report scope 传给 retrieval goal。本次仅在复验脚本内适配为实际绑定合同，并先核对 Collector Manifest 的精确 scope Hash；原评分文件、Gold、断言及阈值没有修改。

8 份新采集均验证 HMAC 和 payload Hash；原输入、Gold 和 pins 的来源 SHA256 在执行后复核不变。机器记录列出逐题 Run ID、False 维度、额外文档 ID、采集 SHA 和证据路径：

- [逐题机器结果](p7-final50-scope-recheck.json)
- 本地执行及证据目录：`artifacts/p7/final50-scope-recheck-20261104/`
- 新采集核验：`verification.json`
- 执行日志：`recheck-execution.log`
- 原问题/Gold 来源 Hash：`frozen-inputs.json`（private）
- Corpus 追加物化记录：`materialization.json`
- 每题：`case-NNN/signed-collection.json`、`score.json`，或 `preflight-blocked.json`
- 静态核验：`static-verification.json`；Ruff 未使用变量检查、format、JSON/证据 Hash 和 `git diff --check` 通过。执行后仅移除复验脚本末尾空行，前后 SHA 留档，未重新执行业务。

复验脚本 `recheck.py` 使用独占文件创建，已有 Run/输出不能覆盖重跑。首轮导入错误在创建 Run 前发生，原 `recheck.log` 保留；成功执行日志另存。

## 执行边界

- Fake 模型调用 24 次；付费调用 **0**；unknown **0**。
- 本轮未修改产品核心、Prompt、Gold、Scorer 或历史 Seal/STOP/结果；新增复验脚本、证据和报告。
- 没有将本次 Fake 结果合并为原 Final 50 的 Live 通过率。
- 先前工作区未提交修改保留；未 Commit/Push，未启动新 Live 或完整 CI。
- 十题逐项工程复验已完成；严格验收仍有 5 个失败和 2 个前置阻塞，真实模型质量复验尚未执行。
