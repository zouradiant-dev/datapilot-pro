# P7 New Implementation Freeze

日期：2026-10-26（Asia/Shanghai）。本轮只建立新冻结并准备零付费 Smoke。**不是付费授权；真实 DeepSeek 质量仍 not_run。** 当前执行前状态见 [Smoke 计划](p7-deepseek-smoke-plan.md) 和机器 preflight 记录。

## 冻结身份与范围

| 身份 | 实际值 |
|---|---|
| Freeze ID | `p7-dev-smoke-impl-v1-c2dd57f1294a` |
| Implementation Manifest SHA256 | `d673860787c22881e07e45fb7eb4e8ffb95a83317cfce166364f3812cb05fe73` |
| Working Tree Source SHA256 | `c2dd57f1294ab0ee7b17b53e6c5f8da2d15a16e1bb09a24c44a36ca8c97b9180` |
| Git HEAD | `18271d7b5159dff7e01bb1e6edd3257f9fd78be4` |
| Branch / 状态 | main；存在既有 tracked 修改与 untracked 运行源码，未 commit/push |
| 文件闭包 | 261 文件，包含 src、scripts、tests、migrations、锁/依赖、Docker/Compose、构建配置及必要约束 |
| Case Seal SHA256 | `e1599b3dff412b38e740ecec2bdd5335625895c66f72c6e2ea56081f22d6c711` |
| Evaluation Protocol SHA256 | `15083497b1bb8208a07072e20ee552f02c50dd673db8c942dcc0bf09edd4dc67` |
| Smoke Evaluator Seal v2 SHA256 | `83e3b362384fa8de9d6c00131e901795b628573f2d0a681c0c49a22d934fa833` |

机器入口为 [Freeze anchor](research/p7-new-implementation-freeze-v1.json)。完整清单为本机忽略目录 `artifacts/p7/dev-smoke-v1/implementation-freeze-v1.json`，运行快照 `frozen-source-c2dd57f1294a`。原 Phase 4/Unified Candidate 未冒充本冻结；这是本轮新建的正式实现冻结。

路径统一 POSIX/NFC、拒绝符号链接和大小写冲突，以文件实际字节计算 SHA256；将排序后的 UTF-8 canonical JSON 路径→SHA 映射再 Hash。源码 Hash 与 Commit、镜像、协议、数据 Hash 各自独立。Manifest 不包含自身 Hash，由外层 anchor 固定；Case/Evaluator Seal 不引用未来 Manifest，避免循环依赖。

每次执行核对当前完整运行文件集合（包括新增 untracked 文件）、只读快照集合/字节、Case/Gold Seal、Evaluation Protocol/Seal，Source/Registry/index pin 和两张合成表的有界 MCP 指纹。新增/删除/修改执行文件或协议即 FREEZE_INVALIDATED；不得静默覆盖，须保留原件、验证受影响功能并创建新版本。

## 已包含的产品修复

当前 src 与已通过 Unified Regression 的源码逐字节一致，包含 Phase 1 拒答原因、Phase 2 Host 因果契约、Phase 3D 必需事实覆盖、Phase 4 预算感知上下文/快照拒绝，以及统一回归的 Web 确认与 Journal 畸形缓存恢复修复。没有改 P3 六层 Verifier、SQL 配方、RAG 阈值/查询策略、预算、权限或迁移。

本轮只新增三份 P7 评测适配脚本和 `test_p7_smoke.py`；原 Runtime、Collector、Scorer v1/v2 与旧评测包不改。适配复用原 `run_durable`、`inspect_run`、PG lease、DurableLedger、签名采集和数值/引用检查；新协议只适应 Phase 3D 事实覆盖和八条 Dev 身份，没有第二套 Scheduler/Checkpoint/计费引擎。

## 依赖、镜像及基础设施

- Python：本机 3.11.16/3.13.15；候选镜像 Python 3.11.14，uv.lock/pyproject 均原字节。完整安装版本在 Manifest，之前 Linux 双版各 985 passed/1 Live skipped 的记录作为未改变产品的基线。
- Docker 固定镜像身份 `sha256:6c78a77b7ca5604bf4ac4ff8e725bc72370d550aef6c9c5b545eb27b8fa87339`，descriptor 为 OCI image index，原 RepoDigest/OS/架构另存 Manifest。候选使用该镜像 + 精确只读源码/三份执行 helper 挂载，不把本机 Tag 当不可变身份；禁止自动 pull。原件、Gold、签名 key、.env、Docker socket 不挂给候选。
- 仅使用已建隔离项目 datapilot-p7-unified，127.0.0.1:55441/datapilot_unified，容器可信端点 postgres:5432。真实 health：PG17.11、pgvector0.8.6、Alembic0007。无迁移、初始化、Seed、清库或删卷。
- 本轮开始 Docker Engine 已停止。启动既有 Docker 后原 Demo 的 restart policy 自行启动其 PG；本轮未向旧实例执行 db-init/seed/停启/清理。原 Gate2B PG 保持停止，没有为了重复审计启动它；历史库行 SHA 沿用上一轮已验证快照，本轮只写新隔离数据和新 Run。

## 新数据、P3 与引用

新合成 Dataset `ae623898-326b-5bfc-9052-7ed993e6627d` v1，原件 SHA `d319a6a5a6e8013ed19fe92e2bc1df5a02f8ec1437d35f35875d7ccd4e8e5e57`。两表共13行，使用2026年8/9月、north-* ID 和全新金额/事件；不是旧 bh2 任务改写。

Semantic v1 SHA `272ef81974ea38bdf52369befa1778bd8e571fe6d619d99aef7b6375cb874f58`。paid_invoice_revenue/usage v1 使用既有 saas_metrics_v1：paid/CNY/minor-unit/右开窗口，usage 的 automation 过滤，覆盖声明仅属于明确的合成夹具。通过原 Registry confirm 接口登记，不更新 reviewed、不触碰旧定义。此为授权准备中的合成宿主契约，不冒充独立人工签署。

三个新 Corpus 与 Source/Document/Chunk、span、文件/text Hash、index/model/chunker 版本存于封存 pins。每个 Corpus 单独授权，不用不兼容的 Document 子集 Pin。跨来源 Report 仍分别核验 P3 Evidence/Verification 与 RAG 引用。对物理表做 MCP 指纹是有界点检，**不证明最新或跨来源同一时点快照**。

Embedding：BAAI/bge-small-zh-v1.5/Qdrant-onnx，revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，512维；ONNX/tokenizer 文件实际大小和 SHA 已校验。0.55、默认 Top-k3（合法1–5）、每任务两次搜索及原 Stop Hook 不变；未合并原问优先策略。

## Provider、预算与恢复

API ID deepseek-flash，https://api.deepseek.com，Chat Completions/native tool calls，temperature0、thinking disabled、max_tokens1200、timeout30秒、SDK retry0。当前本地配置匹配且 Key 非空；**只验证存在/形式，不验证 Key 有效性，未调用 API 或模型列表**。官方网页所列服务版本仅供记录，别名不是不可变服务端版本；实际响应型号需在未来授权实测中记录。

JSON/Tool 参数经原 Gateway/Pydantic 校验；没有宣称新启用 response_format、全供应商结构化输出或 Prefix Cache 省费。每次模型/摘要调用仍走原 Ledger。Root8 calls/18000 Token，Child4 calls/18000 Token，原 Context L0–L4、Artifact SHA、Journal、Checkpoint、unknown-outcome 和角色隔离保持。

Campaign 额外用原 DurableLedger 预留整个 Run 的18000，再按已知真实用量结算；未知保留全额。其 calls 字段单位为 Run 派发槽，最多7槽，绝不是7次模型调用。7个唯一 Run×原8次上限保证最多56次模型尝试；公共池90000计账单位，SDK/外层零自动重试。数据与模型预算、超时、停止条件详见计划和 [Budget/Stop 记录](research/p7-dev-smoke-budget-stop-v1.json)。

## 冻结前失败与历史保护

原始 Docker 未运行、合成 Mapping 日期逐字段赋值触发校验、旧指标投影省略空 fact_coverage、首次清单嵌套 DTO 序列化错误均保留在 smoke-preparation-v1 日志。修复仅限新准备/评测脚本。首次清单未发布有效 Manifest/anchor，其未封存快照和 Evaluator Seal v1 保留；最终使用新内容快照和 Smoke Evaluator Seal v2（不等于历史 Holdout Scorer v2）。原 Case/Gold Seal 未变。

当前 Manifest 发布后不再修改任何冻结运行文件/输入/规则。源码变化必须作废原 Freeze 后重新回归/封存。所有原 60 Holdout、31观测/29未运行、v1 25/31、离线v2 26/31、61次/77897 Token 和费用记录保留。无新真实 Campaign、无历史重评分、无 Gate3/P8–P11、无 Git 提交/推送/远端 dispatch。当前工作树远端 CI 为 not_run；PR-only 连接器对旧 HEAD 返回空集合，不能据此推断 push CI 成败。

## 最终完整性与停止状态

新Freeze发布后与Dry Run前后均有效；Gold/Case/Evaluation Seal未变。8条零付费Dry Run全部符合冻结预期；每版本71项定向测试和1项真实PG预算重开通过，七条跨进程NoModel重放不改变原引用/账本。详见 [最终机器校验](research/p7-deepseek-smoke-preflight-v1.json)。

准入状态：**READY FOR SEPARATELY AUTHORIZED PAID SMOKE**。这是准备通过，不是真实DeepSeek业务能力通过；没有正式付费Campaign、消费授权或预算余额沿用。后续任何有效运行源码/输入/Scorer变更仍必须 FREEZE_INVALIDATED、保留原Freeze并另建版本。
