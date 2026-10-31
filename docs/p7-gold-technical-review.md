# P7 Gate 2B：Gold 技术初审（2026-10-25）

本轮按用户要求，先审核能够从冻结原件和既有业务口径复核的 Gold。**60 条均完成 Codex 技术初审，其中 50 条未发现技术一致性冲突，10 条需要处理或裁决。独立人工审核仍为 60 pending、0 approved，Gate 2B 继续 blocked。** 这里的“技术一致”仅表示原始数据、提案口径与 Gold 相符，不表示已获得业务审批、已通过被测 Agent 或已证明正式业务成功率。

逐条私有结果位于 `artifacts/p7/gate2b/private/gold-technical-review-20261025/technical-review.html` 和同目录 JSON；该目录含完整问题、原答案、重算选中行/队列、原文引用、逐条意见、疑点与待人工字段。公开 [机器可读摘要](research/p7-gold-technical-review.json) 只记录数量、问题类型和私有证据 SHA，不含答案数值或文档正文。原 [人工审核包](p7-gate2b.md#2-gold-审核包) 没有改成 approved。

## 已完成的审核

- **27 个预期数值目标**：用另一份离线实现，直接读取封存 CSV/XLSX，按提案的字段映射和 [P3 已记录口径](semantic-metrics.md#已实现口径saas_metrics_v1) 进行 Decimal、日期和集合复算。金额/单位、paid/币种过滤、右开边界、合同/客户分母、重订阅、并行合同和事件 feature 均核对，全部相符。原 15 条真实 PG/MCP 证明只保留原字节，不重新执行或覆盖。
- **10 个不可计算指标目标**：复核 USD 不支持、MRR 缺少经常性定义、历史未确认完整、零分母、重复事件 ID、单位未确认等理由；没有补数、汇率或口径。
- **40 条文档任务**：逐条检查相关性、必要来源数、历史/最新版本、信息不足、时期不匹配、权限和注入边界。共 48 次 Gold 事实引用的原文跨度、事实行号、Source/Document/Chunk 身份和 hash 均能核对；47 个索引内文档快照及 47 个 chunk 的元数据校验通过，含历史版本和跨索引重复来源，不代表 47 个独立业务来源。没有执行召回或相似度实验。
- **60 条完成/拒答配置**：分别检查宿主阻断、指标能否计算、文档是否足够和最终业务结论。因果问题不能因检索完成而升级成已验证因果。

审核实现没有导入原 Gold oracle、Agent、业务配方或 Verifier，也没有读取被测 Agent 的答案。它仍由同一 Codex 工作链完成，且已经参考项目业务定义，**不构成独立人员盲审或独立作者 Gold**。覆盖范围和合同历史完整性仍是待人工确认的业务声明，不能仅由源文件的首末行证明。

## 需要处理的 10 条

| Case | 发现与最小后续行动 |
|---|---|
| bh2-030 / 033 / 035 / 038 / 040 / 054 / 059 | 7 条原有授权兼容阻断：Document 子集 pin 与当前索引的全量 manifest 授权要求不匹配。原件/目标及文档不足的设计可以审阅，但任务暂不能按原输入执行。待独立裁决后，另行授权兼容子索引/输入的新封存版本；原包保留，MCP 权限不放宽。 |
| bh2-001 | Gold 金额和独立原 SQL JOIN 证明相符；但当前 MetricRequest/Gold 结构和未完成 Scorer 不显式要求实际完成题目中的客户主数据 JOIN。只做账单单表求和也可能通过数值项，无法证明 JOIN 目标覆盖。需要明确 JOIN 是必需验收项还是仅为粒度说明，不能自动降为数值匹配。 |
| bh2-048 | Gold 要求 confirmation_required，当前实际元数据检查返回 REPORT_SCOPE_INVALID；离线严格 scope 分类器将未授权的指定版本归入拒绝，因此有 **1 个宿主分类检查 mismatch**，不是数值或原文错误。原 Gold 同时给了 blocked 和 complete 文档参考事实：必须明确事实仅为条件性参考，阻断前不要求读取。不能为拿到引用执行已被拒绝的请求；当前 Scorer 对拒答/阻断仍未完成，不能照搬其事实覆盖规则评分。 |
| bh2-055 | 数值和各自单位一致；题目还有不同单位不能共用数值轴的要求，当前 Gold/Scorer 没有显式图表检查。原 Report 契约已有单位限制，但运行期守卫不等于独立评分覆盖，需审核裁决该要求如何验收。 |

因此，机器结果细分为 **50 consistent_under_proposed_policy、9 needs_resolution、1 mismatch**。这些是技术审核分类，不是正式 Holdout 的模型失败或成功次数。没有发现已审核数值与原件之间的差异，但不能据此宣称全部 Gold 已通过业务验收。

其中 JOIN/图表两项是评分覆盖缺口，版本阻断一项是语义/阶段分类待裁决。没有自行补写封存 Gold、改分母或修候选来匹配这些问题。若审核决定确需修改，应保留旧 seal 和记录，以另外授权的新版本处理。

## 验证与保全

本轮执行的命令：

```powershell
.venv\Scripts\python.exe artifacts/p7/gate2b/private/gold-technical-review-20261025/review.py
.venv\Scripts\python.exe -m pytest artifacts/p7/gate2b/private/gold-technical-review-20261025/test_review.py -q
.venv-313\Scripts\python.exe -m pytest artifacts/p7/gate2b/private/gold-technical-review-20261025/test_review.py -q
.venv\Scripts\python.exe -m pytest tests/test_p7_holdout_preparation.py tests/test_p7_gate2b.py -q
.venv-313\Scripts\python.exe -m pytest tests/test_p7_holdout_preparation.py tests/test_p7_gate2b.py -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe check artifacts/p7/gate2b/private/gold-technical-review-20261025
.venv\Scripts\ruff.exe format --check artifacts/p7/gate2b/private/gold-technical-review-20261025
git diff --check
```

私有审核脚本拒绝覆盖已有审核结果；重复审核应建立新的版本，不删除旧记录。Python 3.11/3.13 的 Toy 审核器测试各 **8 passed**，原准备/隔离评分契约各 **32 passed**；两者不计入 60 个业务任务。Ruff、JSON、文档本地链接和 Git Diff 检查通过，JUnit 及验证记录留在同一私有目录。首次 Ruff 样式问题已修正；没有把 1 个 Gold 分类 mismatch 隐去或改成 passed。

原封存包 66 个文件全部 hash 核验；seal 仍为 `7af09ffe2320dfdad3535c55ed89e96124a7fd4bad0d66bc1cc898dbec464ecc`。116 个生产/依赖/迁移文件、18 个意图冻结文件、原准备器/评分器、人工审核包及 v2.4/v2.5 规划文件均未修改。原 Gate 2B freeze 仍为 `891b9e83e7d064f9934aa8524b9b96bf570f6abdb7eddb4390a2379a2bab0b15`；本次是独立追加的审核记录，不替换该历史 freeze。

本轮没有数据库读写、Registry 确认、正式 Agent 执行、检索查询或付费模型调用。未重新运行此前源码未变的完整 PG 回归；其结果保持 [Gate 2B 交付记录](p7-gate2b.md) 中的历史验证属性。未提交/推送。

## 接下来的审核

先由独立审核人查看私有逐条技术意见，确认业务提案与拒答条件，裁决上述 10 条；记录身份、时间和可验证的逐条决定。确认前 P3 Semantic/Metric 仍不登记为 approved。正式 Runner/完整 Scorer 和 Live 授权等其余阻断仍见 [Gate 2B](p7-gate2b.md)，本轮没有将其标为完成。
