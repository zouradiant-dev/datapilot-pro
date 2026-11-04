# 新 60 题正式准备记录

日期：2026-11-04。前轮工程验证与 053 单题已经收口；负责人随后同意按“提交与远端 CI → 新 60 题正式适配 → 修订 Gold 审阅 → 单独 Live 准入”的顺序继续，准备工作不必等待完整 CI 结束。

## 已完成

- 工程修复已提交并推送为 `44600094a322c5049a6a8dfee6b7a3189f24605d`，完整双版本 [Actions #41816538430](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41816538430) 已触发。原 425 文件 raw 候选及其本地双版本验证证据保留，Git 的换行标准化不改签原候选。
- 增加 `HoldoutCase` / `HoldoutAnswer`，专用 `g2-bh-{sql,rag,xsrc}-001..020` 命名空间，禁止复用历史 ID。Case 绑定完整 ReportScope，包含政策及确认字段；模型候选输入不含 oracle、预期状态或拒绝 Gold。
- 新宿主评分适配器 `p7-new-holdout-host-v1` 复用修复后的 `p7-current-partial-evidence-v3`。宿主直接拒绝进入原始拒绝分支，无需报告快照；运行结果仍验证 Collector HMAC、完整 Scope、文档审批和原 v3 各项维度。旧评分器、053 和历史结果没有改写。
- 60 题已编译为严格合同草稿。40 道文档合同都保留逐题政策审阅，不批量启用 `partial-facts-v1`，不自动创建有限目标确认。
- 11 道 revision-01 题的原始 XLSX 独立 Decimal 结果、PG Reader 查询结果、草稿 Gold 三方一致；原 metric / semantic / source / query / result 身份全部复现。没有写入业务来源、登记新 P3 结果或创建 Run。
- 55 条事实要求的本地来源文本与原绑定 Hash 一致。54 条提示出现一次，1 条出现两次；原文命中只说明文本位置，不能证明提示等于完整问题，也不能把“目标事实缺失”改成已验证。

本轮新增公开控制 13 项；Python 3.11 / 3.13 各 **1433 非集成测试通过**，另有 408 个集成身份分别保留给远端 CI/前轮隔离证据。Windows 首次默认 GBK 下各有一个旧测试 `read_text()` 解码失败；按 CI 相同的 `PYTHONUTF8=1` 复验全部通过，原失败日志保留。Ruff 与 format 通过；132 个历史受保护文件 raw SHA 未变。

最终审阅包绑定 430 文件 raw 候选，Manifest SHA256 `da632e6d625f9bb2e56bd4bea0b18c916926f6f23d436f78c0c8d494864090c4`，保存在本地 `candidate-v3/`。相对工程基线只增评测合同/适配/审阅工具及其公开测试；产品源码和历史 v2/v3 评分文件未变。审阅材料没有加入候选快照或 Git。

## 可直接审阅的本地材料

目录：`artifacts/p7/holdout60-formal-preparation-20261104/review-v2/`，整个目录被 Git 忽略。

- `private/OWNER-REVIEW.md`：11 题原题→修订题、指标请求、三方数值、原 Gold、保留的拒绝要求及文档事实。
- `private/revised-gold-review.json`：完整原题/新题、原始回执与复核记录；原件的 PENDING 保留，后续接受决定单独追加。
- `private/contract-review.json`：60 题完整问题语义审阅、40 题文档目标/部分证据政策、原事实绑定、缺失或拒绝要求。
- `private/fact-review.json`：55 条文本检查，含多次出现提示；不把文本提示升级为事实证明。
- `draft-inputs.jsonl`：60 个严格 Case 草稿，不含 Gold；**未批准，不可派发**。
- `manifest.json`：公开源码候选、v3 评分依赖、新适配器、私密绑定及上述文件身份。

这些是审阅草稿，不是正式 Seal。原始 revision-01、旧 Freeze/Gold/Seal/STOP 均保留。

负责人随后明确接受这 11 题的修订及 Gold 提案。新增审批回执精确绑定上述审阅文档、Manifest、11 条修订输入/Oracle/MetricRequest 哈希，见 [公开审批元数据](p7-new-holdout-revised-gold-approval.json)。该接受不等于文档合同、P3 定义变更或付费 Live 授权。

40 题文档合同另已整理为本地 `document-review-v1/private/OWNER-DOCUMENT-REVIEW.md`，包含完整问题、原始/拟定目的、ReportScope/RagScope、逐事实来源/引述候选、原拒绝边界及待审项。53 个引述候选经机械定位可供语义审阅；另 2 项缺失事实保留独立审阅，不用负面提示代替目标事实证明。该包有独立 Manifest，未改变前述不可覆盖的 review-v2。

准备源码已提交/推送为 `dc9e638`，[完整双版本 CI #41818754250](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41818754250) 已触发；没有把原生入口准入写成完成。

## 尚需完成的准入

**后续更新：**负责人已授权执行文档完整语义审阅，40/40 已完成；结果为 24 份可确认合同提案、2 份精确来源待补、4 份宿主拒绝、10 份语义缺口。原 review-v2 / document-review-v1 保持原件，新的逐题材料与下一步见 [语义审阅记录](p7-document-contract-semantic-review.md)。下面的合同确认、正式封存及原生入口准入仍未被审阅本身代替。

数值正确只解决 11 题的数字复核。反事实、口径替换、未确认优先级、缺失事实、因果和额外自然语言子目标仍需逐题对应到有限合同；不能只把可执行的指标部分交给 Runtime，再期待 Gold 将遗漏部分补成 partial。

下一步先审阅合同与修订 Gold，确定每题的引用、缺失码、预期 Verifier 结果及 partial 政策；随后生成正式 Gold/只读输入、Freeze/Seal，并补原生 Host→Worker→Collector 的 Dev 控制与六条真实拒绝配置绑定。当前公开合成测试覆盖评分分支，不等于原生 60 题入口已验收。

最终单独批准精确候选、正式题集/Gold/评分 Hash、供应商、Run/调用/Token/时限及零重试预算后，才允许正式 Live。旧 053 的许可已消费，不能复用。本次新增付费调用为 **0**。

独立消融只准备新 Dev 草稿和协议，见 [独立消融准备](p7-independent-ablation-preparation.md)。
