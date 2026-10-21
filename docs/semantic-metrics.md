# P3：SaaS 业务语义、指标与证据

本阶段实现 Roadmap v2 D6–D8 / Gate B，入口是显式版本化 `MetricRequest`，不是新的自然语言规划器。原 `ask` 仍是 Day 1 SaaS 查询路径；本节的六层验证与 Evidence 报告通过 `semantics run` 使用。没有新增 Multi-Agent、DAG、UI、RAG 或 Fork。

## 定义与确认

Pydantic 严格 DTO 位于 `semantics/contracts.py`，拒绝未知字段、错误类型和超限列表。定义先是 `SemanticDraft` / `MetricDraft`，经可信操作者显式 `--reviewed` 才登记版本；MCP 没有确认或写 Registry 的工具。默认政策也是供审阅的草案，不能把文件名、相似字段名或模型建议当确认。

| DTO | 关键内容与限制 |
|---|---|
| SemanticDraft / SemanticVersion | Dataset/version、saas-1、至多三个实体、每实体至多 16 个角色、真实列/粒度映射、单位/覆盖范围/历史完整性；确认后绑定源 hash 与定义 hash |
| MetricDraft / MetricVersion | 指标 ID、语义版本、saas_metrics_v1、币种、paid/churn/非 churn 枚举政策、可选 feature；枚举至多 8 个，值至多 32 字符；不可上传 SQL/Python 表达式 |
| MetricRequest / MetricContext | 显式 Dataset/语义/指标版本、唯一 goal_id、DATE 半开窗口或 as_of；上下文只含该指标实体/必需列，不含无关表、原始业务行或凭据 |
| MetricProof / MetricValue | saas-metrics-1、请求/context hash、独立 Python 计算、页 hash/行数；精确数字文本至多 80 字符，拒绝 float/指数/非有限值 |
| Evidence | 源 hash/version、语义/指标 hash/version、实际 SQL/query hash、QueryResult/result hash、复算证明、缺失信息；原始证据不自带 verified 标志 |
| VerificationRecord / ReportClaim | 六层有序状态、规则版本、派生终态与实际 Evidence 引用；最多 10 个目标，不能遗漏、重复或换源 |

JSON 操作输入最多 256 KiB；Registry 证据记录最多 2 MiB；沿用 SQL 单次 12,000 字符、单元格 4,096 字符、结果 1 MB、MCP 输出 3 MiB 及已有模型上下文/调用/Token 预算。窗口最多 3,660 天。所有日期为用户确认的 DATE；本阶段不猜测时间戳的时区/日期归属。

更改映射或指标政策只追加新版本，同一已确认定义幂等复用。旧 Evidence 不跟随 Dataset 当前指针或新口径变化。新 Dataset 版本必须重新绑定定义；请求不自动选择最新语义/指标版本。Operator 身份记录为本地 `local-user`，不代表生产认证。

## 已实现口径：saas_metrics_v1

以下均需操作者确认记录 ID 粒度、完整观测范围、时间列和字段映射。完整范围是业务声明，系统不能从有记录的首末日期推导完整性。声明不足、映射缺失/类型错误会返回具名 missing requirements，不执行猜测查询。

| 指标 | 可执行定义 | 不能替代的概念 |
|---|---|---|
| paid_invoice_revenue | 已确认 paid_values，invoice_date ∈ [start,end)，按记录 ID 粒度求金额；明确 major 或整数 minor÷100；币种列过滤或用户确认常量；首版只支持 CNY | 非 MRR/ARR、GAAP 确认收入、按实际支付日期的现金流 |
| subscription_churn | 分母为开始边界**之前瞬间**存续的合同：start_date < start 且 end_date 空或 ≥ start；分子为同队列中 start ≤ end_date < end 且 termination_kind 属于确认的 churn_values | 不以最终 status 充当历史快照；套餐周期不是合同；新增合同不进入期初分母 |
| customer_churn | 分母为上述期初队列的去重客户；分子为这些客户中，在结束边界之前瞬间没有任何存续合同者；同客户多个合同只计一次，期内重订阅且期末存续则保留 | 这是**期初客户队列期末净流失率**，不是所有取消事件率，也不是订阅流失率 |
| active_subscriptions | as_of 时 start_date ≤ as_of 且 end_date 空或 > as_of 的合同数 | 不用最终 active 状态推断任意历史时点 |
| usage | event_date ∈ [start,end) 的非负整数 event_count 合计；可选已确认 feature 精确过滤 | 不自动等同活跃用户/会话数；缺记录不自动当完整的零使用 |
| mrr | 可以登记定义版本；当前无可执行配方，明确返回缺经常性合约金额、计费周期、折扣/退款/币种政策 | 永不通过账单求和猜 MRR |

订阅指标要求 `history_complete=true`、`subscription_identity=contract`。原 Day 1 Seed 的 subscription 记录可能是套餐期间，不自动标成满足此条件。每个结束合同的 termination_kind 必须属于确认的 churn 或 non_churn_end 集合；未知分类不静默计入。负金额/退款、空必需字段、重复记录 ID、负/小数使用量、倒置有效区间均导致不能验证，需新的政策或数据修复。复算检查整张相关表，不只检查选中窗口的“好”行。

比率用 SQL 返回整数分子/分母，再由 Decimal 以 HALF_EVEN 保留 12 位小数；分母零是不可计算。时间长度由 Python date 相减。不同分母/客户流失定义不是自由文本覆盖项；若需要其他业务政策，必须新增受审查的 policy/computation 版本及 Gold，不覆盖本版本历史定义。

## 六层验证与报告

1. **安全**：SQLGlot PostgreSQL AST、每请求物理表范围、真实 SELECT grants、只读事务、超时/锁超时与 LIMIT。原函数/语句白名单未放宽。
2. **结果形状**：一行完整 scalar 或 numerator/denominator，精确有限数值、无截断、实际查询/结果 hash 和来源一致。
3. **指标语义**：已确认版本、字段类型/粒度、币种/单位/窗口、覆盖范围；候选 SQL AST 与封闭配方的规范 AST 一致。保守拒绝其他写法，即使某些 SQL 可能等价。
4. **独立复算**：MCP 以另一条原始列投影读取，在单独 REPEATABLE READ + READ ONLY 快照中分页；Python 自己选队列、过滤和求和，未复用 SQL WHERE/聚合结果。与 SQL 数值、单位、分子分母和时长一致才通过。
5. **引用**：先追加保存 raw Evidence，再经授权 MCP 读回；检查引用确实存在、内容 hash、源版本、请求/指标/计算与所有原始工件一致。Verification 独立追加保存。
6. **目标覆盖**：每个 goal 恰好一个同请求/来源的 claim；数值须引用已通过的 Verification + Evidence；不能计算必须明确缺失原因。描述性证据不能升级成因果结论。

六层全过为 `verified`；没有 failed 且有不适用层为 `unavailable`；任何 failed 为 `rejected`。复算上限 20,000 行、256 页、8 MiB 累计投影 JSON，逐页仍受现有行数/字节/statement_timeout 限制，循环有五秒协作期限（进行中的单条 SQL 仍由数据库超时约束）。超限、不完整或异常直接不给已验证数字。分页只在服务端内部发生，原始行不进入 Worker/模型或报告。

报告由已校验的结构化 claim 确定性渲染；每个数字行与版本/时间行均携带 Evidence/Verification ID。MRR、因果请求、零分母、缺映射/覆盖范围等输出不能计算及 missing fields。原始 Evidence 可能保存未通过的 SQL 候选数值，只有单独的 Verification 决定是否允许发布。无自由文本 LLM 报告被当作验证事实。

## 安装升级与复现

已有 P2 环境保留数据库、卷和密码，不重复 Seed：

```powershell
uv run --locked python scripts/configure_local.py --add-registry-role
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot health
```

新 0003 迁移仅追加四表；0001/0002 不修改。独立 `datapilot_registry` 仅有 catalog 元数据 SELECT 和新四表 INSERT，不能读 saas/uploads/rag、UPDATE/DELETE 历史、建表、提权或继承其他角色。Owner 执行迁移；upload_reader 只获得新元数据 SELECT。所有业务查询/复算/证据读取继续经过真实 MCP。Registry 写入是可信宿主基础设施通道，不是模型工具；MCP 环境不继承 Registry DSN。

公开合成样例在 `tests/fixtures/semantics/`，生成器 `data/semantic_demo.py` 使用固定内容与时间。以下确认开关只适用于仓库合成数据，不可拿来批准未知真实数据：

```powershell
$demoDir = 'artifacts/semantic-demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
uv run --locked python scripts/prepare_semantic_demo.py --reviewed-synthetic --output $demoDir
uv run --locked datapilot semantics run "$demoDir/requests.json" > "$demoDir/report.json"
$report = Get-Content "$demoDir/report.json" -Raw | ConvertFrom-Json
$report.markdown
$first = $report.outcomes[0]
uv run --locked datapilot semantics evidence $first.evidence_id --dataset $first.request.dataset_id --version $first.request.dataset_version
```

该入口 `execution_mode=deterministic`，不调用 Fake 或真实 LLM。合成 October 2025 Gold：收入 300 CNY、订阅流失 4/6、客户净流失 2/5、October 31 活跃合同 4、使用量 35；MRR 不可计算。它们是测试样例事实，不是任何真实企业指标。

真实文件继续走 P1/P2，再人工填写/审阅映射和指标 JSON（样式见生成的 mapping.json 与各指标文件）：

```powershell
uv run --locked datapilot semantics confirm-mapping artifacts/my-mapping.json --reviewed
uv run --locked datapilot semantics confirm-metric artifacts/my-metric.json --reviewed
uv run --locked datapilot semantics run artifacts/my-requests.json
```

`SQLAgent.run_metric` 也支持由宿主注入已有预算化 ModelClient 提议 SQL，仅提供最小确认上下文，仍需封闭配方校验；本阶段没有新增 live CLI，也没有以确定性测试声称真实模型 E2E。尚未确认的定义返回 `SEMANTIC_NOT_CONFIRMED` / `METRIC_NOT_CONFIRMED`，不能捏造可持久化的已确认版本。

## 边界

这是本地单用户的 SaaS 首版：固定受审查配方、单个 Dataset 内指标、CNY/DATE、可信本地确认。没有生产认证、跨租户隔离、FX、复杂收入确认、可执行 MRR、因果识别、任意自然语言目标判定或自动修复业务口径。Hash 不能证明原件真实；ingest/owner 是可信基础设施，应用不可变不等于数据库 WORM。MCP 原始投影快照与主查询是独立快照，不同则拒绝，不宣称跨工具全局事务。后续代码语义变化须新 computation/rule 版本；完整历史引擎回放和长期代码制品保管仍属后续治理。
