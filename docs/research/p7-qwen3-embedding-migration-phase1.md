# P7 Qwen3 Embedding Migration Phase 1

日期：2026-10-29（Asia/Shanghai）。基线 HEAD `f8b122438d2c67ab26e618ecded72ecc18454015`。

新实现freeze：`qwen-migration-p1-7ca65af73573`；211份源码/契约/依赖文件清单SHA `7ca65af73573d5e6eb0913811c165ef839a9126352608d311d3463eaccdb6d84`。原P7冻结清单不改。

**最小兼容实现及隔离工程验收完成；生产默认仍为 BGE。** 新 Qwen CPU/GPU profile 已实际经过原摄取、PG17/pgvector、MCP、RAG 完成协议、事实报告和 Durable 恢复链。模型决策全部为脚本/Fake，没有 DeepSeek/其他付费调用，没有重新评测历史 Holdout，没有提交或推送。冷启动和取消清理的尾部耗时仍是生产切换前的阻碍。

## 审计与最小兼容范围

| 原耦合位置 | 本次处理 |
| --- | --- |
| `rag/contracts.py` 的512维 ModelSpec | 只增加原生1024维；默认512不变，文件清单上限扩至8 |
| `rag/models.py` 的 BGE 工厂、512维校验 | 默认原工厂；Qwen 延迟加载；向量校验显式接收维数，拒绝其他维数 |
| 0005 / `rag.chunks vector(512)` | 历史迁移、数据不动；新0008只增加 `rag.chunks_1024 vector(1024)` 及相同权限/外键/范围索引 |
| MCP 预检固定 `specification()` | 仍严格相等，只改为核对宿主 profile 对应的固定 ModelSpec 和策略 SHA |
| `bge-host-goal-cosine-v1` / 0.55 | BGE保持；Qwen有独立 Search/Goal策略及新的校准记录 |
| 原问策略、Report、恢复身份中的 `retrieval_goal` | 可选接收可信检索句柄，把对应 Goal策略穿透原调用点；原要求解析、事实/因果及完成规则不改 |
| 原环境 tokenizer 0.23.3 与 Transformers 4.57.1 的依赖冲突 | 独立锁定 `.venv-qwen`，运行**相同** stdio MCP源码，保留主环境、`pyproject.toml` 和 `uv.lock` 的原始字节 |

没有新增 Scheduler、检索服务、Verifier 或恢复引擎。P3、Journal、Ledger、Saver、权限/业务配方未修改。`persistence/session.py` / `inspection.py` 各一处适配仅将真实检索策略传给原目标身份构建，未更改预算、恢复算法或未知调用规则。

新增字段/接口的必要性：

- `RagScope.embedding_profile`：宿主明确选择两个新 profile之一；模型工具仍只有 query/top_k。没有任意模型、文件、Python或阈值参数。
- `IndexManifest.relevance_policy_sha256`：把模型专属的校准策略纳入 IndexVersion，防止相同来源被其他模型/阈值解释。
- 两字段缺省时从投影省略，保留旧Scope/Manifest hash。`EmbeddingUsage.local_torch`区分本地Torch编码与原ONNX/Fake，不是供应商用量。
- `_connection(executable=...)`：仅可信RAG适配器使用固定 `.venv-qwen` 部署路径；缺环境失败，不接收模型提供的可执行路径。Qwen子进程仅有原RAG Reader凭据和固定源码路径，不继承Provider/管理员/Registry密钥。
- `rag/qwen.py`：固定模型、版本、文件、推理和策略；原Storage/工具/完成协议继续复用。`rag ingest --embedding-profile`是可信CLI部署/摄取选择，不注册为模型工具。

完整决策见 [ADR-017](../adr/0017-opt-in-qwen-embedding.md)。仍存在的512是旧BGE默认、旧表或512 token/字符输入配额；后者不是向量维度，不应机械替换。

## 模型、IndexVersion 与策略

| profile | 模型/维数 | recipe | 执行环境 |
| --- | --- | --- | --- |
| 缺省 | 原BGE/Qdrant ONNX，512 | 原CLS/L2/中文query前缀 | 原ORT1.31.0/tokenizers0.23.3 |
| `qwen3-cpu-v1` | Qwen3-Embedding-0.6B，1024 | last token、FP32、L2、固定SaaS query instruction | 独立Torch2.8.0+cu128/Transformers4.57.1/tokenizers0.22.2，CPU |
| `qwen3-cuda-fp16-v1` | 同一Qwen权重，1024 | last token、FP16 hidden、FP32归一化、同一instruction | 同一独立环境，CUDA12.8；不可用时拒绝，不静默转CPU |

Qwen revision：`97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`；safetensors SHA：`0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd`。运行前核对config、权重、tokenizer、tokenizer_config、vocab、merges六个SHA；目录不允许额外文件/链接。仅本地文件、`trust_remote_code=False`、safetensors、eval/inference_mode，不下载、不训练、不截断。最长512字符/512 token、batch1、两CPU线程。

CPU与GPU的recipe、策略和IndexVersion不同；不能把1024向量写入旧表，或把同一revision当成可混用精度。索引仍绑定Target/Dataset/version、完整来源集合、原件/片段hash、跨度、chunker与检索器。此次主Dev新增4个Corpus、12个IndexVersion、72条向量；后续pytest另建独立Corpus并追加测试记录。仅在新库 `datapilot_test_qwen_migration_p1_20261029` 执行迁移及写入，旧库没有执行DDL/DML/Seed；全局角色未修改，未清库/删卷。

## 新Dev与阈值校准

[公开合成Dev](../../tests/fixtures/rag/qwen-migration-dev.json)先登记，再推理：SHA `7dcb299a8493377cffda084d3f0845a5cab9da2938977c42a5d8ee10bfa0f9fd`。20条calibration与20条validation，主题分开；覆盖中/英同语言、双向跨语言、多Required来源、缺主题、SQL文本、背景不足、注入及目标错配。它们包含同主题语言变体，**不是40个独立业务任务或新的sealed Holdout**。Gold为明确源/目标标签及合成宿主事实，不伪称独立人工审批。初稿目标错配标签在任何推理前纠正，旧初稿登记记录仍保留。

Search仅按calibration的空Gold误召回为零、再最大化Recall选择；Goal按calibration候选的原目标标签独立选择，要求无错误资格接受。固定grid 0.20–0.95、步长0.05，平局取高阈值，先落校准锁再看validation。

**两个profile独立校准的Search与Goal阈值均得到0.55。** 这是新Dev选择结果的数值巧合，不是沿用BGE阈值；策略名分别为各profile的 `/search-cosine-v1`、`/host-goal-cosine-v1`，校准锁SHA `9be20cb4b8cbffbe74a95a06d15d4bf7b6bad621a67972301decd7d98233fa2b`。策略SHA进入索引，BGE目标契约不能用于Qwen完成收据；宿主min_score只能提高下限。

实际MCP验证结果，两profile各20条：

| 指标 | CPU | GPU |
| --- | ---: | ---: |
| Source Recall@3（17条非空Gold） | 100% | 100% |
| Mean Required Coverage（17条） | 94.12% | 94.12% |
| 完整Required覆盖 | 16/17 | 16/17 |
| 返回Source Precision（本小集） | 100% | 100% |
| 空Gold误召回 | 0/3 | 0/3 |
| 不相关Source条目 | 0 | 0 |
| MCP错误 | 0/20 | 0/20 |

Required分母保留故意“query指向A、原目标需要B”的负例，不能删除它制造全覆盖。Goal独立诊断在validation各60个阈值前候选对中为TP19/FP0/FN0/TN41；这是**已召回候选条件下**的相关性标签，不代表全库召回、事实真实性或业务完成。一Source一短chunk，不能外推长文档/多chunk。3条空Gold也不足以证明普遍零误召回。

另有预登记的[高相似度安全Dev](../../tests/fixtures/rag/qwen-migration-safety.json)，不用于校准。真实分数：当前规则0.8200，已撤回规则0.7276，虚构桌游规则0.6476。两条干扰都高于阈值；报告只发布已绑定当前Source的事实，业务completed；增加一个无法提供审阅事实的Required来源后实际partial。证明报告守卫必要，不能用高相似度替代事实。

按这一额外案例的“当前规则”Source Gold，Search返回3条中仅1条支持事实，Precision=1/3、误召回2条。不能把主Dev的零误召回外推到它，也不能把Report成功过滤干扰描述成Embedding没有误召回。

## 真实性、事实覆盖及恢复

Qwen专项15项PG/MCP验收通过：owner/index/model/precision错绑、策略SHA/引用伪造、原目标绑定、Required/Supplement、完整/部分/缺失事实、因果声明、注入正文、跨进程重复恢复和issued工具未知结果。五类报告实际分别为completed、partial、unavailable、partial、unavailable；纯文档不发布P3数字或财务图表。

0007上创建并暂停BGE Run，0008后用新进程恢复为succeeded/completed，旧512索引 `ada19a75e6f8258e4327b37db0e32f753190fbd62f1f4a812cf162bc6972d0b3` 保持。Qwen暂停/恢复/再次恢复的报告与预算一致；精度策略变更拒绝；`tool_issued`进程退出后返回 `RECOVERY_UNCERTAIN`，不重发。真实新表Reader只SELECT、Ingest只SELECT/INSERT；只读事务与额外独立grant负例分别得到25006/42501。

以上为真实本地神经Embedding＋PG/MCP＋**脚本/Fake模型决策**，不是DeepSeek自主推理质量评测。P3六层及旧证据/预算/三策略的保护由原回归验证，不把文档收据升级为P3 verified。

## 性能与10秒限制

实机：i9-14900HX、24核/32线程、16GB RAM、RTX5060 Laptop 8151MiB，驱动582.05；实测Torch2.8.0+cu128可执行FP16。单模型/单请求、batch1、两CPU线程、短公开文本；其他桌面应用和部分回归进程存在，没有清OS缓存或锁频，不是SLO或并发容量测试。

| 实测 | CPU FP32 | GPU FP16 |
| --- | ---: | ---: |
| 单query编码p50/p95，40次（ms） | 254.71 / 422.29 | 31.67 / 54.66 |
| 该性能进程加载，含import/hash（s，N=1） | 9.58 | 7.84 |
| 预热（s） | 0.389 | 0.455 |
| Peak process RSS（GiB） | 3.86 | 2.77 |
| GPU allocator峰值/保留（GiB） | 0 / 0 | 1.125 / 1.139 |
| MCP冷search范围，3次（s） | 6.78–7.12 | 6.99–7.37 |
| MCP热search p50/p95，17次（ms） | 266.40 / 473.95 | 54.57 / 84.89 |

p50为中位数，p95为nearest rank；编码在输出CPU向量后计时，包含CUDA同步。MCP计时是单次search，包含验证/PG/SDK，不包括会话启动/退出。不能把分位数相加成Run时延。最初校准进程还记录GPU加载34.15秒、CPU7.97秒；冷启动尾部明显存在，不能只选择较快的后续加载。

同一真实会话重复搜索，首次query＋goal编码2次，第二次1次，Goal score完全相同；模型与Goal缓存确实复用。**这不是跨Run常驻模型**，新stdio进程仍需加载。

延迟模型的真实MCP故障夹具中，调用10.009秒返回TOOL_TIMEOUT，取消等待0.215秒结束；原连接器将SDK晚到响应关闭错误转换为TOOL_ERROR。两个完整测试约31.6秒，说明同步初始化/SDK清理不能被当成即时取消。这两个用例使用注入延迟，不冒称真实Qwen质量推理；未放宽10秒调用限制，unknown仍保守阻断。清理尾部是下一阶段Gate，尚未解决。

## 测试、失败历史及完整性

| 真实执行 | 结果 |
| --- | --- |
| 冻结实现的Python3.11非集成回归 | 972 passed |
| 冻结实现的Python3.13非集成回归 | 972 passed |
| 原P3/BGE/MCP/三策略/恢复定向PG，3.11 | 77 passed |
| 同一PG回归，3.13 | 77 passed |
| Qwen专项PG/MCP/Report/恢复/传输故障，3.11宿主 | 15 passed |
| Qwen Goal/Citation与跨进程恢复，3.13宿主 | 2 passed、13 deselected；子进程仍固定3.11 |
| Ruff check / format、git diff --check | passed |

没有运行完整全部PG/UI套件、远端CI、Linux/GPU容器或付费Live。相关原回归使用新的隔离记录，未对历史Campaign调用模型或重评分。

既有通用health按Alembic head严格检查；源码现在head=0008，未升级的0007库会提示迁移未达预期。这不是自动升级授权。本轮证明BGE运行/恢复的兼容性，没有放宽health，也未把未迁移生产库宣称为已完成新版本部署。

保留的失败：首次专项10通过/1失败是旧测试CLI读本机.env造成策略不匹配，原Manifest守卫正确拒绝；固定测试宿主策略后12通过。底层SDK直接关闭出现2失败/12通过，改为测试产品原连接器后15通过，未修改连接器恢复规则。首轮旧PG回归36通过/41 setup errors源于Windows Temp权限，改用新的仓库内basetemp后两版本均77通过。另有诊断输出字段/Row JSON序列化修正，失败脚本/日志保留，不算产品通过证据。

原AB结果77文件、原Live Smoke136文件、Scorer修复29文件的Seal逐项无变化，原6passed/1failed/1not_run保持。主锁、旧Gold/Scorer/Seal、用户v2.4/v2.5规划未改。`AGENTS.md`只追加本阶段约束，已有未提交修改保留。

完整JSON、ModelSpec/12个索引Manifest、测试计数和历史检查见[机器记录](p7-qwen3-embedding-migration-phase1.json)。本地日志、JUnit、原始排名、资源记录、依赖安装及新实现freeze在忽略目录 `artifacts/p7/qwen3-migration-phase1/`；凭据仅在私密environment文件，不进入本报告。

## 复现入口与下一Gate

保留基础环境 `uv sync --locked`。Qwen只在**另一个**环境安装：

```powershell
uv venv .venv-qwen --python .venv/Scripts/python.exe
uv pip sync requirements/qwen-mcp.lock --python .venv-qwen/Scripts/python.exe --require-hashes --index https://download.pytorch.org/whl/cu128 --index https://pypi.org/simple --index-strategy unsafe-best-match
```

部署固定六文件到 `.cache/rag-models/qwen3/<revision>/`，由 `check_files()` 核验；MCP不会下载。新1024表只通过新Alembic0008在获授权的隔离库显式部署。可信摄取用独立环境、固定源码路径和 `rag ingest --embedding-profile qwen3-cuda-fp16-v1`（或CPU），其余原审批/目标参数照旧；产出的Scope可供原rag_session/run_durable。不要将这些操作套用生产.env或自动切换Web。

测试命令（事先配置独立测试角色环境，API Key空）：

```powershell
.venv/Scripts/python.exe -m pytest -m "not integration and not live" -p no:cacheprovider -q
.venv-313/Scripts/python.exe -m pytest -m "not integration and not live" -p no:cacheprovider -q
$env:DATAPILOT_RUN_QWEN_TESTS='1'
.venv/Scripts/python.exe -m pytest tests/test_qwen_migration_postgres.py -p no:cacheprovider -q
$pgTemp = 'artifacts/tests/pg-' + [guid]::NewGuid().ToString('N')
.venv/Scripts/python.exe -m pytest tests/test_semantic_integration.py tests/test_rag_postgres.py tests/test_recovery_versions.py tests/test_citation_policy_postgres.py tests/test_partial_evidence_postgres.py tests/test_original_query_postgres.py -p no:cacheprovider --basetemp $pgTemp -q
```

后续应先处理并验收**冷启动尾部/10秒余量、慢初始化取消清理、资源竞争、Linux/Docker依赖及解释器绑定**。维持原MCP架构，不以隐性预热或重试绕过时限；任何生命周期调整需明确边界。之后再决定Web集成及独立新Freeze/有界Live授权。本轮不切生产、不进入Gate3、不启动新Campaign。

参考：固定[Qwen模型源码/说明](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B/tree/97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3)及[PyTorch官方版本安装说明](https://pytorch.org/get-started/previous-versions/)。权重采用Apache-2.0；未复制第三方Runtime源码。
