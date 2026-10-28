# P7 测试夹具与环境可移植性

本轮只处理用户批准的“消除测试对本机环境的依赖”。此前三步策略、英文召回失败、历史 Holdout/Seal/评分及旧交付记录保留。本轮未修改生产源码、模型策略、Embedding、0.55阈值、P3、权限实现、预算、迁移或依赖；没有付费模型、提交推送和远端 CI。

## 依赖根因与最小变更

三组策略 PG 测试原先导入 `evaluation/p7_citation_dev/dev.py`，读取本机私密绑定，并要求一个特定 Windows Docker 路径、容器名和端口。英文控制的原件也位于忽略目录。文档事实测试则根据旧私密绑定是否存在选择 Corpus，造成前轮13项集成失败。

| 文件 | 必要增量 |
|---|---|
| `tests/reporting_fixtures.py` | 一个测试专用公开数据准备器及三个 pytest fixture：核对显式隔离环境；每个 session 通过原受限 Ingestion/Registry 生成当前实例的 Dataset/Corpus/Pin；按 module 分配独立临时输出。不增加 Runtime、调度、恢复或权限框架。 |
| `tests/fixtures/rag/reporting-cases.json` | 仅保存原公开 Dev 中这三组测试实际使用的7个输入，保留原文/问题/要求；没有复制封存 Holdout。 |
| `tests/fixtures/rag/keys.md` | 英文控制的原字节公开副本，不改问题或文本以提高召回。 |
| `tests/conftest.py` | 注册上述 fixture，不改变已有 pg_settings 或其他测试配置。 |
| 三组 `*_postgres.py` 策略测试 | 保留全部原断言/故障切点，将旧 Dev 加载器替换为共享 fixture，将输出移到 pytest 临时目录。 |
| `tests/test_document_fact_postgres.py` | 固定使用已有的公开合成三文档夹具；每次新 session 创建新 Corpus，删除私密文件存在性分支；Phase4 继续复用该 fixture。 |
| `tests/test_reporting_fixture_portability.py` | 环境/角色/跨实例/query覆盖注入/私密依赖的11个本地反例，不访问外部服务。 |
| `.github/workflows/test.yml` | 原一次性 CI 服务改名为 datapilot_test_ci，所有角色连接同步；明确 DATAPILOT_TEST_ISOLATED=1。原初始化、Seed、模型下载、完整 pytest 和安全检查步骤不删。 |

数据准备沿用原 Dev 的确定性 CSV/字段/时间覆盖/金额单位与原 Registry confirm 接口；因原评测 author 文件冻结，本轮将其必要夹具构造整理到测试目录，未重写冻结文件。session 内共用一次准备结果，各次 pytest 使用新 Dataset/Corpus 身份与临时目录；不存在跨库旧 Pin 缓存。synthetic reviewed 表示测试宿主配置，不是额外人工审批或生产定义确认。

## 明确的隔离准入

新夹具要求 `DATAPILOT_RUN_DB_TESTS=1`、`DATAPILOT_TEST_ISOLATED=1`，数据库名以 `datapilot_test_` 开头。admin/owner/seed/reader/ingest/upload_reader/registry/runtime/checkpoint_owner/rag_ingest/rag_reader/web/maintenance 的显式 DSN 必须采用指定角色、相同 TCP host/port/database，无额外连接参数；拒绝缺配置、普通业务库名、混合实例和把 Reader 指向 postgres。错误信息不输出原 DSN。

连接后以受限 rag_reader 开只读事务核对实际 PG17、pgvector 和无 superuser/createdb/createrole/bypassrls；连接/语句有界。开启集成但缺环境或模型时失败关闭，不能回退 SQLite、随机向量、Fake 检索或成功 skip。未开启集成才保持原 skip。此 guard 是测试宿主的显式部署约束，不是生产租户认证；原 MCP/Reader/Manifest 校验仍实际执行。

测试不会初始化数据库、Seed、下载模型、直接修改 grants 或清理数据库；新上传表的授权仍只由原受限 Ingestion 事务执行。须由可信宿主先部署专用空测试库，并执行原 db-init/migrate/runtime-init；完整旧 SaaS 集合还需宿主显式 Seed240。本轮51项真实集成不依赖 SaaS Seed，使用两个新空库完成。

```powershell
# 仓库根目录；先由宿主配置全部专用角色 DSN、迁移与固定模型缓存。
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_TEST_ISOLATED='1'
$env:PYTHONUTF8='1'
uv run --locked pytest tests/test_reporting_fixture_portability.py tests/test_partial_evidence_postgres.py tests/test_citation_policy_postgres.py tests/test_original_query_postgres.py tests/test_document_fact_postgres.py tests/test_phase4_postgres.py -q
```

Linux 使用同样 pytest 参数与环境名。没有 Docker 客户端/Socket、特定容器名称、固定端口、私密 artifacts、.env 或评测包要求。标准部署可显式运行原 `datapilot rag model-fetch`；fixture 本身不会联网下载。

## 验证记录

实现前新增契约测试因缺 reporting_fixtures 出现1个收集错误；实现中一个空 DSN 的 SQLAlchemy ArgumentError 分类反例失败，补充安全错误归一化后11项通过，原日志保留。

| 当前源码上的执行 | Python 3.11 | Python 3.13 |
|---|---|---|
| Windows完整非集成集合 | **896 passed，19.76秒** | **896 passed，19.85秒** |
| 干净Linux、51项真实PG/MCP + 11项环境契约 | **62 passed，663.61秒** | **62 passed，694.82秒** |
| Windows真实PG路径/子进程Smoke | **4 passed，69.41秒** | 未额外执行；本版真实集成由Linux覆盖 |

干净Linux无 skip/xfail/failure/error，二者测试身份相同。Windows非集成分区的256项integration/Live为deselected，由本轮有变化的51项真实集成定向补验，不声称本轮再次执行全部旧PG集合。11项环境测试与Windows集合重叠、4项Smoke与Linux集合重叠，不累计成新的独立用例。未调用DeepSeek或其他真实生成API，工程用例数不代表业务Benchmark成功率。

Ruff全仓通过，276个Python文件格式检查通过，git diff --check通过。CI中13组角色连接通过相同guard，实际远端CI仍not_run。日志/JUnit/干净目录闭包、测试前文件原件及差异位于忽略目录 `artifacts/p7/fixture-portability-v1/`，公开摘要见 [机器验收记录](research/p7-test-fixture-portability.json)。

干净验证目录只复制源码/正式测试/脚本/迁移和项目配置，不复制 .env、Git、evaluation、旧 artifacts 或 Gold；固定本地 BGE 文件只读挂载，按原 SHA 校验。使用已有锁定依赖镜像中的 Python3.11/3.13，两者各自连接一个全新 datapilot_test_portable_* 数据库；原隔离历史库和用户数据库不作测试写入。所有模型决策为 Fake/脚本或 HTTP Mock，真实检索使用 PG17+pgvector/本地 ONNX/MCP。

两版都明确核对实际模块导入路径为 `/case/src/datapilot/...`，防止误用依赖镜像内旧安装。干净源码只读、结果单独可写、无Docker Socket和模型API Key；证明不需要旧私密绑定。Windows额外覆盖部分事实、P3+补充引用、工具提交后硬退出恢复和精确事实持久化，使用同一新测试库里的全新Run。

本轮相对开工快照只修改上述6份既有测试/CI文件；生产源码、迁移、锁、旧规划和历史报告保持。原7个公开输入逐字段相等，英文原件字节Hash一致。旧隔离库的121,808条记录与上轮结束快照逐行Hash一致，无改写/删除/追加；新测试数据仅在两个本轮新建数据库中追加，测试库/容器均保留，无清理/删卷/重新Seed。新Run/Evidence/Pin不能追溯替换任何历史评测。

新增helper只负责现有公开夹具准备和pytest生命周期，未增加第二套调度/恢复/账本；三个原测试文件仅切换fixture、输出和英文原件位置，原断言与故障切点未删除。旧文档事实分支中两次赋值的重复维护文案已整理，保留现有公开fallback文案与全部断言。没有无关重构。

## 保留边界

英文控制仍按原业务预期 completed 独立记录：本轮两版Linux均为0片段、unavailable、business_correct=false；协议/恢复 passed 不会把错误空召回改成合法拒答。不调阈值、改写查询、替换模型或删除失败来刷通过。

本机干净 Linux 验证不等于 GitHub Actions 已运行。远端 CI、浏览器、新付费 Smoke、正式新 Freeze、默认 Web 启用和英文检索优化均不在本轮范围。历史报告中“本机绑定依赖”的限制保持其当时事实，以本记录补充当前状态。
