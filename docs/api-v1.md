# 本地 HTTP API v1

这是 P6C 的可信本地单用户接口。默认 API `http://127.0.0.1:8000`、UI `http://127.0.0.1:8501`；不是公网多租户认证。完整机器契约见 [OpenAPI 快照](api-v1-openapi.json)，运行实例的 `/api/v1/openapi.json` 同样要求宿主会话。

## 身份与确认

宿主通过 `datapilot-web bootstrap` 在忽略的私密目录生成配置。UI **服务端**读取 bootstrap secret，向 `POST /api/v1/session` 提交 `X-DataPilot-Host-Key` 和配置的 `Origin`，取得 HttpOnly/SameSite=Strict 会话 Cookie 与 CSRF 值。密钥不进入浏览器、模型或 URL。Cookie 仅是宿主已发放会话的随机句柄；实际 owner 固定在宿主配置和 PostgreSQL 会话记录中。

后续请求携带 Cookie；POST 还必须携带 `X-CSRF-Token` 与匹配的 `Origin`。所有请求检查 Host。无跨域通配、无客户端 owner/权限字段、无任意工件或文件路径接口。当前 Streamlit 从服务端发 HTTP 请求；未来浏览器客户端需采用可信同源代理或单独设计登录/CORS，不能把宿主 secret 打包进前端。

Schema、业务映射、指标定义和任务审核都需要明确的人工确认。模型没有相应 HTTP/MCP 写工具。Dataset UUID、Run UUID、Evidence ID 及摘要文本都不授予访问权。

## 路由与契约

所有业务路径以 `/api/v1` 开头。JSON DTO 拒绝额外字段，日期使用 ISO 格式；金额为精确十进制字符串，不能在客户端用浮点重新定义指标。

| 方法 / 路径 | 输入 / 输出 | 行为 |
|---|---|---|
| POST `/session` | HostBootstrap → SessionView | 发放 8 小时本地会话 |
| GET `/health` | → HealthView | 检查 Web 元数据访问，标明 fake/live 与 Durable；完整数据库健康另用 CLI |
| POST `/uploads` | multipart file + ParseOptions JSON → UploadView | CSV/XLSX 有界解析；不返回业务原始行 |
| POST `/samples` | → UploadView | 只读取仓库内固定合成 XLSX，仍需确认后入库 |
| GET `/uploads/{id}` | → UploadView | owner、hash、TTL 检查后的画像与 Schema |
| POST `/uploads/{id}/confirm` | SchemaReview → UploadView | 重读原件、验证 proposal hash 与用户覆盖 |
| POST `/uploads/{id}/import` | ImportUpload → ImportResult | 原 P2 事务导入；成功后建立宿主版本 grant |
| GET `/datasets` | → DatasetViews | 只列宿主已授权版本，不返回物理表名 |
| GET `/datasets/{id}/versions/{v}` | → DatasetView | 通过原 MCP 重核 source/version/schema |
| GET `/datasets/{id}/versions/{v}/sample-mapping` | → SemanticDraft | 仅当源 hash 等于提交的合成样例时提供建议，不自动确认 |
| POST `/semantics/confirm` | SemanticReview → SemanticVersion | 复用原 P3 追加版本，写操作仅在宿主 |
| POST `/metrics/confirm` | MetricReview → MetricVersion | 明确单位/过滤/口径，不能用收入替代 MRR |
| POST `/datasets/{id}/versions/{v}/documents` | multipart file + reviewed → DocumentIngested | 授权 TXT/MD → 原 P6A 本地 Embedding/pgvector；无任意 URL 摄取 |
| GET `/corpora` | → CorporaView | 只列授权 corpus/index 版本引用，不返回正文/向量 |
| POST `/tasks` | CreateTask → Acknowledgement | 宿主确认 MetricRequest/文档范围，写幂等 outbox |
| GET `/tasks` | → TaskIDs | 最近 30 个未过期授权 Run ID |
| GET `/tasks/{run}` | → TaskView | 官方 Checkpoint/预算的只读投影；不执行恢复或调用模型 |
| POST `/tasks/{run}/{approve,resume,cancel}` | TaskAction → Acknowledgement | 可信审核/安全恢复/取消；不清除未知外部结果 |
| GET `/tasks/{run}/report` | → ReportView | 重新验证 P3/P4/RAG 后发布聚合事实及引用 |
| GET `/tasks/{run}/evidence/{id}` | → MetricFact | 只能读取该已授权报告实际引用的 P3 事实 |
| GET `/tasks/{run}/trace` | → TraceView | 脱敏关联、真实已记录 latency/usage；不返回 SQL/Prompt/原文 |

## 任务、幂等与错误

创建、批准、恢复、取消要求 8–128 字符的 `Idempotency-Key`。宿主将键绑定 owner、操作、run_id、规范载荷 hash 和授权版本；同请求复用原响应，异请求返回 `WEB_IDEMPOTENCY_CONFLICT`。批准重试可在任务继续后重放同一确认，但新键不能批准已经结束的任务。

TaskStatus 为 `pending / running / paused / awaiting_review / partial / unavailable / blocked / failed / completed / cancelled`。`execution_status` 是原 Runtime 的执行状态；`business_completion` 是原 P6B 的目标覆盖结论，两者不能互相冒充。Pending、等待审核、检索非空都不代表业务完成。无可验证证据时报告接口返回 `REPORT_NOT_READY`。

`RECOVERY_UNCERTAIN` 表示调用已发出但无法确认结果，必须保留原预算并人工对账。不得用新 Run/新键自动掩盖或重发。取消只减少执行权限，不扩大数据访问；即使来源 grant 已撤回，宿主仍能取消自己的未过期 Run。已完成运行的取消是幂等空操作，不重新启动图或修改证据。

错误统一为 `{"schema_version":"api-v1","error":{"code":"...","message":"...","retryable":false,"manual_action_required":false}}`。403 表示授权/版本/确认拒绝，409 表示幂等冲突或已有命令处理中，413 为接收配额，422 为 DTO/解析不通过，500 为安全的内部错误摘要。响应不包含原始异常回溯或凭据。

## 有界资源与隐私

上传原件最多 10 MiB，沿用 P1 的行/列/Sheet/解压/解析时间上限。ASGI 在 JSON/multipart 解析前对实际流累计字节和接收时间做限制，含 chunked 请求；普通 POST 上限 384 KiB。文档最多 256 KiB，格式限定 TXT/Markdown；本地模型缓存缺失时明确失败，不自动下载或回退 fixture。

每个宿主默认 1 个执行进程槽，最多 2 个；默认最多 20 个待派发命令。进程槽及 Run 锁由 PostgreSQL advisory lock 控制，API 重启后以 outbox 和原 P5B 状态有条件续行。没有第二套 Agent Scheduler、计费账本或 Checkpointer。

报告保留 Dataset/source hash、Semantic/Metric 版本、原 P3 Evidence/Verification hash、时间/单位/过滤与 RAG chunk 定位；只提供已验证聚合、引用元数据及安全 Markdown。原业务行、SQL、文档正文、完整工件和 Checkpoint 不可下载。生产认证、TLS/KMS、RLS、分页/存储运维和长期保留制度另行验收。
