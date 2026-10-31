# P7 Gate 2B：物化、私有审核支持与非付费验收

本轮最终状态为 **blocked**，未达到 `ready_for_live_authorization`。已完成新隔离环境、数据/文档物化、原服务的非付费回归和 Toy 执行隔离；60 条独立人工审核仍 pending，P3 定义未代为确认，7 条封存输入存在现有接口兼容问题，完整 Live 执行/评分准入仍不满足。

没有运行正式业务 Holdout、付费模型或 Gate 3；没有改业务源码/配方/Verifier/阈值/Worker 行为，也没有修改原 Gold/anchor、旧意图结果或用户 v2.4/v2.5 文档。未提交/推送。原 [准备记录](p7-business-holdout.md) 保持历史，新增实际证据在 [preflight 的 gate2b](research/p7-business-holdout-preflight.json) 和 [本轮冻结清单](research/p7-gate2b-freeze.json)。

## 1. 开始时状态与授权

HEAD 为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`，main；上轮准备工具/文档未提交，v2.4 为已有修改、v2.5 为已有未跟踪文件。开始时先读取 Git 状态；准备器初稿创建后的工作区保全指纹在 `artifacts/p7/gate2b/initial.json`，更早的生产/封存基线继续保留。本轮保留这些修改，不拿旧 CI 当新增代码验收。

Gate 0/1/2 意图 Live 授权均已结束。本次仅授权非付费工程准备、新建隔离环境、摄取冻结合成来源及公开 Toy 验证；不代表人工审核 Gold 或确认 P3 业务定义。用户对审核询问明确回复：**“尚无审核记录，保持 pending”**。

## 2. Gold 审核包

私密文件：

- `artifacts/p7/gate2b/private/human-review.html`：60 条完整问题、必要条件、Gold 预期数值/拒答、原文跨度/Chunk、版本和待审核字段，适合人工阅读。
- 同目录 `human-review.json`：每条 decision=pending、reviewer/time/确认凭据为空，包含定义与 Corpus manifest、分歧列表；没有自动生成 human_approved。
- `human-review-evidence.json`：事实原件定位、事实自身行号与 source/definition hash 的补充检查；不覆盖原 Gold。
- `artifacts/p7/gate2b/review-summary.json`：仅数量、完整性结论和工程问题，不公开答案。

全部 60 条进入清单。SQL 审阅包括收入/MRR、分/元 Decimal、右开窗口、完整空窗口零值、覆盖不足、合同/客户、重订阅/并行合同、零分母与不支持币种/单位。RAG 逐项核对原文事实/行号/身份/来源数量/旧版/时间和注入边界；混合任务分别审查数值与文档，不能把相关背景当因果。实际自动检查了原件 hash、事实跨度、chunk hash 与行号，不能据此称人工审核完成。

原 27 个数值目标/15 条 PG/MCP 证明保留，没有重算或覆盖原 `oracle-proof.json`。本轮只为审核读取 Gold，没有把 Gold 提交给候选、Embedding 或模型。需要注意：自动完整性通过不证明业务 Gold 的全部定义正确，独立人工裁决不可省略。

## 3. 全新 PG17 + pgvector

| 项目 | 本轮实际环境 |
|---|---|
| 容器/Compose 项目 | datapilot-p7b-postgres-1 / datapilot-p7b |
| 数据库/宿主端口 | datapilot_p7b / 127.0.0.1:55440 |
| 独立数据卷 | datapilot-p7b_businessdata |
| 镜像 | 沿用原固定 pgvector 0.8.6-pg17 镜像与 digest |
| 原服务部署 | db-init → migrate → runtime-init → 首次 seed → health |
| Server | PostgreSQL 17.11，pgvector 0.8.6；客户端包版本另存 dependency receipt |
| 网络 | 数据库额外宿主端口网络；候选只加入 internal 网络，无外网路由 |

首次部署因 Docker Desktop 不为 internal 网络发布宿主端口而失败，`db-init` 未成功。仅给新实例增加 hostaccess 网络，保留新卷，再按原服务完成初始化；失败日志/初始化记录保留。没有 down/delete/删除卷路径，也没有重置旧实例。

新实例单独初始 Seed 240 条用于原回归预期；这不是重新 Seed Demo。只读复核 Demo 仍为 240 客户、历史 P7 仍为 48 客户，旧容器仍运行、启动时间未因本轮重启。不同实例使用独立密码和原 12 个角色；grants/只读/无超级用户及无继承检查通过，模型没有新的 DDL/管理工具。

## 4. 数据与索引物化

通过原 `IngestionService.import_file` 导入 **13 个 Dataset 快照 / 12 个逻辑身份**，逐项比对 Dataset UUID、v1/v2、source SHA、confirmation SHA。原 P1 再解析/确认校验与原 P2 事务化发布生效；v1/v2 均可通过指定 scope 的真实 MCP 读取 schema，不把旧版本替换为 current。

该操作仅执行本轮明确授权的合成来源存储和 Schema 配置，不等于独立 Gold 审核或 P3 业务口径批准。**封存集的 Semantic/Metric 确认没有执行**。实测 reviewed=False 被原 Registry 拒绝；不能为了产生期望版本自行传 True。真实 P3 MetricExecution 由独立公开 Toy/原测试验证，没有执行封存目标的 P3 计算。

原 RAG IngestionService 与固定本地 ONNX 实际写入 **4 个 Corpus / 5 个 index snapshot**；旧/新 manifest 与所有 Source/document/chunk/index hash 精确匹配，版本均经原 MCP metadata preflight 可用。摄取的 reviewed=True 表示本轮用户授权这些合成文档进入隔离库，不是自动批准 Gold/指标或文档中的命令。

冻结索引共 **47 条 512 维向量**，原 validate_vectors 的维度/有限值/范数及原 embedding SHA 逐条通过。最初环境检查的数据库总量 134 包含同期公开回归材料；不能将其视为 Holdout 向量数。本轮固定索引核对以 `vectors-integrity.json` 的 47 条为准。没有运行任何封存问题的搜索或按召回结果改阈值。

## 5. 发现的输入契约阻断

原 `rag/storage.py::Repository.manifests` 要求 CorpusPin.document_ids 与所 pin index 的全部 Sources 一致；原封存集中 7 条输入给了文档子集：

`bh2-030 / 033 / 035 / 038 / 040 / 054 / 059`。

这 7 条在原 MCP 实际 preflight 返回 DOCUMENT_NOT_AUTHORIZED，未进入 Worker。不能将权限层拒绝偷换成 Gold 指定的文档不足/正常检索，也不能把它算成业务评测已通过。没有改 `!=` 为子集判断，没有扩权、扩大 pin、换 index 或重写原任务。

另有 5 条故意越权/版本冲突输入在宿主契约或文档授权层被拒绝；它们是预先存在的负例，与上述兼容阻断分别记录。全部 60 条只检查 DTO、ReportScope 与来源环境，**执行数仍为 0**，没有运行全部任务再调实现。

最小后续行动：独立审核确认这 7 条的目标、授权与预期状态；如需适配当前接口，应另行授权构造精确子索引/兼容输入的新封存版本并保留旧包，不能静默修改旧 anchor，也不能在本轮改 MCP/Gold 求通过。

## 6. Runner / Collector / Scorer

`p7_business_runtime.py` 是原 `run_durable` / `inspect_run` 的薄适配：原 Coordinator、Gateway、MCP、P3、ReportService、Journal、Ledger 和 Checkpointer 保持。没有第二套 Planner/恢复状态机/Verifier。当前 CLI **仅接受 gate2b_toy + toy-*，并拒绝 live/key/正式 case**；未来正式 campaign 的受审阅来源/授权接线没有完成，不能把这个防误运行的 Toy CLI 当可直接启动 60 条 Live 的入口。

Collector 在独立容器中获取原 Run lease，调用原 `inspect_run`，重新校验 Manifest、Dataset/Metric/source、任务依赖/能力、Artifact SHA、P3 Evidence/Verification、RAG 和 Report。只采集原 state/calls/events/artifacts/usage，不调用模型，不盲目 resume。可信宿主在容器结束后签署采集包，私钥只在宿主；Scorer 验签并核对 question/scope/source/version/window/unit 后才比较 Gold，不能凭候选输出 `verified` 成功。执行收据的问题 hash 明确使用原 `digest` 的 canonical JSON SHA256；人工审查包里的原始 UTF-8 hash 是单独证据，不混用。真实 Toy 采集包已在隔离评分侧对照公开 300 CNY Gold 通过，未读取正式 Gold。

`p7_business_scoring.py` 目前支持签名/身份、精确数值/单位/窗口/版本/source 对照、必要事实跨度覆盖、独立 rank 原语和 not_run 分母。**拒答原因的语义等价需人工裁决，完整 Chunk/Document/Source 跨查询聚合、批次级成本/置信区间和 Live campaign 驱动尚未完成**。这些是明确的工程未完成项，不能把原语测试冒充完整评分器验收。没有通过增加宽松别名，把所有工具失败变成合法拒答。

独立公开 Toy 的实际链路为：原公开 XLSX → 原导入/已审阅测试定义 → 新容器 Fake 决策 → 原 Durable review interrupt → 测试宿主明确 approve → 真实 MCP/P3 → 原 ReportService → 独立 Collector。该 Toy 输出 300 CNY，原 verified Evidence/Verification 存在；跨新进程 resume 后 Run、报告、P3 ID/hash/verdict、账本和调用总数均一致。没有把 Toy 数字写入任何真实业务结果。

### 文件隔离已实际验证

候选容器非 root（10001）、只读根目录、cap-drop ALL、no-new-privileges；仅挂载原 src、Toy 配置、批准 XLSX、固定模型和单独 runner。镜像中的其他 tests/fixtures 被空目录覆盖，未挂载项目根、Git、Gold、审核包、评分器/私钥、Docker socket。实际进程能读批准配置/源码，不能读 Gold/evaluator/私有审核路径；不是仅依赖 gitignore。

这验证的是**本次 Toy 容器**的有效挂载边界，不是尚未生成的每个正式 case 分发闭包。未来须逐 case 再验证资产分发、配置 hash、撤权和人工审批，不能将 Toy 结论直接外推生产多租户。

## 7. 验收与失败记录

实际结果、JUnit 路径和环境在 [preflight](research/p7-business-holdout-preflight.json)，本轮验证分为：

- 新公开 Toy 契约 16 项：正式 case/key 拒绝、签名篡改、错误问题/scope、单位/source/版本/窗口/verdict、unknown/review/未完成、无数据不报 Live 分数、拒答待裁决、环境隔离、实际执行器的 canonical 问题 hash 接线。
- Python 3.11/3.13 非 PG 最终各 **564 passed、194 deselected**；此前各 563 项为 hash 接线反例加入前的快照，保留在原日志中。
- Python 3.11 原真实 PG 回归 **76 passed / 904.91s**，另有跨来源/版本恢复 **16 passed / 219.41s**；3.13 分别 **76 passed / 902.22s**、**16 passed / 227.99s**，每版本合计 92 个适用用例。原业务源码在这些执行期间保持不变，不引用旧 CI 代替。
- 正式 Holdout 60 条输入/环境检查、13 Dataset、5 index、47 向量；scope 失败明确保留，没有业务执行/质量分数。
- OpenAPI 24 个路径与原 snapshot 完全一致；没有启动 API lifespan 或改 API 契约来通过比对。

原 PG 测试覆盖重复提交只关联原 Run、取消/撤权不能恢复绕过、未知调用保守预算与拒绝重发、预算上限、越权/错误来源/版本拒绝、raw/伪造 verified 拒绝、审批与 API/Worker 实际进程重启。测试均使用新实例和公开 fixtures/Fake/Mock，不能充作 DeepSeek 自主业务效果。

失败历史保留：新实例 internal 网络导致初始化连接失败；7 个原封存输入的真实 preflight 拒绝；独立 Toy 审计最初错误使用字符串 `300 == 300.0000000000000000`，已按原协议改为 Decimal 精确比较，没有修改数值/业务源码/Gold。最后新增的执行器/Scorer 哈希接线反例先 1 failed，再统一为原 canonical digest，16 contracts passed，实际 Toy 采集到评分通过。初次准备 freeze 保留在 `artifacts/p7/gate2b/freeze-initial.json`，修正后生成 revision 2，原业务/Gold anchor 不变。准备期 Ruff 问题已修正，最终检查另记。没有删除负例或把未执行项改成通过。

复现命令（仓库根目录；只针对本轮新环境，已有审核包拒绝覆盖）：

```powershell
uv run --locked pytest tests/test_p7_gate2b.py -q
uv run --locked pytest -m "not integration and not live" -q
uv run --locked ruff check .
uv run --locked ruff format --check --exclude docs/codex-prompts-v2.5.md .
git diff --check
```

原实跑 PG 入口为 `artifacts/p7/gate2b/run-pg.py 311|313`，它先检查新容器/DSN，再将环境传给六个原测试文件；不会指向 Demo/历史 P7。JUnit/日志和命令清单保存在该目录。本轮不清理测试数据、卷或未提交文件，重建/清理需另行授权。

补充入口 `artifacts/p7/gate2b/run-cross-source.py 311|313` 运行原恢复版本测试和五类跨来源测试节点，包括五个独立公开业务案例、跨进程 P3 verdict 保持、跨节点引用、真实篡改与权限/Metric 版本拒绝。它们属于公开 Toy/回归，不是新 60 条 Holdout 的执行。

新增文件用途：`p7_gate2b.py` 负责私有审核包/新实例/原服务物化；`p7_gate2b_validation.py` 仅做元数据/Scope/向量完整性核验；`p7_gate2b_smoke.py` 是公开 Toy 的只读挂载容器启动器；`p7_business_runtime.py` 薄接原 Runtime/Inspector；`p7_business_scoring.py` 是隔离评分原语；`test_p7_gate2b.py` 保留 16 个公开反例/契约。逐文件新增行数与 SHA 见 freeze 的 change_inventory；tracked 文档相对 HEAD 的统计包含上轮未提交准备，另行标明，不能算作本轮业务源码修改。

## 8. 冻结、预算与停止

原 60 条包的 seal 仍为 `7af09ffe2320dfdad3535c55ed89e96124a7fd4bad0d66bc1cc898dbec464ecc`，66 个文件完整性通过；原 116 个生产/依赖/迁移文件、18 个意图冻结文件以及原 PG proof 原字节未变。新工具/测试和证据的 SHA 在 [Gate 2B freeze](research/p7-gate2b-freeze.json)，它是**blocked 准备状态**的审计冻结，不是 Live 授权。

本地配置只做离线校验：deepseek-flash / api.deepseek.com、Key 已配置但未输出，8 calls、18,000 Token/Run、1,200 output/call。原 profile 保持 Thinking disabled、SDK retries=0；没有新建 Live client 或供应商 HTTP 实验。[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)重新核实，支持 Tool Calls 不等于本轮实测能力。

未来提案仍为 [未授权 Live plan](research/p7-business-holdout-live-plan.json)，本轮只补充 [预算/配置复核](research/p7-gate2b-budget.json)：三路径各 20 Run、各最多 160 calls / 360,000 Token，合计 60 / 480 / 1,080,000，并发 1。每路径按最满输出/输入均 cache-miss，费用规划约 USD 0.1404 非高峰 / 0.2808 高峰，三路径合计 0.4212 / 0.8424；更宽松的所有 Token 均按最高费率为 0.648 / 1.296。未知 usage/缓存、价格/模型别名变动和审批准备成本需单列，不是账单/硬费用上限或稳定成功率。

停止条件：越权/源 hash/版本变化、预算不足、任何 issued/uncertain、采集签名或原 Verifier 失败立即停止，不缩分母、扩大授权、清零预算或自动重跑。未知供应商结果走原 RECOVERY_UNCERTAIN，需人工对账；回滚只意味着保留隔离现场和阻断后续执行，不恢复旧授权、不删除/重建原数据。

必须补齐后才能再次申请 Live：

1. 独立审核人完成 60 条记录（含身份、时间、确认凭据与分歧处理），再通过原 Registry 确认对应 P3 版本；不能用本轮任务授权代替签字。
2. 决定 7 条输入兼容问题的处理，必要时独立授权新封存版本；原版本不改。
3. 完成并冻结正式 campaign 的逐 case 受审阅授权/分发、拒答裁决协议和全量评分/成本聚合，再用独立 Toy 验证。当前薄适配和原语测试不足以宣称这项完成。
4. 明确批准正式端点、来源闭包、模型/profile、调用/Token/费用提案及未知结果停止规则；旧 Gate 0/1/2 额度不得沿用。

本轮到此停止。真实 DeepSeek 业务评测为 not_run；不自动进入 Gate 3、提交或推送。
