# P7 当前候选与验收进度

日期：2026-11-04，Asia/Singapore。分支 `p7-engineering-candidate-v1`，已提交基线 `2628b61`，叠加保留的工程修复与本轮候选整合。该 HEAD 的历史 CI 不覆盖当前工作区。

## 本轮推进约定

按“候选整合 → 完整工程回归 → 053 与业务证据补齐 → P7 验收”推进。不把等待完整 CI 全绿作为所有下一项准备的前置条件；源码、合同、授权、未知调用和付费预算仍分别核对。

负责人后续明确：新 60 题正式 Live、独立消融实验准备留到本轮收口后再讨论。本轮继续完成已授权的 053 单题和已经启动的工程验证。

新 60 题使用补齐工程缺口后的候选：宿主范围确认、独立文档事实及跨 Dataset 检查、部分证据发布、共享事件循环和异常诊断修复都在新源码身份中。批次评分绑定 `p7-current-partial-evidence-v3` 及其 v2/冻结基础评分依赖；只有宿主合同显式启用 `partial-facts-v1` 时，部分证据规则才生效。缺失事实仍未验证，insufficient 不能冒充 RAG complete 或整体 completed。

## 三组业务证据与消融

| 集合 | 当前已知状态 | 下一项 |
|---|---|---|
| 旧 Gate 2B 60 | 原首次 Live 31 observed、29 not_run；原 v1 25/31、离线 v2 26/31 | 保留历史，不续跑旧 Campaign |
| Final 50 的十题修复回归 | 原十题 Live 严格 9/10；053 随后在当前候选及 v3 下新单题严格通过，partial，4 calls／7139 Token | 本次单题已 STOP；原 9/10 保留 |
| 新业务 Holdout 60 | `g2-bh-*`；SQL/RAG/组合各 20，另有 14 故障探针；revision-01 保留 49、修订 11，新 Gold review PENDING | 当前源码与 v3 评分绑定、可信合同审阅、正式准入 |
| 消融 | 使用独立新题，与新 60 题分开出题、分开封存；完整六组 Runner 尚未验收 | 明确可安全运行的对照、任务和预算 |

新 60 题的既有材料保存在忽略的 `artifacts/p7/g2-business-60-private/`，没有把问题或 Gold 加入公共代码或候选运行输入。本轮在当前源码下只读复验已有专用库：54 条 pins verified pending launch binding、6 条 negative control passed。来源实际已存在于 55450 专用实例，旧封面“未物化”不能代替当前观察；本轮没有写入这些来源，也没有将来源预检写成 60 条业务通过。

Final 50 另有七题缺执行证据（071、072、073、074、076、078、079）及八题历史不确定（020、037、038、050、057、058、070、075）。旧未知调用不自动重发，不与新 Holdout 混合计算质量。

## 当前工程整合

- 默认 pytest 收集 `tests` 和 `evaluation/p7_v3_current`。评测测试改用公开合成绑定、隔离临时文件和本地 HTTP，不再读取私密题库、数据库凭据或旧 Campaign。
- `current_binding` 在显式执行/验证时才读取旧 Manifest。历史 Freeze 的校验保留，当前源码仍不能套用旧绑定继续执行。
- `candidate_binding` 为新候选保存完整公开源码/依赖/测试快照、raw SHA256 和两个评分版本的文件身份；创建拒绝覆盖，验证拒绝源码、快照及 Manifest 漂移。
- `holdout_preparation` 将新 60 条修订草稿绑定到当前候选及 v3 评分。40 条文档合同仍需逐题审阅部分证据政策，不自动确认 Goal、登记 P3 或派发 Worker。
- CI 测试数量由实际 collection 生成，替代过期的 1748 固定声明；依赖、双版本、真实 PG/MCP、JUnit、覆盖率及 opt-in 边界保留。
- 本地 handoff 压缩包被明确忽略，私密交付与代码分开保存。

最终工程打包为 425 文件候选，Manifest SHA256 `cdb520d5f97ba1159e6345b69690335a109411df762e882162a5228e3b992974`。补齐了 README、公开 JSONL 和意图清单，直接在该快照上运行双版本非集成测试，各 1420 passed。

053 已执行的 421 文件候选保持原件；后续只修改打包工具与其测试、增加上述公开验证输入。业务源码、Worker、评分器及评分依赖与 053 执行时逐文件 Hash 相同，不将旧 Run 改签为新打包版本。

## 验证与执行边界

本轮本地证据写入 `artifacts/p7/current-candidate-integration-20261104/`，最终结果另见同目录交付记录。新建独立 PG17/pgvector：3.11 使用 `datapilot-p7-candidate-20261104`／55451，3.13 使用另一实例 `datapilot-p7-candidate-20261104-py313`／55452，均为 `datapilot_test_` 前缀的新数据库；不在同一 PG 实例并发做故障测试，不重置历史实例或卷。

双版本非集成各 1420 passed；不含本地私密工件的公开副本 1420 passed；Ruff 与 format 通过。当前计划由实际 collection 得到 1828 = 1420 非集成 + 408 集成。

首次 3.11 集成回归为 123 passed、62 skipped、223 setup errors，错误均指向 Windows 系统 Temp ACL。首轮日志与 JUnit 保留；专属临时目录对原 223 个身份精确复验，得到 222 passed、1 CUDA opt-in skip、0 failed/errors。两批合并完整覆盖 408 个身份，最终 345 passed／63 合法 skip；不冒称一次干净全量运行。

3.13 独立实例一次完成完整 408 项：345 passed／63 合法 skip、0 failed/errors。两版本集成身份集合完全一致，跳过均为 Qwen/CUDA 62 项及 Live opt-in 1 项。本轮工程验证已收口，详见 [最终整合与本地验证](research/p7-current-candidate-integration.md)。两套新建测试容器已停止，卷和证据保留，历史实例未停止。

当前完整远端 CI 仍 NOT_RUN，未提交或推送。唯一新增付费执行为已结束的 053：4 次调用／7139 Token，unknown=false。

旧冻结 Manifest、Gold、Seal、STOP 和历史分数保持原件。候选准备不等于生效 Permit；业务补验与新 Holdout Live 按各自精确合同和预算独立准入。

相关记录：[本轮最终交付](research/p7-current-candidate-integration.md)、[十题 Live](research/p7-final50-ten-live-results.md)、[053 修复](research/p7-053-partial-evidence-repair.md)、[当前候选 053 Live](research/p7-053-current-candidate-live-results.md)、[Final 50 对账](research/p7-final50-reconciliation.md)。原始检查与本地证据目录为 local-only，不随 Git 上传。
