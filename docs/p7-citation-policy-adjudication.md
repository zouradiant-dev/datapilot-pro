# P7 Citation Policy 候选裁决

状态：**PENDING_OWNER_ADJUDICATION**。这是新的政策提案与 Dev 验证，不是负责人批准，也不追溯修改 v3/v4、Gold 或原 20/29 成绩。

## 三层来源与 Claim 关系

| 来源类别 | 准入条件 | 不能承担的作用 |
|---|---|---|
| Required Evidence Source | 授权、Dataset/Source/Document/IndexVersion/span/hash 有效；直接支持宿主规定的必需 Claim；达到独立 Source/Document 覆盖 | 不同 Chunk 不能重复计数；背景不能替代缺失必需来源 |
| Acceptable Supplementary Source | 同样通过真实性与版本检查；预注册的具体补充 Claim 与全局目标有关；经宿主确认的精确引述能支持该 Claim | 不增加必需来源覆盖，不补齐未知指标、不扩大事实、货币或时间范围，不证明因果 |
| Irrelevant / Misleading Source | 仅关键词接近、邻近业务背景、缺少可核验 Claim 支持，或使读者误以为目标已得证 | 即使已授权、相似度高、hash 正确也不能作为合格引用 |

Claim→Citation 关系至少绑定 claim_id、用途、原始目标/子目标、source/document/chunk/index/version、span/hash、引述与可信确认来源。数值 Claim 仍绑定 P3 Evidence/Verification；文档引述不能替代 P3。授权、相关性、引述真实性、具体事实证明、必需来源覆盖、业务完成分别记录。

补充关系不是模型可自行填写的权限。开放语义是否足以支持一个 Claim，现有确定性字面核对不能普遍裁决；不满足受审阅证明时留为未确认，不能因 `acceptable_supplementary` 标签直接标记 fact verified。

## 两种候选

| 候选 | 引用准入 | 权衡 |
|---|---|---|
| Required-only | 发布集合只含 Required，且覆盖 Required | 可重现、严格，但会处罚真实有用补充，Gold 标注遗漏影响较大 |
| Required + Claim-grounded Supplement（推荐待裁决） | 覆盖全部 Required；额外来源须有独立的、目标相关且实际得证的补充 Claim | 更贴近报告用途，但增加 Claim 标注/审阅成本；不能直接接受“相邻领域” |

两者均：缺少 Required 判来源覆盖失败；无关/误导来源判引用精确性失败；未证实 Claim 否决该事实发布及依赖它的 completed。补充来源不计入 minimum_sources。默认不加未经注册的分数权重或自动抵消惩罚。

Precision@k（检索）与报告引用 Precision 分开。报告严格策略分子是 Required 引用；补充策略分子为 Required 加已得证补充，分母为实际发布引用；Source/Document 去重，并另报必需覆盖、支持 Claim 覆盖与错误 Claim 数。空分母为 NA。不能用背景引用数量增加覆盖。

新 cp09 Dev 中，配额二进制单位与展示舍入是不同 Claim。原 MCP 验证两份来源，原 `fact_coverage` 核对补充引述：Required-only 拒绝额外引用，Claim-grounded 候选接受；伪造引述仍失败，只有补充来源仍缺 Required。cp10 的果园文档通过第二次真实检索取得，但与工单目标无关，原 Report 未发布它；若人为把它加入发布集合，两种政策都拒绝。不是所有额外来源都应放行。

## 七条历史案例的只读政策分析

以下“拟关联 Claim”是审查建议，历史报告并没有完整的独立补充 Claim 证明关系；表格不提供新通过分数。

| 原案例 | Required / Extra | Extra 拟关联 Claim | 直接证明原必需事实 | 新候选原则与争议 |
|---|---|---|---|---|
| 041 | settlement.md / credit.md | 额度限制 | 否 | 邻近计费背景，默认排除；是否允许另列背景需负责人裁决 |
| 022 | revocation.md / credential.md | 凭据轮换 | 否 | 不证明令牌撤回顺序，默认排除；不能把安全邻近性当证明 |
| 023 | credit.md / settlement.md | 额度与实际收款区别 | 否 | 全局目标含收款区别时可作为补充候选；须明确 Claim/引述，Gold 范围存在争议 |
| 024 | metering.md / contracts.md | 续订与流失队列 | 否 | 与事件重试计费无直接关系，排除；属于引用选择问题 |
| 045 | settlement.md / credit.md | 额度说明 | 否 | 不证明退款登记，默认排除；相邻资金背景仍需独立用途 |
| 047 | credit.md / settlement.md | 已付收入与现金退款 | 否 | 全局目标较文档子目标宽，可能合理补充，不能自动变为通过 |
| 049 | credit.md / settlement.md | 已支付收入核算 | 否 | 可支持收入部分，不补齐 MRR 定义；partial 保留，来源政策待裁决 |

七条原必需来源均已命中；真实性成立不代表额外引用相关。三条补充候选、三条背景边界意见均未获负责人新政策批准。原 v3/v4 citations 和 strict 结果不变。精确身份/版本/hash 继续引用上一轮审计，不重跑历史检索。

## 待负责人决定与版本迁移

待裁决：选择默认策略；全局目标与文档子目标的补充范围；是否允许不参与证明的背景单独展示；谁确认补充 Claim；标注分歧处理与惩罚粒度。推荐把背景与证明引用分区，未审阅补充不得进入严格证明分子。

批准后才建立新 Policy/Gold/Protocol/Scorer 版本，记录 parent seal、逐条变化、分母和新 Claim 关系。旧 v3/v4 和历史 Gold 永久保留；不回填旧来源标签刷分。新的独立 Holdout 必须预先标注 Required/允许补充/拒绝条件，冻结后再评测，不能使用旧29调阈值。

机器记录：[候选政策](research/p7-citation-policy-candidate.json)。Dev 原件与证明位于忽略目录 `artifacts/p7/citation-partial-dev-v1/claim-policy-probe.json`；没有独立第三方人工签名，也没有生产政策变更。
