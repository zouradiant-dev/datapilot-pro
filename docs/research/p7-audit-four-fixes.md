# P7 四项审计修复与零付费工程验收

日期：2026-11-05。负责人明确授权修复审计发现的四项问题。本轮四项均已完成；新增 Provider 调用为 0，没有重跑已冻结的 009/010，没有修改 Gold 或评分器，没有提交或推送。

## 四项修复

1. **摘要预算原子预留。** Gateway 始终一次性预留摘要及最大合法 follow-up，移除延后申请后续预算的分支。预算不足时在摘要派发前失败；已发出未知请求仍按原规则结算。新增顺序边界及竞争 Worker 回归，证明不会先花摘要调用再丢失后续预算。
2. **协议消费者一致。** benchmark 校准器、HTTP Mock、benchmark 决策双及跨进程恢复探针统一 decisions-only 输出；模型不返回或覆盖宿主权威字段。之前两项 L4 benchmark 和一项异步 HTTP 失败已消除。
3. **决策数量边界。** 使用 ContextSummary 的实际模型验证接纳决策，保留唯一性及已有 ID 校验。八项允许、九项明确拒绝；拒绝后释放已证明未发出的 follow-up，保留摘要已发生 usage。
4. **同一候选及实际 PG/MCP 准入。** 当前入口改指向本轮另建的 444 文件候选及新工程 Seal，旧 v12/v14 不改。真实 PG17/pgvector/MCP、只读角色与拒绝写 SQL、L4 摘要到后续请求及原 Verifier 的链路已实际验证。

## 验证

| 检查 | Python 3.11 | Python 3.13 |
|---|---:|---:|
| 完整非集成 | 1500 passed | 1500 passed |
| 真实隔离 PG/MCP 上下文准入及 RAG 发布/持久化/签名回归 | 13 passed | 13 passed |

固定镜像 `sha256:6c78a77b7ca5604bf4ac4ff8e725bc72370d550aef6c9c5b545eb27b8fa87339` 内另有四项直接控制通过，实际 Python 3.11.14；只读源文件 SHA 与新源码匹配。它验证了真实数据库角色无业务写权限、MCP 拒绝 DELETE、L4 Summary→Follow-up→Verifier、预算不足零派发以及父子 Ledger 守恒。实际主控制保持 8 次/18,000 Token、Worker 4 次、输出上限 1,200，默认生产预算没有增加。

运行镜像没有 pytest：首次仅在导入测试运行器时停止，保留日志；随后使用独立脚本直接调用原 Runtime/MCP 完成真实容器验收，没有安装依赖或更换镜像。双版本 pytest 在原锁定环境执行。

本轮 20 份 RAG 原生签名记录均按原评分器精确复现，含 16 个严格正例和 4 个预期严格失败的负例；13 项工程断言不能当业务通过率。Ruff、CI 范围格式和 diff 空白检查通过。新 PG 测试首轮的元数据查询方式与 schema/context 引用区分问题已修正，早期失败 JUnit 保留，最终结果来自后续通过的记录。

## 新候选身份

- 路径：`artifacts/p7/audit-four-fixes-20261105/candidate-final`
- 文件：444（新增一份公开合成真实 PG/MCP 验收测试）
- Manifest canonical SHA256：`6d8c79a6bfcecc7e199714ec8c61ecb5ee2c70fe7d97d49e6b11720f6871765b`
- 工程状态：ENGINEERING_VERIFIED_LIVE_NOT_AUTHORIZED
- 候选 Manifest 本身仍为 PREPARED_NOT_AUTHORIZED，不等于付费 Permit。

容器验证使用先行测试快照；最终快照与它只有 README.md 的验收状态入口不同，全部 Runtime、依赖、脚本、测试与 fixture 字节完全一致。原 README/AGENTS/current-status/最终冻结入口等八份原件保存在本轮 entry-originals，以原哈希核对；当前源码与最终快照逐文件一致。

## 历史和下一阶段边界

原 433/437/443、v12/v14 快照、原工程冻结记录、旧合同/Gold/Seal/STOP 和已签名结果保留。原 60 题 51/60、修复 Dev 的 8 strict／1 blocked／1 not_run 不改；旧 009/010 不重跑。已有 133 个正式结果文件逐一哈希一致，历史评分实现未变。

测试仅使用 55453 专用合成库，追加的是公开合成 RAG fixture/测试 Run；SQL 主控制和角色核验为只读，没有迁移、重置、重建或写入 55450。测试库恢复至本轮开始时的 **running** 状态并保留卷。没有新增付费许可或正式题包采用。

本轮没有重跑远端 CI 或全量数据库集成矩阵，也没有测量新的真实模型业务效果。工程修复完成后，正式 Live 仍须先绑定具体题目、合同、Gold、来源、候选、评分和新 Seal，再单独决定付费授权。此前仅列预算的 60 题请求保留为历史草案；不能用它跳过题包准入，也不把已用于修复的旧集合重新称作未见过的独立 Holdout。
