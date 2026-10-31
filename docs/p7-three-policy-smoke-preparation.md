# P7 三项策略冻结与 Live Smoke 非付费准备

2026-10-29。本轮只准备 Required/Supplement、Partial Evidence、Original-query-first 联合启用后的版本化 Dev Smoke。未调用 DeepSeek、未执行新 Holdout 或 Gate 3，未提交/推送。当前状态为 **ready_for_live_authorization_with_known_quality_failure**：工程链路已通过，英文短问的质量失败仍在；这不表示 Live 或质量 Gate 已通过。

## 冻结与复用边界

- Git 父基线：`f8b122438d2c67ab26e618ecded72ecc18454015`；本轮新增文件尚未提交。新 Freeze 是精确工作区字节快照，不能当作已提交版本。
- Freeze ID：`p7-three-policy-dev-v1-4e9651e1844f`，完整闭包 **284 文件**。
- Implementation Manifest SHA256：`c46f092849e2fdd98f1220244641a1b8a43942c8b36c34429913cd7b2d6a79ce`。
- 本地准备包：`artifacts/p7/three-policy-smoke-v1/pack-v2/`。`anchor.json` 固定 Manifest；Manifest 固定源码、快照、Case/Gold、数据与定义 Pin、协议、Scorer、预算和 Fake/Live 两套配置 Hash。
- 本地结果 Seal SHA256：`195940815c6d23e076e5f81d3ba49f33a643ab179e42ba05a6a4063f0107e3f0`，固定 85 份机器记录/快照摘要及 [公开机器摘要](research/p7-three-policy-smoke-preparation.json)。原始工件、DSN、签名 Key 留在忽略的私密目录，不上传或放入公开 Trace。

原 Smoke 的固定 ID、Permit 和 Scope 投影不包含全部三项新策略，故新增薄版本适配器，不修改旧 Runner、Scorer 或 Seal。执行继续使用原 `run_durable`、LangGraph、Gateway、Journal、Checkpoint、Artifact、`DurableLedger`、`inspect_run` 和签名 Collector；Scorer 复用原权威 Plan 版本任务键及 RAG 收据解析。未新增 Scheduler、恢复引擎、账本实现或业务验证器。

修改文件及必要性：

| 新文件 | 作用 |
| --- | --- |
| [p7_policy_smoke_prepare.py](../scripts/p7_policy_smoke_prepare.py) | 复用公开 fixture、独立 CSV/Decimal Oracle、精确 Source/Metric Pin 与新闭包封存；拒绝覆盖已有包 |
| [p7_policy_smoke.py](../scripts/p7_policy_smoke.py) | 本版 Case/Gold DTO、完整策略 Scope/Artifact/P3 引用评分；不更改旧 Gold/Scorer |
| [p7_policy_smoke_run.py](../scripts/p7_policy_smoke_run.py) | 在原账本和子进程执行器上顺序派发；每次先预留原 18k、遇未知结果保留预留并停止 |
| [p7_policy_smoke_worker.py](../scripts/p7_policy_smoke_worker.py) | 仅接受单个封闭配置；Live 在读取凭据/构造模型前核对新授权；Fake 只提供决策 |
| [test_policy_smoke.py](../tests/test_policy_smoke.py) | 新授权、过期、预算类型、闭包漂移、JSON Scope Hash、独立 Oracle、签名篡改反例 |
| [test_policy_smoke_postgres.py](../tests/test_policy_smoke_postgres.py) | 沿用 portable_pg/reporting_dev，验证真实 Pin、P3 上下文与越权宿主拒绝；不依赖本机 Docker 路径或历史 bindings |

只给可信宿主增加 Dev 协议/冻结适配，没有修改 `src/`、依赖、迁移、旧测试、业务策略或网站默认开关。候选容器挂载精确 `src`、必要的五个执行辅助文件、单个配置和固定 BGE；不挂载 Gold、Scorer、Collector Key、其他 Case、`.env` 或 Docker Socket。启动前 probe 实测这些私密入口不可读。

## 公开 Dev 协议与实际结果

这些题来自已有公开合成 fixture 与已测英文控制，**非盲、非新的独立 Holdout**。金额 Gold 用原始 CSV 独立 Decimal 按 paid/CNY/2025-10 右开窗口求和为 **637.45 CNY**，不从 Agent 或 P3 输出反推。文档预期来自审阅的原文事实绑定；合成 fixture 的可信宿主确认不是虚构人工签名。每个 RAG Scope 显式开启三项新策略，Web 默认未变。

| Case | 范围 | Gold | 实际 | 严格正确 |
| --- | --- | --- | --- | --- |
| tps-01 | SQL 已支付收入，排除未付记录 | completed | completed；637.45 CNY、P3 verified | 是 |
| tps-02 | 必需配额事实＋有原文支撑的补充取整事实 | completed | completed；两类引用职责分离 | 是 |
| tps-03 | 有水位背景，但缺离线承诺事实 | partial | partial；保留已证实事实和缺口 | 是 |
| tps-04 | SQL 收入＋文档未证明的补寄保证 | partial | partial；数值 verified，文档缺口保留 | 是 |
| tps-05 | 时钟事实与无关果园来源 | completed | completed；无关来源未发布 | 是 |
| tps-06 | 入门步骤事实与未证实因果 | partial | partial；因果仍未验证 | 是 |
| tps-07 | `How should API keys be rotated?`，原英文短问 | completed | unavailable；空检索，未发布无依据事实 | **否** |
| tps-08 | 其他 owner 访问已绑定 Corpus | blocked | DOCUMENT_NOT_AUTHORIZED；无 Runtime/模型 | 是 |

planned/observed **8/8**，Runtime **7**，宿主拒绝 **1**，not_run **0**；严格正确 **7/8**（Runtime 6/7，宿主拒绝 1/1）。这只说明脚本决策下的确定性工程结果，不是 DeepSeek 成功率。英文短问仍按原 completed Gold 计失败，没有改成“预期拒答”；保持 0.55、原 BGE、检索次数与生产 Top-k 范围不变。Fake 沿用既有 Script 的 Top-k=5，未来真实模型可在原 1–5 范围内选择，不能据此声称公平的检索策略质量 A/B。

7 个 Runtime 均真实经历审批 interrupt → 原宿主 approve → 真实 MCP/P3/RAG → Report → 私密签名收集 → 新进程终态重放（NoModel）。重放后 Artifact、调用记录、Manifest、报告、P3 Evidence/Verification、usage 完全一致，无新增调用。产生两组新的持久 P3 Evidence/Verification，ID 见机器摘要；不存在将查询/检索收据直接升级为 P3 verified。

独立进程离线复评 **8/8 一致**。对签名记录副本进行的 **9 项**反例均拒绝：错误 Case、错误 owner、未知结果、unverified P3、错误 Metric 版本、未知 usage、伪造文档 Artifact、篡改引述、将宿主拒绝伪装为模型执行。原始签名记录和评分未覆盖。

Fake 决策共 **19 次**，工具 Journal **21 条**；脚本填报 **285 Token 单位**，不是供应商 Token。Campaign 账本为 7 个 Run 派发槽/285 已知单位，执行约 **308.83 秒**，无严重停止或未知结算。真实 Provider attempts **0**，真实 input/output/cache-hit/miss 均不适用，账单不适用；没有将 Fake usage 当作费用数据。

## 真实验证及保留的失败

| 检查 | 本轮真实结果 |
| --- | --- |
| Python 3.11 定向单元/旧 Smoke 契约 | 44 passed，1 integration deselected，0 failed |
| Python 3.13 同一定向集合 | 44 passed，1 integration deselected，0 failed |
| Python 3.11 真实 PG/MCP 新包预检 | 1 passed，0 failed，26.87 秒 |
| 隔离容器的 Fake→真实 PG/MCP/本地 BGE/Durable | 上表 8/8 观测，7 个严格正确，1 个质量失败；含 7 个终态重放 |
| 独立签名评分/篡改副本 | 8/8 评分一致；9/9 反例拒绝 |
| Ruff lint | 全仓通过 |
| Python format | src/scripts/tests/migrations 的 260 文件通过 |
| `ruff format --check .` | 发现原有 3 个 Markdown 代码块格式差异，保留未改；不冒称全仓格式全绿 |
| `git diff --check` | 通过；已有 LF/CRLF 提示保留 |
| Python 3.13 实时 PG、本轮完整 pytest/浏览器/远端 CI/Live | **not_run**，未用此前 CI 替代本轮验证 |

精确命令与 JUnit 留在 `artifacts/p7/three-policy-smoke-v1/`：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest tests/test_policy_smoke.py tests/test_p7_smoke.py -m 'not integration' -q
.venv-313\Scripts\python.exe -m pytest tests/test_policy_smoke.py tests/test_p7_smoke.py -m 'not integration' -q
# PG 命令先由可信宿主注入全部现有 portable_pg 隔离角色与 RUN_DB_TESTS/TEST_ISOLATED 标记。
.venv\Scripts\python.exe -m pytest tests/test_policy_smoke_postgres.py -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check src scripts tests migrations
git diff --check
```

PG fixture 会只向独立 `datapilot_test_*` 追加新的公开数据，不能用演示 DSN。已完成包不可通过重跑作者工具重建；本轮首次预检错误及后续封存错误保留在失败日志/`failed-preparation-attempts.json`：初版 126k 预算被原 100k 契约拒绝、缺显式 metric_goals、测试误解 pending 状态、错误 helper 导入、错误测试路径、嵌套 DTO 未转 JSON。修正只发生在新的适配器/测试，未放宽原契约。失败 partial pack-v1 保留，相同 Case/Gold/Pin 字节复制到 pack-v2，未再次摄取来绕过问题。

隔离实例由既有 Docker Desktop 启动，随后只启动已核验标签的测试 PG；未执行 Seed、迁移、清库或删卷。Docker 的原 restart policy 同时启动已有演示容器，本轮没有向演示库发出业务查询/写入。实际验证仅连接 `datapilot_test_portable_311`：PG 17.11 + pgvector 0.8.6，固定 ONNX/tokenizer SHA。新候选镜像固定 `sha256:6c78a77b7ca5604bf4ac4ff8e725bc72370d550aef6c9c5b545eb27b8fa87339`，Python 3.11.14，原 SDK/锁文件不改。

开工前 **539 份文件** Hash 均不变，包括旧策略源码、Gold、Scorer、Seal、实验/规划记录；测试库 **27 张已有表、7,086 条原记录**的行 Hash 多重集全部保留，包括原 Evidence、Verification、Journal、Ledger、Checkpoint。只追加新公开 fixture 和本轮 7 Run＋1 原账本准入记录；首次 fixture 失败时已追加的数据也保留，没有删除。历史业务评测库和原 31/29、v3 Live、Dev Smoke 记录不重执行、不重评分。

## 待申请的单轮 Live 计划

当前 `authorization-template.json` 为 **authorized=false**；未填负责人/批准来源/有效期，旧授权不能复用。以后只有取得新的明确授权并保留其原文依据，才可创建一次性私密 Permit，绑定本 Manifest、全部资产和精确配置/Scope、Provider/模型、预算。候选在触碰模型前再次校验，旧/空/错 Scope/错配置/过期 Permit 均拒绝。

建议新授权上限：**同一 8 条公开 Dev、7 Runtime、56 次真实尝试、90,000 Token 计账单位、单 Run 8 calls/18k、Child 4 calls、输出最多 1,200、并发 1、Run 180 秒、总计 1,800 秒、重试 0、Thinking disabled**。沿用原单个 90k DurableLedger，不建立第二套预算。每个 Run 先预留完整 18k，已知实际量结算，未知结果保留且停止；90k **不保证**七个最坏情况 18k 全部执行，余额不足即停止，不能增额。新 Run/Pool ID 按本版 Freeze 与 fake/live 分离；不重复使用已有执行身份。

按 2026-10-29 免费核对的 [DeepSeek 官方费率](https://api-docs.deepseek.com/quick_start/pricing/)，峰值 USD/百万 Token 为缓存命中输入 0.006、未命中输入 0.3、输出 1.2；保守按最高单价计算费用上界估算 **USD 0.108**，不是供应商账单保证。未来执行前须重新免费核对费率；不得用 Key 查余额或付费探针代替。实际 Provider 只记录返回的 model ID/usage，不虚构更细后端版本或缓存收益。

Permit 在首次准入时必须至少覆盖完整 30 分钟加 5 分钟缓冲。执行前重查精确源码闭包、数据/Metric/Corpus/Document/IndexVersion/BGE、角色、未使用的 ID/账本、STOP 文件与当前配置。普通质量失败（包括英文控制）完整保留后继续；权限/伪造证据/协议/预算/Provider/unknown/超时/评分完整性异常立即停止，不自动重跑。`pack-v2/STOP` 只停止本版新派发，不能取消已经被供应商接收的费用。

剩余不确定性：真实 DeepSeek 是否遵守首查原问提示、如何选择工具参数、实际上下文/预算、引用选择、Token/延迟/费用尚未实测；英文/跨语言能力仍有明确边界。此次通过的是工程预检，不能承诺 Live 质量、稳定成功率、Web 端到端效果或供应商 exactly-once。本轮在准备完成后停止，等待独立 Live 授权，不自动优化英文、执行 Gate 3 或提交推送。
