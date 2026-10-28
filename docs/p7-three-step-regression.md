# P7 三步修复联合回归

**结论：本机工程联合回归通过，保留质量和发布限制。** 两版均完成 1,141 个唯一测试身份：环境修正复验后各 **1,140 passed / 1 paid-Live skipped**。不是首轮零失败，也不是正式业务 Benchmark 或干净 CI 通过。英文控制仍错误空召回；不建议默认启用新策略，提交前需处理测试环境可移植性。

本轮依据用户“进行第一步”，执行上一轮建议中的联合回归与发布准备。联合对象为 `partial-facts-v1`、`required-supplement-v1` 和 `original-first-v1`。本记录补充三个阶段的历史交付记录，不覆盖其原始测试、失败、封存或质量结论。

只做现有实现验收与记录。本轮没有修改产品源码、测试、依赖、迁移、权限、Gold、Scorer、Prompt、检索阈值或策略默认值；没有付费模型请求、历史 Holdout 重跑、正式新 Live Freeze/Permit、Git 提交推送或 Gate 3。

## 源码与范围

HEAD 为 `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`。开始时已有大量未提交的 P7 工作，完整 Git Diff 不能当成本轮增量。开始前另存工作区状态及 2,090 份文件 SHA；真实隔离实例的 85,630 条既存记录逐行 Hash 用于结束后的只读核对。原 `v2.4/v2.5` 规划文件也在保护范围内。

现有联合用例已实际同时设置三个策略，无需另建测试框架：`test_original_query_postgres.py` 的 cp09 验证必需与补充引用及终态复用，cp07 验证真实 P3 指标、insufficient 文档收据、补充引述、partial 与恢复一致。提交前后、模型响应后及第二次搜索后的跨进程切点沿用原 Journal/Saver/Ledger。

| 不变量 | 现有验证位置 |
|---|---|
| 首次实际 query 必须等于宿主 DocumentGoal，保留 AI/tool ID 与参数 | `test_original_query_policy.py`、`test_original_query_postgres.py` |
| 补充引用不能填补必需事实、必需来源数、数值或因果缺口 | `test_citation_policy.py`、`test_citation_policy_postgres.py` |
| insufficient 可以保留已证明的部分事实，不能改成完成收据 | `test_partial_evidence_report.py`、`test_partial_evidence_postgres.py` |
| P3 Evidence/Verification/hash/verdict、已提交调用和预算恢复不变 | 原跨来源、恢复、Context、Web 集成及上述联合用例 |
| 旧策略 Hash 兼容，跨策略/权限/版本恢复失败关闭 | 三个阶段的政策冲突、权限撤回、Journal 冲突用例 |
| unknown-outcome 保留预留且禁止自动重发 | 原恢复、HTTP SDK Mock 故障与三步专门反例 |

## 测试环境与命令

Windows 原生 Python 3.11 / 3.13，复用锁定依赖。真实数据面仅使用已存在、经过精确 Docker 身份/标签/DSN 检查的 `datapilot-p7-unified-postgres-1`，PG17 + pgvector，端口 55441；不操作用户的 `datapilot-pro-postgres-1`。本地 Embedding 使用原固定 BGE/ONNX/tokenizer，阈值 0.55、Top-k 和两次搜索限制不改。

`artifacts/p7/three-step-regression-v1/run_pg.py` 是本轮私密测试启动适配：复用既有隔离守卫，清除继承的数据库/模型配置，再只注入隔离角色、Fake、空 API Key 和 Live 禁用标志；将旧测试的宿主隔离辅助函数绑定至已核验的同一实例。它不修改 Runtime 或模型权限，没有新的 Scheduler/恢复机制。SDK 故障测试的 HTTP 请求被 MockTransport 拦截；不能当真实 DeepSeek。

```powershell
$env:PYTHONUTF8='1'
$env:DATAPILOT_LLM_MODE='fake'
$env:DATAPILOT_API_KEY=''
$env:DATAPILOT_RUN_LIVE_TESTS='0'
$env:DATAPILOT_RUN_DB_TESTS='0'
.venv\Scripts\python.exe -m pytest -m "not integration and not live" -q -p no:cacheprovider --junitxml=artifacts/p7/three-step-regression-v1/unit-311.xml
.venv\Scripts\python.exe artifacts/p7/three-step-regression-v1/run_pg.py -m integration -q -p no:cacheprovider --basetemp=artifacts/p7/three-step-regression-v1/tmp-311 --junitxml=artifacts/p7/three-step-regression-v1/pg-311.xml
# 保留上述首轮结果，仅复验环境绑定有问题的现有用例：
.venv\Scripts\python.exe artifacts/p7/three-step-regression-v1/run_pg.py --fresh-fact-fixture tests/test_document_fact_postgres.py tests/test_phase4_postgres.py -q -p no:cacheprovider --junitxml=artifacts/p7/three-step-regression-v1/fixture-pg-311.xml
.venv\Scripts\python.exe artifacts/p7/three-step-regression-v1/run_pg.py tests/test_p7_smoke.py::test_original_durable_campaign_ledger_survives_process_reopen -q -p no:cacheprovider --junitxml=artifacts/p7/three-step-regression-v1/ledger-pg-311.xml
# Python 3.13 使用 .venv-313 和对应 -313 日志/临时目录。
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check src tests scripts migrations evaluation
git diff --check
```

两个 Python 的测试进程并行运行，使用同一个专用测试实例、不同临时目录与新 Run 身份；不是性能基准或单并发 Live。后续受夹具影响的定向复验有独立进程与临时目录，峰值四个测试进程。集成测试内的损坏/撤权/取消反例只针对本轮新建的记录；维护删除测试在自己新建的独立临时数据库内执行，保留临时库不 Drop。原已有 SaaS Seed 重入测试只断言非空库拒绝，不能称重新 Seed 成功。

## 保留的夹具失败与环境修正

首轮两版完整集成均首先出现文档事实模块的七个失败。单例只读定位证明旧 `phase3d-document-completion/pg-fixture/bindings.json` 引用的 Index Pin 在当前实例不存在，原 MCP 正确拒绝 `Pinned index is missing or changed`；不能去补建旧 Pin 或跳过校验。旧 Phase3B 私密绑定也不能跨库冒用。

测试启动适配新增仅本机的 `--fresh-fact-fixture`：将原 `test_document_fact_postgres` 的输出目录和旧私密绑定查找位置指向本轮全新目录，使现有测试代码使用其已经实现的公开合成三文档夹具和原受限摄取接口。没有复制旧 Corpus、重写旧绑定、修改测试源码/断言、读取旧 Holdout 或改变业务策略；每个 Python 的新夹具只首次创建，此后复用。受影响范围仅文档事实模块与导入同一夹具的 Phase4 模块。

同一 year 用例先在旧绑定下失败，改用本轮新夹具后通过（8.38 秒）。原完整失败、单例诊断和后续复验分别保留，不能将最终汇总表述为首轮无失败。辅助依赖检查最初没有应用 lock 的 Python 条件标记，误报 NumPy；保留初始 JSON，按 resolution-markers 重新核对后两版各113个包均无不匹配，未改环境或依赖。

## 当前验证结果

完整单元/契约集合：Python 3.11 **885 passed，17.37 秒**；Python 3.13 **885 passed，17.66 秒**。各有 256 项集成/Live 从该分区 deselect，集成由另一分区执行，不冒充全量通过。

| 分区/轮次 | Python 3.11.16 | Python 3.13.15 |
|---|---|---|
| 完整单元/契约集合 | 885 passed / 17.37秒 | 885 passed / 17.66秒 |
| 首轮完整 PG/MCP 集成（256项） | 241 passed / 13 failed / 2 skipped；3451.50秒 | 241 passed / 13 failed / 2 skipped；3518.18秒 |
| 新公开夹具定向复验（14项） | 14 passed / 150.31秒 | 14 passed / 152.41秒 |
| 补齐隔离路径的非付费账本用例 | 1 passed / 0.30秒 | 1 passed / 0.31秒 |
| 按唯一身份合并后的最终完整集合 | **1140 passed / 1 Live skipped** | **1140 passed / 1 Live skipped** |

首轮13项失败严格限于文档事实7项和 Phase4 6项，均由上述14项现有测试复验覆盖；其中一项 Phase4 原本已通过，不重复增加分母。第二个 skip 是专用 Smoke 账本用例缺少 `DATAPILOT_SMOKE_DB_ENV`，将它绑定到原守卫已经核验的隔离配置后补跑通过。唯一剩余 skip 为 `test_live_model.py::test_real_model_postgres_workflow`，本轮未授权且未请求真实 API。没有 xfail 或残留 failure/error。

两版测试身份与最终判定完全一致：每版885个非集成用例 + 255个真实集成用例通过，另1个 Live 不运行。单例诊断、Live opt-in 守卫和环境复验均不增加唯一用例数；没有为了获得单条全绿命令而再重复一小时完整 PG 集合。源码从开测到最后检查逐字节一致；所有最终结论明确来自分区执行与限定环境复验的合并。

JUnit、全部首轮失败、单例诊断、复验日志和逐身份汇总位于 `artifacts/p7/three-step-regression-v1/`，机器可读公开摘要见 [本轮验收记录](research/p7-three-step-regression.json)。全套真实数据测试使用 Fake/脚本决策或 HTTP SDK Mock，没有供应商 Token、缓存或真实账单数据；不能将1140个工程用例当作独立业务题或真实模型完成率。

Ruff 全仓通过；273 个 Python 文件格式检查通过。实际 OpenAPI 与交付 `docs/api-v1-openapi.json` 相等，共 24 个路径；三个可信宿主策略字段均未进入公开请求 Schema。

## 历史保护与本轮增量

结束只读核对确认：2,090份开测前文件无修改/缺失，290份被测源码/测试/配置闭包一致；另外对照更早基线的373份历史评测原件也保持 Hash。85,630条既存数据库记录无修改/删除，包括原 Evidence、Verification、Run、Journal、Ledger 和 Checkpoint。旧 Gold、Scorer v1/v2/v3/v4、历史失败、not_run 和费用记录未改写。

本轮主隔离库新增293条 execution.runs 注册记录，含组件账本、Fake/HTTP Mock、故障反例与重复回归；不是293个独立业务任务或正式 Campaign。另新增98条 Evidence、96条 Verification及相应元数据、测试 Dataset/Corpus/动态上传表；负例及未完成操作可能只有原始 Evidence，不能将新增 Evidence 全部称 verified。新夹具、上传和摄取通过原可信测试/受限服务进行。维护删除反例仅在其新建临时库执行，临时库保留，无 Drop/清库/删卷或重新 Seed 既存库。

本轮公开增量仅本报告与 `docs/research/p7-three-step-regression.json`。测试辅助文件、原件 Hash、日志和结果 Seal 留在忽略目录。产品源码、正式测试、CI、迁移、锁文件及负责人规划均无本轮增量。HEAD未变、暂存区为空，没有自动提交推送。

## 质量限制与下一步边界

公开英文控制 `How should API keys be rotated?` 的原业务预期仍为 completed；之前真实检索的唯一候选得分 0.5200636541862387 < 0.55，实际 unavailable。联合回归继续单独保留新 Run 的 english-quality.json，不把协议测试 passed 解释为该业务答案正确，不更改问题、文档、阈值或 Gold。

网站仍使用 legacy；三个策略仅供可信宿主显式配置。当前 API 没有向用户签发可信 Fact Proof 或引用分类审批的入口，不能因本轮测试而声称 Web 已默认采用新行为。真实 DeepSeek 对首查说明的遵循率、额外输入 Token/成本以及整体业务质量均未实测；后续须独立限定并授权。

新增三组 PG 测试依赖本机公开 Dev 的私密 bindings、当前隔离实例及 Windows Docker 路径。缺失配置时原守卫会失败关闭；这次本机适配不能被称为干净 CI 已具备可复现性。正式提交/远端验收前，需另行完成最小测试环境可移植适配并实际运行 CI；本轮没有修改测试/CI 配置来隐藏此限制。

浏览器手工 Smoke、数据库整实例重启和远端 CI 本轮均 not_run；API 的真实 HTTP、审批、上传和进程重启由当前 pytest 集成覆盖。没有借用过去的浏览器或数据库重启结果冒充本轮执行。

本轮不创建正式付费实现 Freeze，不重新评价历史成绩。后续候选冻结、Web 启用、英文召回改进、付费 Smoke 和 Gate 3 分别等待新指令。
