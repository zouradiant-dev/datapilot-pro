# P7 工程候选交付索引

这是 GitHub 可阅读的公开摘要。历史原件、签名采集包、凭据、模型权重、数据库和原始 Trace 留在本地，不随本候选分支上传。

| 维度 | 状态 |
|---|---|
| Engineering Demo Candidate | **ACCEPTED**，限定本地单用户、公开合成数据、脚本 Worker |
| Independent Business Quality | **PASS**，2026-11-07 的 455 文件 v4 候选 |
| DeepSeek Live Gate | **PASS**，正式 48k 批次严格 60/60、业务 60/60，边界均 42/42 |
| P7 本地交付 | **已收尾**。工程修复候选另有 94 项本地定向集成证据 |
| GitHub 发布 CI | **PASS**，提交 `23c44c7` 的 Python 3.11 和 3.13 均通过。[Actions 运行](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/42354878566) |
| 独立消融 | **已暂停**。零付费控制留档 |
| 独立人工合同语义审查 | **NOT_VERIFIED** |

2026-11-07 的 455 文件 v4 正式业务验收、后续 Git 发布 CI 与下文早期冻结工程 Demo 分别列报。冻结副本中的 PENDING 属于当时状态。[正式验收与交付记录](../../research/p7-formal60-48k-acceptance.md)

## 工程与 Demo

- [工程冻结公开副本](frozen/p7-engineering-freeze.md)：Goal v4、可信范围确认、P3/Citation、原 Journal/Ledger/Durable；BGE 默认，Qwen 可选，架构不重建。
- [Demo 验收公开副本](frozen/p7-demo-acceptance.md)：五个新 Run、七项工程控制，三 completed、一 unavailable、一 blocked；1432.25 CNY。
- [冻结后 Backlog](frozen/p7-post-freeze-backlog.md)：四类过拒、日期控件、独立质量与资源补验。
- [机器可读 Demo 摘要](demo-summary.json)、[公开副本溯源](publication-provenance.json)。原件 Hash 与语义结论保留，公开副本仅替换本机路径及 local-only 引用。
- [Git 整理记录](../../research/p7-git-consolidation.md)、[历史文档 local-only/缺失链接清单](local-only-links.json)。旧报告是当时的快照，不把其本地证据链接当作 GitHub 可访问文件。

运行链：Streamlit → FastAPI → 原 Outbox/Journal 独立审批 → LangGraph → MCP → SQL/P3 或真实 BGE/pgvector → 原 Report/Inspector。Demo 决策使用 Fake/脚本，不宣传为真实 DeepSeek 自主决策；unknown-outcome 不重发，撤回后旧报告403。

## 源码与恢复身份

产品源码树 SHA256 为 `5a11a01af573c7ee456f2fac7946051f1ce829fe9eba2ba8624370f6c4d7f3a1`；工程结果 Seal SHA256 为 `50f0c25699b7f51a4c70ba1d95f395873cf4765e95ba9e4014c48893728f80ec`。历史 HEAD 是 `f8b122438d2c67ab26e618ecded72ecc18454015`，当时尚未提交；本次新 Commit 映射另记，不能回写历史 Freeze。

[源码逐文件映射](source-freeze-mapping.json) 绑定实际产品 Commit、原始工作区字节 Hash 和 Git blob Hash。既有 Git 换行归一化使10个文件的字节 Hash 不同，但111个源文件的归一化内容全部精确相同；原工作区和旧 Freeze 未改。需要复核原 Windows 字节时，只能在独立导出副本按清单恢复对应 EOL，再计算 Hash，不能改写历史 Run。

Goal v4 的范围确认与业务事实验证、执行审批分离。旧 v3/未绑定 RAG Run 不被静默迁移，不兼容恢复保持 RECOVERY_IDENTITY；SQL-only/P3 继续原兼容规则。合同确认不能解除全集、快照、因果、权限或证据守卫。

## 历史结论与未通过项

- Phase 2C.7：24条技术合同观察20/24；有限目标4/15过拒；不是独立语义质量成绩。[交接公开副本](frozen/p7-goal-confirmation-quality-handoff.md)。
- Qwen Web 控制因 RAM 低于3 GiB准入要求失败，补验未完成；不把旧 Linux/CUDA 生命周期通过冒称最新 Web 链通过。[生命周期交接公开副本](frozen/p7-qwen3-lifecycle-handoff.md)。
- [Pilot 聚合](p7-qwen3-phase2c-business-quality.summary.json)、[2C.2 聚合](p7-qwen3-phase2c2-expanded-quality.summary.json)、[2C.4 聚合](p7-qwen3-phase2c4-fresh-validation.summary.json) 由历史原件白名单字段提取，排除大型逐 Run 原始明细。STOP、失败和 not_run 均保留；没有重评分或补跑。
- 全部真实 PG/MCP/浏览器原始日志和私密签名包为 local-only；公开 Hash 可标识原件，但不能替代独立审计者访问原件。未声称全面安全审计、生产多租户、SLA 或总体语义安全。

## 运行与验证

本地配置与常规启动见[根 README](../../../README.md)、[RAG 部署](../../rag-pipeline.md)、[恢复协议](../../recovery.md)、[Goal v4 ADR](../../adr/0018-trusted-goal-scope.md)、[Web 确认 ADR](../../adr/0019-web-goal-confirmation.md)。新机器需要锁定环境、固定 BGE 模型缓存和隔离数据库角色；历史 Demo 的私密环境不能直接复制，过期确认不能延长复用。不要重跑原 unknown 或任何 STOP 实验。

GitHub 发布 CI 覆盖 CPU／固定 BGE、真实 PostgreSQL／MCP 与 Fake／HTTP Mock。真实模型和 CUDA 的验证范围单列。[远端 CI 证据](../../research/p7-formal60-48k-acceptance.md#远端-ci)
