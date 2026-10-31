> 公开脱敏副本。历史原件 `docs/research/p7-engineering-freeze.md` 保持不变、仅本地保留。
> 原件 SHA256：`3fd940f6bbed7dc98821eebc850433f1f1e6db2f05d887ea49aefc0aef1917b7`。仅替换本机路径和不可公开工件链接，历史结论/分数不变。

# P7 工程候选版本冻结

记录日期：2026-10-31。Freeze：`p7-engineering-candidate-v1`。

**Engineering Demo Candidate: ACCEPTED**，仅限本文和 [Demo 验收](p7-demo-acceptance.md) 的可信本地单用户、BGE、合成数据、脚本 Worker 路径。

**Independent Business Quality: PENDING**。**DeepSeek Live Gate: PENDING**。本次不是独立质量评测、真实模型准入或生产发布。

## 冻结身份与改动范围

| 项目 | 冻结值 |
|---|---|
| 分支 | `p7-ci-verification-20261028` |
| HEAD | `f8b122438d2c67ab26e618ecded72ecc18454015` |
| 当前产品源码树 SHA256 | `5a11a01af573c7ee456f2fac7946051f1ce829fe9eba2ba8624370f6c4d7f3a1` |
| Phase 2C.7 父结果 Seal SHA256 | `96a1bf9aea4afdba893b02bc6098297377beaf68a58288b9e251c733346585d2` |
| Goal 语义 | `host-goal-requirements-v4`，原 Trusted Scope Attestation |
| 默认 Embedding | 原 BGE 512；原模型、0.55、Top-k 与预算未改 |
| 数据库 | 新隔离库 `datapilot_test_engineering_demo_v1_20261031`，真实 PG17/pgvector，迁移 `0008` |

这是**内容 Hash 标识的未提交工作区候选版**，不能从上述 HEAD 单独检出全部候选内容。完整逐文件 Hash 在 engineering-freeze.json（local-only：`artifacts/p7/engineering-demo-v1/engineering-freeze.json`；原件不上传），驱动与公开数据在 harness-freeze.json（local-only：`artifacts/p7/engineering-demo-v1/harness-freeze.json`；原件不上传）。最终文档、日志和结果另由 result-seal.json（local-only：`artifacts/p7/engineering-demo-v1/result-seal.json`；原件不上传） 封存；没有 commit/push 或远端 CI。

本次及中断的 Phase 2C.8 没有修改产品源码、原测试、迁移、依赖或规划文档。原先大量未提交修改完整保留，不能把当前相对 HEAD 的全部 Diff 归为本轮新增。最终受 Git 跟踪的 Diff 与本轮开始逐字一致；记录见 final-source-integrity.json（local-only：`artifacts/p7/engineering-demo-v1/final-source-integrity.json`；原件不上传） 和同目录 `git-status-before.txt`、`git-status-final.txt`、`git-diff-before.patch`、`git-diff-final.patch`。

本轮仓库可见新增项：

- [scripts/p7_engineering_demo.py](../../../../scripts/p7_engineering_demo.py)：薄 HTTP/原 Outbox 工程驱动，调用原 `execute_one/run_durable`、Inspector 和受控 MCP；不是第二套 Scheduler、Verifier 或恢复系统。
- [公开 Demo 夹具](../../../../tests/fixtures/demo/engineering-v1/plan.json)、[CSV](../../../../tests/fixtures/demo/engineering-v1/invoices.csv)、[Markdown 文档](../../../../tests/fixtures/demo/engineering-v1/billing-guide.md)：先固定输入、1432.25 CNY Gold 和停止条件，最多五个 Run。
- 本轮三份交付文档。忽略目录 `artifacts/p7/engineering-demo-v1/` 另保留初始化、只读核对、日志和签名包；没有为 Demo 新增产品状态字段、数据迁移或 Agent 工具。

## 保持的架构与安全条件

外层仍为 LangGraph，Worker 使用原 Gateway/ToolRegistry/MCP。SQL 数字仅经受审查 P3 配方与六层验证发布；RAG 仍验证 Scope、Source/Document/IndexVersion、Chunk/跨度/Hash、事实及完成资格。用户范围确认是服务器版本和合同 Hash 绑定的事件，随后仍需独立 Journal 执行审批；脚本不直接写 confirmed/verified。SQL-only 复用已确认 Registry，不虚构文档确认。

Streamlit 仍只调用 FastAPI。新环境沿用原隔离数据库身份和只读 MCP，不向 Worker 提供管理员/Registry 写入或任意 DDL。新库执行原初始化、迁移、runtime-init，无 Seed；未修改现有数据库、全局角色、Docker Volume 或历史记录。

模型决策是显式 `Fake/ReportDecisions`，真实 Embedding、数据库、SQL、检索、P3、Report、Journal、Ledger 和 Checkpoint 实际执行。`dispatch=False`，薄驱动只对明确待办的原 Outbox 命令执行一次。合成审批由自动化工程测试角色完成，不是项目负责人逐条业务审批，更不是独立人工语义签署。真实 Provider 请求、Token 和付费均为 0。

Qwen 1024、CPU/CUDA Profile、独立环境及历史索引实现保留，未改为默认、未删除、未在本轮加载。原 Qwen 资源失败仍是未完成补验，详见 [Backlog](p7-post-freeze-backlog.md)。

## 版本、恢复与历史保护

新 RAG Run 使用 Goal v4 和已有合同确认契约；Manifest/Receipt 的可信身份由原 Inspector 核对。旧 v3 或缺少当前可信范围绑定的 RAG Run 不被静默迁移/重新解释，不兼容恢复保持 `RECOVERY_IDENTITY`；SQL/P3 无关路径沿用原兼容规则。新语义不能追溯改变旧 Report、Hash 或分数。

最终按已有有限 Manifest 核验：

- 264 个源码、测试、迁移、锁及输入文件，6 个驱动/夹具文件：无漂移。
- Phase 2C.7 父 Seal 的 128 文件与 Phase 2C.6 的 99 文件：全部匹配。
- 历史 2222 个唯一路径：2218 个匹配原 Hash；另外 4 个是先前已批准且与本轮起始 Freeze 相同的版本差异，无新增差异。逐项名单、历史 Seal 及 Gold/Seal/STOP Hash 在最终完整性 JSON 中。
- Phase 2C.4 的 STOP、21/200 observed、179 not_run，以及 Phase 2C.2 的 75/200 observed、125 not_run 均保留；不续跑、不合并。原 Gate 2B 31/60、Scorer v1 25/31、v2 26/31、61 次调用/77,897 Token 属于历史实验，不是本次结果。
- 原 Gold、Scorer、Seal 和失败记录未改。历史数据库没有写入；文件 Hash 不是数据库全量审计的替代。本次数据库不变性证据限新 Demo 的具体 Run/引用和原 Inspector 检查。

## 验证范围与停止状态

本轮仅新增五个合成 Run，覆盖七项工程控制。完整结果、P3 引用、重启、撤回、unknown-outcome 和真实测试命令见 [Demo 验收](p7-demo-acceptance.md)。Python 3.11/3.13 各 3 项最终定向契约通过；原产品源码与前轮双版本各 81 项、PG 8/3 项基线相同，未重复运行全量回归。

本轮全量 pytest、Linux/Docker/远端 CI、Qwen 资源补验、独立人工语义审查、新质量 A/B、DeepSeek Live 和 Gate 3 均未执行。不把历史通过记录改写成本轮新测；原未通过的质量 Gate 保持未通过。

验收结束已停止本轮专用 8029/8529 API/UI 自有进程；所有数据库、报告、故障、预算和采集包保留。后续工作按 [优先级清单](p7-post-freeze-backlog.md) 另行授权，本轮停止。
