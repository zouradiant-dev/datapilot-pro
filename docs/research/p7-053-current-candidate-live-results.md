# 053：当前工程候选与 v3 评分单题 Live

日期：2026-11-04，Asia/Singapore。负责人明确授权不等待完整 CI，执行 1 个新 Run，最多 8 次调用／18,000 Token、180 秒、零重试。**单题严格通过，业务终态为 partial。**

## 真实结果

| 项目 | 结果 |
|---|---|
| Campaign | `p7-053-current-candidate-20261104-v1` |
| 新 Run | `58a8b282-97dd-4b04-ab84-616f0354f033` |
| Provider / 模型 | DeepSeek / deepseek-flash，原端点，thinking disabled |
| 评分 | `p7-current-partial-evidence-v3`，16 项维度全部 True |
| 业务终态 | **partial** |
| Provider 调用 / Token | **4 / 7,139** |
| unknown / 重试 | **0 / 0** |
| 账单 | not_reconciled |
| 批次 | **STOP，许可消费 1/1 Run** |

原问题、指标和两个事实要求沿用原件。已知额度用途 `fact_1=true`，缺失的事故赔偿比例 `fact_2=false`。原文、引用与已知事实可以显示，第二个事实继续缺失。

RAG 实际提交 `insufficient`，RAG Worker 未完成；Report 保持 partial，`verified_goals` 只有 metric_1，缺口同时列出 `document_fact_unverified:fact_2` 与 `rag_task_insufficient`。显式 `partial-facts-v1` 合同及 v3 评分接受这种部分业务结果，没有把不足收据写成 complete，也没有把 documents 或整体目标升级为 verified/completed。

## 源码、签名与用量核验

- 候选为当前工程修复后的 421 个公开源码、依赖、评测与测试文件，raw 字节快照独立保存。
- 候选 Manifest SHA256：`ce54a620851085cb721edc24e7e16c29346069cbfabd7ab2a5fb1160296ab24c`。
- 执行 Binding SHA256：`d047783c9647303a822c0ec95f18af8406fd4d716572a2ca08cda09a2af85944`。
- 审批前模型调用为 0；随后通过原独立执行审批、Gateway、Durable Ledger、MCP、P3、Collector 与评分链。全部动作共用一个事件循环。
- 签名采集 HMAC 通过；4 条模型 Journal 记录均 complete，用量与 Collector 汇总一致；候选与快照无漂移。
- 132 份历史冻结、Gold、Seal、STOP 等受保护文件重新核对 SHA256，变化 0。

新 Run 是已暴露 053 的修复后单题回归，不是新独立 Holdout。原十题 v2 的 **9/10**、原 053 严格失败和旧停止记录全部保留。

本次执行后，工程打包工具另补了 README、公开 JSONL 与意图清单，形成 425 文件包；旧 421 文件快照与本次签名不修改。新旧包的业务源码、Worker 和评分器字节一致；新增验证输入只用于完整公开测试复现，不把本 Run 重新标记为新包的付费执行。

## 工程验证与后续范围

本次执行时完整本地 PG 回归仍在进行，负责人明确许可不等待。随后双版本非集成各 1420 passed，完整 408 个 PG/MCP 身份各 345 passed／63 opt-in skip；3.11 为初轮加精确环境错误复验，3.13 为一次完整运行。最终记录见 [候选整合验证](p7-current-candidate-integration.md)。完整远端 CI 仍 NOT_RUN，不将本次许可延伸到下一批。

负责人已明确将新 60 题正式 Live 及独立消融实验准备留到本轮结束后再讨论。本次许可已消费，不追加 Run，不重跑原批次，不提交或推送。

机器结果见 [p7-053-current-candidate-live-results.json](p7-053-current-candidate-live-results.json)。完整私密证据在本地忽略目录 `artifacts/p7/current-candidate-integration-20261104/053-live/`，包括新配置、审批前状态、审批返回、采集、签名、评分、汇总与 STOP；不随公共仓库上传。
