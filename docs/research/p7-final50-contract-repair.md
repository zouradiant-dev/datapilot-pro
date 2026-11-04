# Final 50：051、052 合同范围修复与复评

日期：2026-11-04。两题新建独立 Run，使用真实隔离 PostgreSQL 17/pgvector、MCP、BGE 和 Fake 决策 Worker。新版评分器为 `p7-current-authorized-citations-v2`。**两题严格通过，业务终态均为符合原 Gold 的 partial。**

## 结果

| Case | 新 Run ID | 实际发布 | 保留的不可用项 | 严格评分 |
|---|---|---|---|---|
| `p7-holdout-v3-051` | `3893c23e-3dba-5407-852f-ac7b6a1419d2` | P3 verified 使用量 **205 events**，使用事件计量规程及合法引用 | 收入：`amount_unit_unconfirmed` | PASS |
| `p7-holdout-v3-052` | `68cfa0f7-c59d-522f-9283-9916d069f4e6` | P3 verified 收入 **744.33 CNY**，发票粒度政策及合法引用 | 客户流失：`history_unconfirmed` | PASS |

两题的 `documents` 均为已验证目标，Required Fact 覆盖 1/1；没有用政策文档补猜金额单位或合同历史。051 的引用精确率为 1.0；052 为 0.5，额外的真实授权引用按新版规则单独记录，不否决整题。

## 根因与修改

原题的 ReportScope 已批准主 Dataset 与变体 Dataset，但 RagScope 只含主 Dataset，因此可信范围确认先被拒绝。即使将两个清单对齐，原 Report 仍要求文档 Target Dataset 等于所关联指标的 Dataset；这两题的政策属于主 Dataset，而指标来自单位未确认／历史不完整的变体。

本轮复用现有合同字段和宿主确认接口：

1. RagScope 使用原 ReportScope 已批准的精确 Dataset/version 集合，不引入 Report 之外的授权，也不改变 Corpus、Source、IndexVersion、原文和事实引用。
2. 两份新合同明确 `independent_facts=true`，保留整体问题、原文档子问、所有指标请求和 `metric_goals` 关联，不删除失败目标。
3. 宿主调用原 `confirm_finite_scope` 重新确认完整合同，生成绑定新合同与 RAG Hash 的证明。
4. Report 对这种显式确认的独立文档事实按其自身授权 Dataset 核验；默认关联型文档仍要求与指标 Dataset/version 一致。所有文档 Target 都必须落在 Report 批准的 Dataset/version 内。

这是 Report 对既有 `independent_facts` 契约的最小适配。未修改 Goal 版本、P3、Verifier、Citation 原文核验、Durable、预算、Embedding、Gold 或历史评分。

实际源码文件：

- `src/datapilot/reporting/service.py`：上述独立事实与 Dataset 授权检查。
- `evaluation/p7_v3_current/final50_scope_repair.py`：宿主侧合同重建；拒绝未批准的 RAG grant 或缺事实证明，不向 Worker 暴露。
- `tests/test_cross_dataset_document_facts.py`：10 项公开合成控制。

## 验证

Python 3.11、3.13 各 **166 passed / 0 failed / 0 errors / 0 skipped**。定向范围包括新跨 Dataset 文档合同、现有跨源报告、可信 Goal/范围完整性、Citation Policy 和新版引用评分。

新负例确认：未选择独立事实时跨 Dataset 仍拒绝；外部 Dataset/错误版本拒绝；缺指标证据或因果要求不能靠政策完成；范围变化须重新确认；宿主修复函数不能导入额外授权或补造事实证明。Ruff、format 和 `git diff --check` 通过。

实际 PG/MCP 使用前轮专用容器 `datapilot-p7-g2-60-postgres-1`、数据库 `datapilot_p7`、宿主端口 `55450`。没有访问历史业务库，没有清库或改写已有数据身份。两题先进入 `awaiting_review` 且模型调用 0，再通过原执行审批运行。

共 6 次 Fake 模型决策、90 个合成 Token 单位，付费调用 **0**，unknown **0**。两份签名采集的 HMAC 验证通过；原输入、Gold、pins 与旧 blocked 记录的 SHA256 复核未变。实际 P3 Evidence/Verification ID 与逐题完整维度见机器结果。

## 保留的验收脚本失败

051 执行后，脚本保存审批返回值时因 `BusinessCompletion` 对象不能直接 JSON 序列化而中断。这是采集脚本错误，没有重新执行 051：

- 原 `execution.log` 和部分写入的 `case-051/approved.json` 保留。
- 后续脚本复用原序列化 `encode`，对 051 仅调用 Collector。
- 052 当时尚未启动，之后才创建并审批一次。
- 完整结果来自签名 Collector、Inspector、Journal 和原评分链，而非不完整的审批返回文件。

初始与最终双版本测试日志均保留；最终测试前只整理了新测试文件的 import 顺序，原执行测试文件副本留档。

## 证据与边界

- [机器结果、P3 ID、引用指标与 SHA256](p7-final50-contract-repair.json)
- 本地证据目录：`artifacts/p7/final50-contract-repair-20261104/`
- `case-051/`、`case-052/`：新合同修订记录、配置、审批前状态、签名采集和 `score.json`。
- `preparation.json`：执行时源码与原件身份；`summary.json`：两题实际结果。
- `final-py311.xml/log`、`final-py313.xml/log`：最终双版本验收。

结合此前 8 题的新口径离线复评，这组十题现在均有非付费工程通过证据；它们涉及不同修订和执行批次，不计为一轮新的十题 Live 通过率。本轮未修改历史 Run、Gold、Seal、STOP 或原分数。

当前产品源码新增了 Report 适配，**新源码完整 CI：NOT_RUN；新 DeepSeek Live：NOT_RUN**。未 Commit、未 Push，未启动其他评测或下一阶段。
