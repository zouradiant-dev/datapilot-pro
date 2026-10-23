# P6C：可信本地单用户产品 Demo

本页保留 P6C 历史交付记录。当前新增 Chat-first 交互见 [P6C.1](chat-first-ui.md)；已有部署只追加 0007 并重启 API/UI，不重复 Seed 或重置数据。原上传、确认、ReportView、Journal 和恢复契约保持。

本轮只实现 P6C，保留 P1–P6B；不进入 P7/P8/P9/P10/P11，不自动 commit/push。基线 `fe05ba23197bb1577ce2ba7693a36d25b641f63f`。预检经 GitHub API 核对 **P6B** Actions `39717954797`（DataPilot checks / Python 3.11、3.13 success），不是尚未提交的 P6C CI。用户已有 v2.4 修改与新增 v2.5 Prompt 保持原样，不据此扩大阶段。

以上“未提交/CI 未运行”及下方本地验证是 **2026-10-23 推送前快照**。用户随后单独授权上传；推送后的提交与 Actions 状态以 GitHub 对应记录为准，不能把本地测试当作远端 CI。

## 实际实现与复用

| 边界 | 实现位置 | 复用与新增 |
|---|---|---|
| HTTP/安全 | web/app、contracts、body_limit | `/api/v1` 严格 DTO/OpenAPI、安全错误、实际接收字节/时间配额；Host/Origin/Session/CSRF |
| 宿主/请求 | web/config、store | 私密 bootstrap、哈希会话、owner/TTL/hash、版本 grant、幂等 outbox；客户端不能提交 scope |
| 业务入口 | web/service | 原 P1 解析确认、P2 事务导入、P3 语义/指标、P6A 授权摄取；不复制计算器 |
| 执行 | web/worker | 有界进程监管 + PG outbox；全部正常分析调用原 run_durable，无第二套 DAG/预算/Checkpoint |
| 状态/报告 | persistence/inspection、web/service | 官方 Saver 只读状态、工件/账本/P3 verdict 重查、安全报告/图表；NoModel 不能执行模型 |
| UI | web/client、ui | 纯 HTTP，覆盖上传/确认/指标/文档/分析/审核/取消/恢复/报告/Trace；不导入业务库/Runtime/MCP |
| 观测 | web/telemetry | 默认关闭，可选私密本地 OTel JSONL 白名单投影，不接远程 Langfuse |
| 维护 | persistence/retention、web/cli | maintenance 独立身份、默认 dry-run、显式计划 hash、整 Run/thread 原子清理及审计 |
| 数据库 | 0006_web_product、db/management、persistence/management | 新 web/maintenance grants；0001–0005 不改，官方 Saver 仍显式 runtime-init |
| 部署/验证 | Dockerfile、compose.demo.yaml、scripts/start_demo.ps1、四组 P6C tests | Windows/容器、API 独立 E2E、真实进程故障、隔离新库清理、安全反例 |

运行期业务仍经真实 MCP；模型无确认、导入 DDL、Shell、维护或任意文件工具。SQLGlot AST、grants、只读事务、超时/行数/输出上限保持生效。接口详见 [API 文档](api-v1.md)、[OpenAPI 快照](api-v1-openapi.json)，架构见 [ADR-013](adr/0013-local-product-boundary.md)。

## Windows 增量部署

在仓库根目录运行，已有数据库不再 Seed，不清表/删卷：

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked
uv run --locked python scripts/configure_local.py --add-web-roles
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot runtime-init
uv run --locked datapilot health
.\scripts\start_demo.ps1
```

配置脚本只向忽略的 `.env` 补缺失角色，保留原凭据；迁移到 0006，官方 Saver setup 不进入 HTTP/Worker。实际 health：PG **17.11**、pgvector **0.8.6**、240 位原合成客户。首次空环境按 README 初始化一次，不能把升级步骤当作重置。

默认 [UI](http://127.0.0.1:8501/)、API `127.0.0.1:8000`；Ctrl+C 停止 Windows 宿主。也可分终端：

```powershell
uv run --locked datapilot-web bootstrap
uv run --locked datapilot-web serve --mode fake
# 另一终端：
uv run --locked python -m streamlit run src/datapilot/web/ui.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

私密 `artifacts/web/host.json` 仅供可信服务端读取：Windows 目录 ACL 为当前用户 SID，Unix 0700/0600。UI 服务端用 secret 换取会话，浏览器没有 bootstrap secret/数据库凭据。运行实例 `/api/v1/docs` 和 `/api/v1/openapi.json` 同样要求宿主会话，不通过公开文档端点泄露内部契约。

旧 Dataset 不因知道 UUID 自动开放；宿主可显式 `datapilot-web grant <dataset_id> <version> --reviewed`。新上传确认/导入成功后建立 grant。不能以复制 Checkpoint 或修改 UI session_state 授权。

## Docker Demo

先完成增量 DB 初始化及 [RAG 模型缓存准备](rag-pipeline.md)，复用已运行的 postgres：

```powershell
docker compose -f compose.yaml -f compose.demo.yaml --profile demo build api
docker compose -f compose.yaml -f compose.demo.yaml --profile demo-init run --rm --no-deps web-init
docker compose -f compose.yaml -f compose.demo.yaml --profile demo up --no-deps --no-build -d api ui
docker compose -f compose.yaml -f compose.demo.yaml --profile demo ps
```

`--no-deps` 不重建 PG；不要 down -v、prune 或 reset。API/UI 共用锁定依赖镜像，API 从 `.env` 读取基础设施凭据并映射容器内部 `postgres:5432`。UI 不接收 `.env` 或 DB/模型 Key，只读私密配置卷，经 `http://api:8000` 调用 API。新增 `web_private` 保存私密文件；已校验权重只读挂载 `/app/.cache/rag-models`。容器内部监听 0.0.0.0，宿主仅发布 **127.0.0.1:8000/8501**；Streamlit 日志列出的网络地址不表示向公网发布。

实际构建/启动已执行，最终镜像与 Smoke 见结构化记录。初次 Docker Hub 鉴权网络失败后，改用官方 GHCR uv Python 基础镜像固定 digest，并复制显式 uv 0.12.5；未修改全局 Docker 凭据/镜像源。构建需要访问官方镜像和依赖注册表。

## 操作流程与验收边界

1. 上传 CSV/XLSX，或“加载合成 SaaS 样例”；审阅画像/Schema 并显式确认，随后受限入库。浏览器不接收原始行、examples 或物理表名。
2. 选择 Dataset/version；仅固定样例 hash 可读取映射建议，仍须人工确认实体/字段/单位/观察范围，再确认指标。任意数据须提供自己的真实映射。
3. 选已确认指标和右开时间窗口，创建任务；默认 awaiting_review，人工批准后刷新真实状态。样例 `[2025-10-01,2025-11-01)` paid-invoice revenue 为 **300 CNY**，不是 MRR。
4. 报告显示 P3 verified 数字、Evidence/Verification ID、版本/单位/时间/过滤及图表；Trace 显示调用关联/latency/usage 来源。刷新/断开依靠 PG 和授权 Run ID，不依靠 UI 缓存恢复。
5. 授权 TXT/MD 经真实本地 ONNX/pgvector 检索；缓存缺失明确失败，不自动下载/随机替代。默认 Fake 的 RAG 完成策略保守，可能为 partial。

Fake 只替代模型决策，未伪造 SQL、Embedding、检索、数值或 P3 verdict。完整跨来源 API 案例以明确标注的 ReportDecisions 脚本选择真实候选证据并校验；浏览器离线 Fake 的不足必须如实显示，不能把非空召回升级为 verified。没有新增付费 DeepSeek 调用。用户另行授权后可用 `start_demo.ps1 -Mode live`，先停止占用相同端口的另一部署；不能把历史 P6A 一次 Smoke 当作本阶段产品模型成功率。

## 恢复、失败与安全

outbox 幂等绑定 owner/操作/Run/载荷与授权 hash：同请求复用，冲突 409，并发只建一个 Run；默认每宿主 1/最多 2 个 PG 进程槽、20 条待派发命令。执行与业务完成状态分开，Pending/Review 不算完成。

- 真实进程故障：杀 API 后新进程依据原 P5B 有条件恢复。已提交 P3 metric 的 Evidence/Verification ID、body hash、原 verdict 不变，不重复调用或结算；新 Report 空账户不算额外扣费。
- 模型已 issued/结果未知：RECOVERY_UNCERTAIN、blocked、保留预算、人工对账，不盲目重发。429 类失败同样保守，不公开私密错误正文。
- 同键审核可重放；新键不能批准终态。终态 cancel 是 no-op；撤回数据授权后本人仍可停止，但不能读取数据/报告；取消不能掩盖 unknown。
- HTTP 独立反例：真实 XLSX/CSV/前导零、未确认导入、PG/MCP/P3、真实文档检索、猜 Run/Evidence、错 owner/撤回 grant/过期、Host/Origin/CSRF、路径注入/接收配额/遥测脱敏。
- 浏览器曾发现旧工件读取早于新 Checkpoint 的并发竞态，短暂拒绝报告。修复为先取官方状态，再读取已提交工件/刷新 P3 bridge；新增 PG 交错提交测试，不放松引用验证。
- 入队但未登记 Runtime 时，Trace 返回尚无观测的空列表；执行前已记录的失败显示 failed/blocked 和安全原因，不能一直显示 pending。对应真实 PG 反例已加入。
- 清理只在新建 `datapilot_retention_test_<uuid>` DB 中执行：dry-run 无副作用、review/hold/active/unknown 拦截、精确计划 hash、故障回滚、整 thread/账本/工件删除和审计。保留隔离库；原用户 Run/Volume 未删除。

数据地图、grants、TTL 和显式 CLI 见 [保留策略](data-retention.md)、[ADR-014](adr/0014-execution-retention.md)。无 HTTP 清理端点、自动清理或模型维护工具。

## 观测

默认 telemetry=off，FastAPI 自动遥测显式关闭。私密宿主配置可显式设 telemetry=local，授权 Trace GET 将白名单 OTel 投影写入私密 JSONL；失败不影响任务。这是事后观测投影，不宣称包含所有实时 provider 网络 span。

本项目不配置远程 exporter。若宿主此前自行开启 LangChain/LangSmith 全局追踪，应在启动前将 `LANGSMITH_TRACING=false`、`LANGCHAIN_TRACING_V2=false`，并移除自行注入的远程自动观测配置；不能将外部全局 SDK 设置误当作本地投影开关。Streamlit 启动已显式 `browser.gatherUsageStats=false`。

保留 Run/plan/task、脱敏 tool/model call、Artifact/P3 refs 和真实记录的 latency/usage/cache。Fake 明确为 mock；未知 cache 为 null，Journal replay 不冒充 Prefix Cache。没有可信价格/账单时 cost=null，不宣称实际费用或 SLA。SQL/Prompt/业务行/文档原文/Key/DSN 不导出。

## 实际验证记录

最终 JUnit 统计、时间、源码与部署产物 hash 见 [结构化记录](research/p6c-validation.json)。JUnit/截图位于忽略的 artifacts/p6c，不提交私密工件。以下均来自真实执行，重复运行不是额外独立业务任务：

| 日期 / 解释器 / 范围 | Passed / skipped | 耗时 | 本地产物 |
|---|---|---|---|
| 10-22 / Python 3.11.16 全量阶段快照 | 563 / 1 | 1158.749s | pytest-full-311.xml |
| 10-22 / Python 3.13.15 全量阶段快照 | 565 / 1 | 1206.552s | pytest-full-313.xml |
| 10-23 / Python 3.13.15 全量回归 | 566 / 1 | 1269.552s | pytest-final-313.xml |
| 10-23 / Python 3.11.16 P6C 含交错提交 | 26 / 0 | 464.541s | pytest-p6c-closeout-311.xml |
| 10-23 / Python 3.11.16 最后读取修正 | 2 / 0 | 198.033s | pytest-final-read-311.xml |
| 10-23 / Python 3.11.16 执行前错误/取消 | 1 / 0 | 21.851s | pytest-predispatch-final-311.xml |
| 10-23 / Python 3.13.15 冻结后全部 P6C | 26 / 0 | 456.895s | pytest-p6c-closeout-313.xml |

全量测试启动后仍补了最后的 Web 只读投影修正和交错提交反例，因此没有将全量计数冒称为最终源码再次全跑；最终源码由后续四组 P6C 26 项和 3.11 定向检查收尾。原业务计算/Loop/MCP 安全源码未改。全量唯一 skip 是显式付费 live 测试；真实 PG、MCP、Embedding、进程故障和清理测试未用 SQLite/Mock 替代。

实际使用已经 uv sync --locked 安装的 `.venv/Scripts/python.exe` 和 `.venv-313/Scripts/python.exe`；全量命令为 `-m pytest --junitxml=artifacts/p6c/pytest-final-313.xml --basetemp=artifacts/p6c/tmp-final-313 --tb=short -q`，最终专项使用下面四个测试文件及相应 JUnit/basetemp。Ruff 实际使用 `.venv/Scripts/ruff.exe check .` 与 `format --check --exclude docs/codex-prompts-v2.5.md .`，217 个文件格式通过。下列 uv 命令是相同锁定环境的复现方式。

浏览器/容器最终实测：样例上传/确认/语义与指标审阅、真实文档摄取、人工批准、300 CNY P3 报告/图表/Trace、证据不足的 partial、取消和 API/UI 替换后的读取均通过。完成 Run `b3356290-33c6-4ac4-b957-93b881fc841c` 的 Evidence `5c0143bc-edb1-485b-8223-f0282c684e19`、Verification `91e0dd31-5540-4827-86c2-35a96b9259e8` 及完整事实和模型调用键重启后未变。最终 API/UI 源码 hash 与本地 14 个部署文件一致；模型决策为 Fake，无付费 API。

```powershell
$env:DATAPILOT_RUN_DB_TESTS = '1'
Remove-Item Env:DATAPILOT_RUN_LIVE_TESTS -ErrorAction SilentlyContinue
uv run --locked pytest --tb=short -q
uv run --locked pytest tests/test_web_contracts.py tests/test_web_postgres.py tests/test_web_recovery_postgres.py tests/test_retention_postgres.py --tb=short -q
uv run --locked ruff check .
uv run --locked ruff format --check --exclude docs/codex-prompts-v2.5.md .
git diff --check
```

全目录 format 检查对用户新增 v2.5 Markdown 内嵌 Python 示例发出格式提示；保留文件，明确排除，不声称该全目录命令通过。续跑时 Docker 未启动，初次取消测试在 setup 连接超时：pytest-cancel-pg-stopped.xml 保留，启动原容器后重测通过。

## 未实现与风险

- 可信本地单用户，不是生产认证/多租户 RLS、KMS/TLS、跨主机 HA、不可篡改审计或供应商 exactly-once。
- 无远程 Langfuse、provider 切换/SLA/语义缓存/永久 Memory；未重新优化 P5A。
- 原件、Dataset/P3/RAG、过期会话和遥测独立保留；TTL 拒绝读取不等于物理清理。私密 DB/卷/备份仍需宿主管理。
- Saver 清理只支持已审计的锁定布局；未知版本、跨 Run 引用或 unknown 均 fail-closed。显式 purge 仍不可逆，开发不对原库执行。
- UI 按按钮刷新，无实时推送；Streamlit Session State 默认值可能产生服务端日志警告，不改变权限/结果。API 短暂不可用时可重连原 Run。
- 无新增付费产品 E2E、≥50 独立经营任务基准或产品胜率比较；P6C 不等于 P7 或整个 Gate D 完成。
