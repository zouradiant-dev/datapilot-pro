# P7 19 条新公开合成业务任务与独立 Gold

日期：2026-11-03。**19 条已落盘、验证并封存；没有执行正式任务。** 旧 v3 31 条保持“未执行候选”，未重新审计或执行。

## 1. 实际文件

- Case 输入：`artifacts/p7/final-evaluation-v1/supplement-19/inputs.jsonl`
- 独立 Gold（私有）：`artifacts/p7/final-evaluation-v1/supplement-19/private/gold.jsonl`
- 公共输入资产：`artifacts/p7/final-evaluation-v1/supplement-19/assets/`
- 数据/文档 pins：`artifacts/p7/final-evaluation-v1/supplement-19/pins.json`
- Launch 配置：`artifacts/p7/final-evaluation-v1/supplement-19/launch-configs.json`
- Oracle：`artifacts/p7/final-evaluation-v1/supplement-19/private/oracle.json`
- Schema/合同验证：`artifacts/p7/final-evaluation-v1/supplement-19/private/contract-validation.json`
- Seal：`artifacts/p7/final-evaluation-v1/supplement-19/SEAL.json`
- Manifest：`artifacts/p7/final-evaluation-v1/supplement-19/manifest.json`

## 2. 数量与覆盖

| Lane | 数量 |
|---|---:|
| SQL-only | 7 |
| RAG-only | 7 |
| SQL+RAG | 5 |
| 合计 | **19** |

Case ID：`p7-holdout-v3-061` 至 `p7-holdout-v3-079`，与旧 v3 的 001–060 不重号。

预期业务状态：

- completed：**15**
- unavailable：**3**
- partial：**1**

覆盖：收入、活跃订阅、使用量、日期右开、单位/覆盖拒绝、缺历史拒绝、多来源/精确原文、英文来源、缺证据、因果边界、组合指标+事实。

## 3. Gold 与独立性

- 数值：由公开 `master.xlsx` 的发票/支付/订阅/事件数据用 pandas/Decimal 独立计算；进入 `oracle.json`。
- 文档：Gold literal 直接来自合成原文，按精确 Source/Chunk/IndexVersion 和 span 校验。
- 没有读取 v3 Gold 来调整产品、Prompt、P3、Report 或阈值。
- 生成方式是 **AI-assisted public synthetic authoring**；不冒称第三方独立或人工盲审。

## 4. 验证结果

- 19 个 Case/Gold ID 一一匹配、唯一，lane 7/7/5。
- 19 个 launch config 的 ReportScope/RagScope 均可解析。
- 所有 Required Fact citation 的 source/document 均存在于 pins。
- 所有文档事实 literal 均能在公开合成原文中定位。
- Oracle：**all_ok=true**（24 项检查）。
- Contract validation：全部通过。
- 包 Seal aggregate：`2ee42be4970570032179ff19bbfdd09afc6db8bb9e64f8cb826170001fb65d11`

## 5. 待物化/待确认

- 19 条新任务复用 v3 公共合成 Dataset/Corpus/Source/IndexVersion；当前隔离 PG 尚未物化这些数据，需在下一轮用现有 Ingestion/RAG 工具物化。
- 31 条 retained + 19 条 new 尚未合并为 50 条准入；本轮不执行正式任务。
- 现有 v3 业务定义/版本复用；没有新增需要负责人确认的指标定义。
- 若负责人要求独立人工审阅，仍需单独签署；本轮不伪造。

## 6. 边界

- 未调用 DeepSeek；未创建 Permit；未执行 Fake/Live 正式任务。
- 未修改产品或评分器，未修改历史 v3 Gold/Seal，未清库，未 commit/push。
