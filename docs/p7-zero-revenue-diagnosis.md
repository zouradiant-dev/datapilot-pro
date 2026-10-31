# Gate 2B：bh2-016/052 零收入拒绝根因

后续状态：本页是修复前历史诊断，原 rejected 和所有哈希保留。负责人随后独立授权最小序列化修复，三个定向检查和双版本适用回归已通过；当前状态见 [修复交付](p7-numeric-serialization-fix.md)，不追溯改写本页诊断或旧业务判定。

2026-10-25，本轮仅做只读核验与离线定向测试。结论：**NUMERIC 结果序列化与 P3 定点解析契约不一致，是实现缺陷；不是缺少业务定义，也不是业务规则禁止零收入。** 问题未修复，Gate 2B 保持 `blocked` / `ready_for_live_authorization=false`。

前轮 A/B 32 项已按原 Registry 接口登记，身份、版本和 Hash 匹配；C 两项及故意不存在的版本仍缺失。该审批不需要重做。当前根因分析不修改这些定义，也没有新的 Registry 写入。

## 原始记录及完整性

使用已有受限 MCP `get_evidence` / `get_verification` 重读原记录，再通过 `get_metric_context` 重读相同 Dataset/Metric/Semantic 版本。context/source/semantic/metric hash 与原 Evidence 一致，原结果 hash、查询 hash 和完整 Verification checks 的本地复核均通过。

| 对象 | bh2-016/052（同一指标请求，共用定向验收证据） | bh2-047 对照 |
|---|---|---|
| Evidence ID | `4f1ccf99-901f-4e2c-abc0-d0054aa8094d` | `efa35865-eb40-44ff-be1a-f46bdc99f339` |
| Verification ID | `dcd34f1c-de7a-4fa3-b260-de4385eb85dd` | `3a846ab5-a7af-4df1-a7b3-ded6ac50167c` |
| 原 SQL 结果 | `"0E-20"`，一行，未截断 | `"447.5600000000000000"` |
| 独立 Python proof | `status=computed`，`0 CNY`，原始投影 2 行 | `447.56 CNY` |
| 原 Evidence.value | `null` | `447.5600000000000000 CNY` |
| 原 verdict | **rejected** | **verified**，六层通过 |

原 `MetricExecution` 是运行时对象，没有单独持久保存。本轮从持久 Evidence 的 request/query/result/proof/missing 和哈希相同的重读 Context 重建诊断 DTO，明确标记 `reconstructed_from_persisted_evidence_not_original_object`。这不冒充取回原内存对象，也没有重新执行 SQL。对该 DTO 调用原纯函数 Verifier，只在内存中复现相同 verdict 和六层 codes；没有追加或替换 VerificationRecord。

私有原件和诊断投影：

- [原定向失败记录](../artifacts/p7/gate2b-v2/p3-owner-confirmation/targeted-p3.json)
- [MCP 重读 Evidence / Verification](../artifacts/p7/gate2b-v2/p3-owner-confirmation/directed-evidence-readback.json)
- [重建执行 DTO 与 Context](../artifacts/p7/gate2b-v2/p3-owner-confirmation/directed-execution-projection.json)
- [机器可读诊断](research/p7-zero-revenue-diagnosis.json)

## 三类原因的判断

**1. Gold 零值证明不足：本次不是这个原因。** 所批 Semantic 对 invoices 明确声明 UTC、整数分、覆盖 `[2023-01-01, 2024-01-01)`；请求为 `[2023-03-01, 2023-04-01)`，筛选 `paid`、CNY。此前真实源行对照匹配，独立 Decimal 和原 MCP Python proof 均得到 0。覆盖完整性来自项目负责人的明确业务声明，不是从“没有行”猜出；文件/hash 本身不能证明现实企业没有漏导数据。本结论只适用于已确认快照和口径，不外推现实账务真实性。

`history_complete=false` 在此是 invoices 映射，未撤销显式观测覆盖；当前封闭配方对 subscriptions 的完整合同历史另有要求，不能混用。重读 Context 的 `request_missing=[]`、执行缺口 `missing=[]`、proof 缺口 `missing=[]`，原 semantics 层 passed。

**2. P3 业务规则按设计拒绝：不是业务层拒绝零收入。** 规则本来接受合法定点 `"0"` / `"0.00000000000000000000"`，本例不存在缺口径、超时间范围、零分母或 MRR 不支持等拒答条件。Verifier 面对不符合解析契约的输入继续失败关闭是正确的安全行为；不能为零值放松该校验。

**3. P3 执行/验证实现缺陷：已复现。** 路径为：

1. 原收入配方对无匹配 paid 行执行 `COALESCE(SUM(CAST(amount AS DECIMAL)),0)/100`，得到精确 NUMERIC 零。
2. [SQL 结果边界](../src/datapilot/tools/sql.py) 的 `_serialize_cell(Decimal)` 调用 `str(value)`，保留 Decimal 的合法指数形式 `"0E-20"`。
3. [P3 数值解析](../src/datapilot/semantics/recipes.py) 的 `scalar()` 只接受有界定点字符，拒绝 `E`；`metric_value()` 因此抛出 `Bounded fixed-point numeric text required`。
4. [Evidence/Verifier](../src/datapilot/harness/metric_verification.py) 无法形成合法 value，产生以下原 codes。独立复算没有把零算错，后续两层失败由主结果无法解析连带触发。

| 层 | 原状态 | 原 reason code / 含义 |
|---|---|---|
| safety | passed | 原 SQL 安全检查通过 |
| shape | failed | `result_invalid`：NUMERIC 文本解析拒绝 |
| semantics | passed | 口径与封闭配方匹配 |
| recomputation | failed | `independent_result_mismatch`：主 value 无法解析，不能与 computed proof 比较 |
| references | passed | 原 Evidence 引用通过 |
| coverage | failed | `goal_not_covered`：没有可发布的合法主 value；不表示 Semantic 时间覆盖缺失 |

原 `rejected` 保留，没有改成 unavailable/completed，也没有发布 0 的 verified 报告。047 接口返回普通定点形式，故同一解析链正常工作；四月规则仍仅为引述背景，不追溯改变三月计算。

## 实际定向测试与限制

本轮只执行 `artifacts/p7/gate2b-v2/test_zero_diagnosis.py`：Python 3.11 / 3.13 **各 5 passed**。覆盖 Decimal 指数零复现、合法定点零/正数对照、两个原执行 DTO 的 verdict/codes 重放、覆盖定义和 proof 缺口检查。测试通过表示**根因被复现并解释**，不是缺陷已修好；原定向业务验收仍失败。

命令为相应虚拟环境下 `python -m pytest artifacts/p7/gate2b-v2/test_zero_diagnosis.py -q -p no:cacheprovider`，JUnit 为 `zero-diagnosis-py311.xml` / `zero-diagnosis-py313.xml`。只读脚本复用原 MCP；本轮指标执行、模型调用、数据库写入均为 0，没有启动全量回归。前轮 173 项适用回归两版本通过是历史结果，不能覆盖这次定向业务反例。

## 最小后续行动及冻结影响

后续应单独授权一个结果表示契约修复：优先在可信 NUMERIC 序列化边界产出**有界、无精度损失的定点文本**，保持 P3 原严格解析与六层守卫。不改 SQL 配方、Gold、单位/过滤/覆盖声明，不给零值开特例，不经过 float，不无界展开大指数。

先使用合成开发反例覆盖带 scale 的零、普通/极小/大精度 NUMERIC、输出长度限制及非法值，再验证真实 PG/MCP；通过后才重新执行受影响的定向业务检查。旧 rejected Evidence/Verification 必须保留，新执行产生新引用，不覆盖旧记录。

**本轮未改变冻结 Runtime/候选实现或 v1/v2 Gold Seal。** 若后续修改 `src/datapilot/tools/sql.py` 等冻结实现，会影响原执行基线，必须建立新的实现 freeze/修订记录，披露首次失败与修复差异；不能追溯宣称旧版本已通过。数据、Gold、授权 pin 和评分语义保持相同时，不需要为掩盖失败改 Gold Seal；若其中任何项确实变更，另建新封存版本。不得使用 Holdout 做 Prompt/阈值/口径调优。

当前阻断是上述结果表示契约缺陷影响 016/052 的可信零收入发布。没有新的定义批准或权限扩大需求；本轮到根因分析为止，不实施修复、不启动 Live 或 Gate 3、不提交推送。
