# LangGraph Fork：后续独立研究计划

状态：**尚未创建 Fork，尚无必须修改 Runtime 内核的已确认问题**。本轮建立原版基线与问题验证方法；后续另行开展研究，不能挤占 SaaS 经营分析主线。

## 1. 原版基线

- 官方 tag：`1.2.16`，提交 `41c9c22fdc83d68a2859d0c9a2b627c8615a792f`。
- 实际安装：Python 3.11.16、LangGraph 1.2.16、langgraph-checkpoint 4.3.0；7 个关键文件与 tag 一致。
- 本项目原创建模探针：[langgraph_baseline.py](research/langgraph_baseline.py)。没有复制上游 Runtime 代码，没有使用模型、MCP 或数据库。
- 实际结果：[langgraph-baseline-results.json](research/langgraph-baseline-results.json)。时间字段为 UTC，本地研究日期为 2026-10-21（Asia/Shanghai）。

| 探针 | 实际观察 | 解释边界 |
|---|---|---|
| Send + Command | 两任务结果 a=4、b=6，Worker 只收到 task_id/value；完成状态正确 | 验证小规模输入切片与汇合，不是完整任务调度器测试 |
| interrupt 恢复 | 节点入口执行 2 次，批准值后继续 | 证明中断前逻辑重放，未验证真实审批身份 |
| 并发局部失败恢复 | 成功 left 执行 1 次，失败 right 共执行 2 次 | 验证 pending writes 复用，不是外部请求 exactly-once |
| 子图恢复 | prepare 执行 1 次，失败 tool 执行 2 次 | 验证继承父 checkpointer 后的子节点恢复 |
| Command 与静态边 | dynamic 和 static 均执行 | goto 不覆盖静态边；这是建图约束，不是内核故障 |

当前 **5/5 通过**，使用 InMemorySaver、同一进程中的可控异常。没有测量性能、进程强杀、PostgreSQL Saver 或远程故障。没有运行上游全量测试，没有真实模型效果或成本结论。

复现（仓库根目录 PowerShell，依赖已按 uv.lock 安装）：

```powershell
$env:PYTHONUTF8 = '1'
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
.\.venv\Scripts\python.exe docs/research/langgraph_baseline.py
```

传入 `--output <本地结果路径>` 可保存这次真实运行的 JSON。脚本在版本不同于 1.2.16 时拒绝执行，升级应先审查基线而非静默覆盖。勿使用 Python `-O`，探针用 assert 校验不变量。

## 2. 候选问题与可证伪假设

下表是待研究假设，不是已发现缺陷，也不预先承诺要修改对应文件。

| 候选问题 | 业务触发场景 | 先用原版验证/解决 | 只有证实后才定位的内部位置 |
|---|---|---|---|
| 大量分群任务的并发公平性/内存 | 同一分析拆分很多客户群体 | Send、max_concurrency、批次、ArtifactRef，测队列等待与峰值内存 | PregelRunner / loop / channel 写入 |
| 取消后工具和模型仍有残留执行 | 用户停止一项耗时分析 | async 取消、工具 timeout、驱动清理、Provider SDK 行为分层观测 | runner/retry 的取消传播；先排除工具/SDK 问题 |
| 崩溃窗口的重复模型成本 | 请求发出但结果尚未落盘 | 小节点/子图、持久预算预留、幂等 ID、官方 PG Saver | checkpoint 写入边界；不假定 Runtime 能控制供应商计费 |
| 大型中间结果拖慢检查点 | 月度使用事件与图表数据量大 | 产物外置、最小 State、自定义公开序列化/存储扩展 | checkpoint/channel 序列化路径 |
| 并发子图暂停与恢复定位困难 | 多项需要人工确认的业务动作 | 独立 thread/task ID、interrupt ID、Command resume 映射、可信审批服务 | 子图 namespace / interrupt 匹配，仅在公开机制不满足时分析 |

业务 DAG 合法性、SQL 权限、Token 预算、引用校验、迁移所有权，优先由业务 Harness 和部署层解决；它们不是 Fork 内核的理由。

## 3. 可复现实验方法

1. 固定同一 Python、锁文件、官方提交、机器资源和配置；记录环境及实际命令，不混用 main 与已发布包。
2. 使用固定随机种子的合成任务/产物：任务数 1/10/100/500、不同依赖深度、同等大小的引用与原文状态；故障点在模型前、工具后、结果持久化前。参数是实验输入，不是性能承诺。
3. 先测无外部 API 的受控异步工具，避免供应商波动掩盖 Runtime 行为；再独立进行真实 MCP/PG、进程重启测试。模型效果评测另列，保留 Fake/真实模型标签。
4. 记录完成结果一致性、各任务执行次数、成功任务重放数、检查点大小、峰值内存、p50/p95 时延、取消延迟、预算预留/结算差额。重复次数和业务 SLO 在实施前由用户确认，不能凭一轮小样本推断趋势。
5. 先比较公开 API 配置、节点粒度、子图、官方 Saver 的改善；保留原始 Trace、失败复现和未通过项。不以覆盖错误或删除数据换取通过。

运行 PostgreSQL Saver 实验前须先解决 [迁移冲突](framework-research.md)，并安装/锁定适配器；当前只读业务连接不能兼作元数据写入连接。失败实验不能操作现有业务卷或自动清库。

## 4. 创建 Fork 的门槛

必须先具备以下证据，才提出具体 Fork 方案：

- 一个可在固定官方版本稳定复现的具体问题，附业务影响、输入、预期/实际结果和独立最小脚本。
- 公开扩展点、子图设计、资源限制和适配器方案已验证且不足，排除自定义 reducer、SDK、数据库权限或部署配置错误。
- 确认需要修改的源文件/函数、原版回归测试、最小补丁范围和回退方式；不先大规模改写 Runtime。
- 与上游 Issue/修复协作的方案、升级合并成本、兼容性矩阵和维护责任。业务代码通过薄适配层依赖修改，避免散布私有 API。
- 完整许可证/版权归属，保留原版基线、补丁前后同工作负载结果。任何性能改进必须有可复现实测。

满足门槛后再让用户决定是否建立独立研究仓库/任务，以及明确要修改的机制。当前仓库继续使用原版锁定依赖。
