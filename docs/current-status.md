# P7 当前候选与验收进度

**2026-11-07 P7 本地交付收尾完成。** 455 文件 v4 候选按封存的 DeepSeek Flash 48k 配置完成 54 个正式 Run 和 6 项宿主拒绝。离线复验确认严格分和业务分均为 **60/60**，边界均为 **42/42**，数值及必需引文各 **36/36**。140 次调用、273,365 Token 与 DeepSeek 小时账单一致，本批实际扣费 ¥0.19409660。独立消融已暂停，Claude Code 产品对照已移出交付范围。下列记录为各轮历史状态。[正式验收与交付记录](research/p7-formal60-48k-acceptance.md)

**工程修复与发布 CI。** Web Runtime 在派发和最终交付边界复核宿主授权，撤权后阻断新增工作。Collector 按调用键稳定排序。修复候选本地 Python 3.11／3.13 非集成各通过 1,630 项，定向集成 94 项通过。GitHub 发布提交 `23c44c7` 的双版本 CI 均通过。[修复候选收口](research/p7-formal60-48k-acceptance.md#修复候选收口) · [远端 CI](research/p7-formal60-48k-acceptance.md#远端-ci)

**2026-11-07 独立消融已暂停。** 008–010 的 3 对短路径零付费预检符合 Gold，开启组压缩 0/3。011–012 首轮开关两组均符合 Gold，开启组压缩 0/2，自然压力准入 0/2。四段检索复验提案已封存，未启动。两轮预检的 Provider 调用均为 0。[消融准备与暂停记录](research/p7-independent-ablation-preparation.md)

## 历史记录

**2026-11-07 原候选本地工程复验。** Python 3.13 的 437 个集成节点全部结算，374 通过、62 个 Qwen／CUDA opt-in 跳过、1 个 Collector 调用排序断言失败。私有故障目录 14 项逐项核对，13 项满足控制，撤权切点部分满足，宿主拒绝已生效，内部 Worker 仍会完成。这两项原观察保留，后续修复见上段。[工程复验与故障边界](research/p7-formal60-48k-acceptance.md#python-313-矩阵复验)

**2026-11-07 本轮零付费收口：**源码工程修复与适用本地Gate已完成。最终v4候选455文件（`3cb3c353ad4ffad7010e0954a151c0dc65bd5d3c22fd63de5af5387914e6abd7`）；437个集成节点全部核对，375通过、62个明确Qwen/CUDA opt-in跳过，未解决失败/未运行均0。这是跨尝试及一项公开fixture-only修订的聚合覆盖，原失败保留，不称同一快照单次全绿。双Python非集成各1630通过；准备入口P2已修复并独立复核。四题原生业务预检4/4、数值5/5、事实6/6通过；已复用P3、不追加。全部本轮测试/Dev容器停止、卷保留，原151实例状态不变。负责人明确本轮不调用，Provider与新正式Runtime仍0；付费许可未签发，业务质量验收仍待。详见[本轮最终收口](research/p7-closeout-final-state.md)与[工程报告](research/p7-closeout-repair.md)。下方“进行中/待采用/STOP”均按历史发生时间保留。

**2026-11-07 新只读准入：**004两条SourceGoal经负责人具体采用后，公开Dev4题真实业务预检4/4、数值5/5、事实6/6通过。五条P3证据复用、未compute或追加，Runtime/Provider仍0，55457已停止且卷保留。新44成员Seal单列，旧空检索STOP不改；实际模型效果和正式业务Gate仍未通过/未测。完整工程回归和执行入口准备继续，状态以[收口修复](research/p7-closeout-repair.md)为准，下方旧STOP按其发生时点保留。

**2026-11-07 准入续进：**负责人已具体采用两份独立引用合同及四题公开Dev，并授权精确零付费物化。新55457已完成5 Dataset、4语义、4指标、6文档/3索引；5个数值目标均经CSV/PG/MCP及原P3核验，Evidence/Verification各5，Runtime/Provider为0。前三题真实发布准入通过；004两次检索返回空文档，原生准入已STOP，正在准备仅两条中性SourceGoal的修订提案，未改Gold或阈值，不重算既有P3。实例已停止且卷保留。完整工程集成仍在继续，详见[收口修复工作状态](research/p7-closeout-repair.md)。本段后续状态取代下方历史“待采用”，付费Live仍未授权。

**2026-11-06 当前收口：**新 60 题已完成 54 个 Runtime 问题及 6 项真实宿主拒绝的观测。分段选取严格 56/60、边界 33/37；已完成数值 29/29 正确，另 3/32 目标未完成，发布引文 34/34 核验通过。128 次调用、239,985 Token 全部结算。结果混合 18k／36k，仍未通过整体业务 Gate，不重新包装为独立统一预算评测。详见[分段 Live 原始总结](research/p7-fresh60-completed-live-results.md)。

负责人已要求推进规划、合同发布、预算与评分闭环的零付费修复，当前实际验证、新候选及剩余准入见[P7 收口修复](research/p7-closeout-repair.md)。两份新独立引用合同尚待采用；新 Dev／独立正式 Live 仍分别准入和授权。本轮不调用付费 Provider、不推送。以下原“最新”字样均保留为历史阶段记录。

**2026-11-06最新Live收口：**新独立合成60题首次Live在RAG-006触发父预算预留保护后STOP，许可关闭。Runtime23/24严格通过，另6/6宿主拒绝；30个Runtime未运行，固定分母29/60，边界17/37，整批业务Gate未通过。35次真实调用/44,067 Token，usage与只读PG及账本一致，unknown/未结算/待预留为0。该题实际2次/3112 Token，后续保守预留累计18,264超18,000上限264，未发出第三次调用。候选444、Gold、评分及历史记录保持，未自动续跑或推送。详见[新60题首次Live结果](research/p7-fresh60-live-results.md)。

以下保留此前工程与历史阶段记录，按发生时间理解；历史“未授权”“零Provider”不覆盖上述单独授权及实际Live记录。


**四项工程审计修复。** 该轮恢复 L4 摘要与最大合法后续调用的原子预留，限制决策 ID 为八个，并同步 benchmark、HTTP 与恢复探针。两版本非集成各通过 1,500 项，关联真实 PG/MCP 各 13 项，固定镜像内四项准入控制通过。原 60 题 51/60、修复 Dev 8 strict／1 blocked／1 not_run 和原 Seal 归各自批次。[四项修复与工程准入](research/p7-audit-four-fixes.md)

下方各阶段记录按其发生时点理解，历史“合同待采用”“Live 未运行”不覆盖后续单独回执与实际结果；不把任何旧许可或已看过的集合视作新的独立 Holdout 授权。

日期：2026-11-05，Asia/Singapore。分支 `p7-engineering-candidate-v1`。新 60 题首次 v2 Live 已完成：Runtime 45/54，加 6/6 宿主拒绝，总计 51/60（85%），业务 Gate 未通过；真实 DeepSeek 调用 143 次、205,772 Token。预期 P3 verified 数值 30/30，实际发布引文真实性 50/50，unknown 和安全违规均为 0。本批许可已结束。

负责人随后授权推进[完成合同与零付费闭环](research/p7-completion-contract-closure.md)：新候选区分检索与业务完成、校验必需来源、提供真实来源身份反馈、修正时间频率范围误判及 Collector 成本状态；使用新合成 Dev 走真实 PG/MCP/Report/签名评分，Provider 调用为 0。34 题边界结构化复核为 32 确认满足、1 未满足、1 证据不足，仍不宣称边界 Gate 达到 95%。e61b2a8、433 文件旧快照、正式 Gold/Seal/STOP/签名成绩保留，不推送；新批次不沿用旧许可。

上一轮候选为 437 文件（Manifest `7698fe078d426bed7b2795bc301b2e8ead76f8e09709969f84edeee319cb1660`），未授权 Live。Python 3.11/3.13 非集成各 1477 passed、原生控制各 8 passed，Ruff/CI 范围格式/diff 检查通过；八项原生断言含预期拒绝负例，不能作为新的业务成功率。当时 xsrc-010 的自然召回质量仍未证明解决，后续按下述新策略单独验证。

**后续授权修复：**现以再下一版候选推进[发布、解释与双来源修复](research/p7-publication-retrieval-repair.md)：显式部分证据与解释政策保留背景并继续拒绝无 P3 数字；缺证据不编造冲突理由；宿主审阅的问题组成部分绑定必需来源，受控查询仍最多两次，阈值不下调。新政策改变自由查询配方，原 437 文件候选及 51/60、34 题复核原件保持；本轮新增 Provider 调用 0，不采用旧许可。双版本非集成各 1494 passed，原生终态/恢复/签名控制和旧政策回归各 18 passed。新合成材料已验证对应机制，原三个正式题目未重跑；具体新候选及证据身份见新报告 JSON。

以下为各阶段历史记录，按当时范围和提交理解。先前的“Live 未启动”“待授权”和旧测试数量不覆盖上述后续状态。

### 当时的推进约定

按“候选整合 → 完整工程回归 → 053 与业务证据补齐 → P7 验收”推进。不把等待完整 CI 全绿作为所有下一项准备的前置条件；源码、合同、授权、未知调用和付费预算仍分别核对。

负责人此前要求新 60 题正式 Live、独立消融准备留到前轮收口后讨论。工程与 053 收口后，负责人已同意继续提交/推送、新 60 题适配和修订 Gold 审阅、独立消融协议与新 Dev 草稿准备。新 60 题及消融的付费 Live 仍未授权。

新 60 题使用补齐工程缺口后的候选：宿主范围确认、独立文档事实及跨 Dataset 检查、部分证据发布、共享事件循环和异常诊断修复都在新源码身份中。批次评分绑定 `p7-current-partial-evidence-v3` 及其 v2/冻结基础评分依赖；只有宿主合同显式启用 `partial-facts-v1` 时，部分证据规则才生效。缺失事实仍未验证，insufficient 不能冒充 RAG complete 或整体 completed。

### 当时的业务证据与消融准备

| 集合 | 当时已知状态 | 当时计划 |
|---|---|---|
| 旧 Gate 2B 60 | 原首次 Live 31 observed、29 not_run；原 v1 25/31、离线 v2 26/31 | 保留历史，不续跑旧 Campaign |
| Final 50 的十题修复回归 | 原十题 Live 严格 9/10；053 随后在当前候选及 v3 下新单题严格通过，partial，4 calls／7139 Token | 本次单题已 STOP；原 9/10 保留 |
| 新业务 Holdout 60 | SQL/RAG/组合各 20；十一题原修订及后续五项状态修订分别获接受；十题缺口已形成修复，现为 34 合同提案、2 精确来源待补、4 宿主拒绝 | 确认完整合同及两份来源准入、正式 Gold/Seal、原生 Dev 控制及独立 Live 准入 |
| 消融 | 已暂停。零付费对照、合同与提案分别留档 | 四段检索复验未启动，付费调用 0 |

新 60 题的既有材料保存在忽略的 `artifacts/p7/g2-business-60-private/`，没有把问题或 Gold 加入公共代码或候选运行输入。本轮在当前源码下只读复验已有专用库：54 条 pins verified pending launch binding、6 条 negative control passed。来源实际已存在于 55450 专用实例，旧封面“未物化”不能代替当前观察；本轮没有写入这些来源，也没有将来源预检写成 60 条业务通过。

Final 50 另有七题缺执行证据（071、072、073、074、076、078、079）及八题历史不确定（020、037、038、050、057、058、070、075）。旧未知调用不自动重发，不与新 Holdout 混合计算质量。

### 当时的工程整合

- 默认 pytest 收集 `tests` 和 `evaluation/p7_v3_current`。评测测试改用公开合成绑定、隔离临时文件和本地 HTTP，不再读取私密题库、数据库凭据或旧 Campaign。
- `current_binding` 在显式执行/验证时才读取旧 Manifest。历史 Freeze 的校验保留，当前源码仍不能套用旧绑定继续执行。
- `candidate_binding` 为新候选保存完整公开源码/依赖/测试快照、raw SHA256 和两个评分版本的文件身份；创建拒绝覆盖，验证拒绝源码、快照及 Manifest 漂移。
- `holdout_preparation` 将新 60 条修订草稿绑定到当前候选及 v3 评分。40 条文档合同仍需逐题审阅部分证据政策，不自动确认 Goal、登记 P3 或派发 Worker。
- CI 测试数量由实际 collection 生成，替代过期的 1748 固定声明；依赖、双版本、真实 PG/MCP、JUnit、覆盖率及 opt-in 边界保留。
- 本地 handoff 压缩包被明确忽略，私密交付与代码分开保存。

最终工程打包为 425 文件候选，Manifest SHA256 `cdb520d5f97ba1159e6345b69690335a109411df762e882162a5228e3b992974`。补齐了 README、公开 JSONL 和意图清单，直接在该快照上运行双版本非集成测试，各 1420 passed。

053 已执行的 421 文件候选保持原件；后续只修改打包工具与其测试、增加上述公开验证输入。业务源码、Worker、评分器及评分依赖与 053 执行时逐文件 Hash 相同，不将旧 Run 改签为新打包版本。

### 当时的验证与执行边界

本轮本地证据写入 `artifacts/p7/current-candidate-integration-20261104/`，最终结果另见同目录交付记录。新建独立 PG17/pgvector：3.11 使用 `datapilot-p7-candidate-20261104`／55451，3.13 使用另一实例 `datapilot-p7-candidate-20261104-py313`／55452，均为 `datapilot_test_` 前缀的新数据库；不在同一 PG 实例并发做故障测试，不重置历史实例或卷。

双版本非集成各 1420 passed；不含本地私密工件的公开副本 1420 passed；Ruff 与 format 通过。当前计划由实际 collection 得到 1828 = 1420 非集成 + 408 集成。

首次 3.11 集成回归为 123 passed、62 skipped、223 setup errors，错误均指向 Windows 系统 Temp ACL。首轮日志与 JUnit 保留；专属临时目录对原 223 个身份精确复验，得到 222 passed、1 CUDA opt-in skip、0 failed/errors。两批合并完整覆盖 408 个身份，最终 345 passed／63 合法 skip；不冒称一次干净全量运行。

3.13 独立实例一次完成完整 408 项：345 passed／63 合法 skip、0 failed/errors。两版本集成身份集合完全一致，跳过均为 Qwen/CUDA 62 项及 Live opt-in 1 项。本轮工程验证已收口，详见 [最终整合与本地验证](research/p7-current-candidate-integration.md)。两套新建测试容器已停止，卷和证据保留，历史实例未停止。

前轮完整远端 CI 原为 NOT_RUN；当前 `4460009` 已推送并启动远端双版本 CI。新 60 题准备新增公开合成评分/合同控制，旧 v3 评分器及产品源码保持原件。新增 60 题准备详见 [正式准备记录](research/p7-new-holdout-formal-preparation.md)，消融见 [独立消融准备](research/p7-independent-ablation-preparation.md)。前轮唯一新增付费执行仍为已结束的 053：4 次调用／7139 Token，unknown=false；本轮准备新增付费调用 0。

新准备工具已通过 Python 3.11 / 3.13 各 1433 项非集成测试（含新增 13 项），Ruff / format 通过。60 题及修订 Gold 的可审阅材料已保存；文档完整语义审阅现已完成，合同采纳、正式 Seal 及原生入口验收仍待完成，当前不能启动正式 Live。

准备源码已提交/推送为 `dc9e638`，[该提交双版本 CI #41818754250](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41818754250) 已触发。负责人随后接受 11 题修订及 Gold，独立追加 [审批记录](research/p7-new-holdout-revised-gold-approval.json)；40 题文档合同另有本地可读审阅提案，含 53 个待语义核验的引述候选和 2 项独立缺失事实审阅，均未批准或派发。

负责人现已授权完成 [40 题文档合同完整语义审阅](research/p7-document-contract-semantic-review.md)。24 份可确认提案含 37 个引述证明提案；另有 2 份精确单文件索引预览、4 个必须保留的宿主拒绝用例，以及 10 个语义/完成状态差异。全部 40 题审阅结束，合同采纳与正式准入尚未通过；不把先前待审引述数量或本次审阅数量当作 Holdout 业务成绩。相关公开回归 149 passed，无模型调用或数据库写入，已接受 Gold 和原候选保持原件。

**2026-11-05 后续修复：**负责人授权处理上述十题，并接受五项具体完成状态修订。五题保留 Gold 补齐合同，另外五题追加状态修订与独立审批；新 60 条 revision-02 只改五个预期状态，其他作者字段不变。新增未绑定指标目标和必需证据引用的显式契约，新宿主评分适配为 v2；默认旧合同序列化及历史评分保持。新 432 文件快照双版本非集成各 1449 passed、定向原生 PG/MCP/Collector/签名评分各 2 passed；未声称全量集成或业务 Live 通过。完整记录见 [十题合同修复](research/p7-ten-contract-gap-repair.md)。

旧冻结 Manifest、Gold、Seal、STOP 和历史分数保持原件。候选准备不等于生效 Permit；业务补验与新 Holdout Live 按各自精确合同和预算独立准入。

相关记录：[本轮最终交付](research/p7-current-candidate-integration.md)、[十题 Live](research/p7-final50-ten-live-results.md)、[053 修复](research/p7-053-partial-evidence-repair.md)、[当前候选 053 Live](research/p7-053-current-candidate-live-results.md)、[Final 50 对账](research/p7-final50-reconciliation.md)。原始检查与本地证据目录为 local-only，不随 Git 上传。
