# P7 Browser Demo & Showcase Acceptance

2026-11-01，分支 `p7-engineering-candidate-v1`，展示文档提交 `e42277c`。本轮在**全新隔离的合成环境**中使用真实 Chrome 操作现有 Chat-first 产品，采集 Browser Demo 素材；没有修改产品源码、测试、Migration、工作流或冻结记录，没有调用付费模型，没有 Git Commit/Push。

> 修复后续：本页的 RAG `RAG_QUERY_POLICY` 失败与“失败状态不可见”结论已由 [Browser Demo Recovery](p7-browser-demo-recovery.md) 复核并修复。RAG-only 与 SQL+RAG 现已在新的浏览器 Run 中 completed；失败 Run 的 failed/blocked 投影也可在 UI 看到。本页保留为当时的验收快照。

机器记录（local-only）：`artifacts/showcase-browser/20261101-demo/evidence/acceptance.json`。截图目录：`artifacts/showcase-browser/20261101-demo/screens/`（默认不提交 Git）。

## 结论

| Gate / 维度 | 结果 |
|---|---|
| **Browser Demo Acceptance** | **PARTIAL** |
| Environment Safety | **PASS** |
| Chat-first UI | **PASS** |
| Goal Confirmation | **PASS** |
| Independent Approval | **PASS** |
| SQL-only | **PASS** |
| RAG-only | **NOT_RUN** |
| SQL+RAG | **FAIL**（RAG Worker 被宿主 `RAG_QUERY_POLICY` 拒绝，未伪造成功） |
| P3 Evidence | **PASS**（SQL） |
| Actual Browser Screenshots | **8 张**（见下） |
| Paid Model Calls | **0** |
| Product Core Changes | **NONE** |
| Git Commit / Push | **NOT_AUTHORIZED（未执行）** |

## 1. 环境与隔离（Gate A：PASS）

启动前 Docker Engine 已停止；启动后核对：

| 项目 | 实际值 |
|---|---|
| Docker Engine | 29.9.1（Docker Desktop 4.96.0） |
| 启动时状态 | **0 containers / 0 volumes / 0 images**，未挂载历史 35.88 GiB 数据盘 |
| 本轮 Compose 项目 | `datapilot-showcase-20261101` |
| 本轮 Volume | `datapilot-showcase-20261101-pgdata`（新建） |
| PostgreSQL | 17.11，`pgvector` 0.8.6 |
| Migration | `0008` |
| Seed | 240 客户，2271 账单，事务化一次 |
| 端口 | `55432` / `8000` / `8501`，仅 loopback |
| 历史容器/卷 | 当前引擎中不存在，未启动、未删除、未 prune |
| 禁止命令 | 未执行 `down -v`、`volume prune`、`system prune`、factory reset、磁盘切换 |

结论：本轮使用**空的当前引擎 + 新项目/新卷/新库**；历史 Docker 数据盘未被挂载或写入。未对历史数据完整性作任何声明。

## 2. 初始化与产品启动

```powershell
docker compose --env-file .env -f artifacts/showcase-browser/20261101-demo/environment/compose.showcase.yaml up -d --wait
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot runtime-init
uv run --locked datapilot seed
uv run --locked datapilot health
uv run --locked datapilot-web --host-file artifacts/showcase-browser/20261101-demo/private/host.json launch --mode fake
```

`health`：`healthy`，PG 17.11 / pgvector 0.8.6 / migration 0008 / 240 客户。Web 健康接口返回 `mode=fake`、`durable=true`、`telemetry=off`；`DATAPILOT_LLM_MODE` 被强制为 `fake`，未调用 Provider。

初始化后通过可信 Host API 一次性准备：

- 上传 `tests/fixtures/demo/engineering-v1/invoices.csv`，确认 Schema，受限入库为 Dataset `263248a1-4eb1-5a22-947a-ef325687de8f` v1；
- 人工确认 Semantic v1 与 `paid_invoice_revenue` Metric v1（`amount_storage=minor`、CNY、窗口 `[2026-06-01,2026-07-01)`）；
- 授权 `billing-guide.md`，真实本地 BGE 摄取：`embedding_fixture=false`，Corpus `a53942ba-8c63-4d45-ac67-b63edf7752b3`，IndexVersion `bd80b8c2…`；
- 通过真实只读 MCP 会话独立复算 Gold：**1432.25 CNY**（100025 + 43200 分；unpaid、7 月、USD 行被排除）。

BGE 权重 SHA256 与仓库冻结值一致：模型 `1294ea4b…`，tokenizer `48cea5d4…`。

## 3. 浏览器操作与四类展示

浏览器：**Playwright 1.64.1 驱动本机 Google Chrome**（`channel=chrome`），真实 Streamlit WebSocket 与 FastAPI HTTP；不是 Streamlit AppTest，也不是 HTTP Mock。窗口 1440×1200（合同页 1440×1600）。

| # | 场景 | 截图 | 实际状态 |
|---|---|---|---|
| 1 | Chat-first 对话入口 | `screens/01-chat-first.png` | 用户问题、候选卡片、指标/窗口、侧栏历史与“执行需审批”提示；该消息随后在同一会话执行 |
| 2 | Goal v4 合同确认 | `screens/02-goal-confirmation.png`、`02b-goal-contract-full.png` | 完整合同：原问、Dataset/version、Metric/窗口、Source/IndexVersion、限制、三项勾选；**展示用 pending 合同，未提交执行**，截图后已 reject |
| 3 | 独立 Journal 审批 | `screens/03-execution-approval.png` | `awaiting_review`、`execution_status=pending`、预算 8 次/18000 Token、审批勾选与“批准执行”；展示用 Run，截图后已 cancel（0 模型调用） |
| 4 | Agent 执行状态 | `screens/04-agent-execution.png` | SQL 与 report 任务均 `succeeded`，节点执行明细与 P3 数值 |
| 5 | 可信报告 | `screens/05-evidence-report.png`、`05b-evidence-report-full.png` | 1432.2500000000000000 CNY、Evidence/Verification、completed |
| 6 | 证据来源 | `screens/06-evidence-sources.png` | `verified_facts` JSON：dataset/version、metric/version、window、hash |

说明：场景 2/3 的截图来自**展示专用**的 pending/awaiting 状态（未执行），因为实际 Run 的确认与审批发生在同一浏览器会话中但截图时已越过该状态；实际执行证据是场景 4/5 的 SQL Run。两者使用同一 UI、同一可信 API，没有复制或伪造状态。

## 4. SQL 证据链（PASS）

| 项目 | 值 |
|---|---|
| Run | `02501271-8c39-4877-a235-bd86aaf5ac5e` |
| 终态 | `completed` / `succeeded` / `completed` |
| 数值 | **1432.2500000000000000 CNY** |
| Evidence | `31bf18f2-c304-4d1c-8567-8d478ee63cfd` |
| Verification | `741aa34a-328b-42c5-adf5-971a6fedb890` |
| Source SHA | `0211d016d75328b89fcc92776ef234fd9897b14928a4276bb15d4b965ec1b3e1` |
| 任务 | `metric_1` sql succeeded；`report` succeeded |
| 模型 | Fake / `scripted-fake`，Provider 实际调用 0 |

报告由原 P3/Report 链路生成；数值经真实 MCP SQL 与独立复算，UI 显示精确 Decimal 字符串而非浮点。

## 5. RAG / SQL+RAG：如实失败

组合 Run `fcae43d0-f2cd-472f-91d5-876b7df6a33c`：

- SQL 指标任务 succeeded 并产生 P3 证据；
- RAG 文档任务 failed，宿主返回 **`RAG_QUERY_POLICY`**（默认 Fake transport 生成的检索查询与宿主绑定的文档目标不完全一致，被原守卫拒绝，符合“不得绕过授权”的设计）；
- `execution_status=failed`，`business_completion=blocked`，缺失项为 `matching_document_or_metric_evidence_missing`、`required_document_source_missing`；
- 没有发布文档 citation，没有把 blocked 升级为 completed。

RAG-only 本轮**未单独执行**。历史 P7 的 SQL+RAG 成功使用专门的脚本化决策并由独立冻结记录证明，**不能作为本轮默认 Fake 浏览器成功证据**。

补充观察：该 failed Run 在 Streamlit 中只渲染到合同确认区，未显示错误/blocked 详情（页面后续内容缺失）。这是产品 UI 的失败投影缺陷，本轮未修改产品，只记录；不影响 API 侧真实状态与上述证据。

## 6. 证据分层

| 层 | 本轮内容 |
|---|---|
| 真实浏览器 | Chrome + Playwright 自动点击/勾选/审批/截图；非人工手动，非 AppTest |
| FastAPI HTTP | 会话、上传、确认、入库、文档、聊天候选、审批、报告全部真实 |
| 后端 PG/MCP | PG 17.11/pgvector、真实 MCP SQL、P3 六层；RAG 摄取真实 BGE，RAG 查询被守卫拒绝 |
| 历史冻结验收 | P7 五 Run 仅作背景引用，未恢复、未重放、未改写 |
| 未使用 | Streamlit AppTest、HTTP Mock、付费模型、旧 Run/合同/Source Hash 授权 |

## 7. Gate 评估

- **Gate A Environment Safety：PASS**。空引擎、新项目/新卷/新库；未触碰历史卷或数据盘；未执行禁止命令。
- **Gate B Browser Reality：PASS（有界）**。真实 Chrome 渲染与交互；截图来自实际页面；自动化而非人工鼠标操作，已如实标注。
- **Gate C Business Evidence：PARTIAL**。SQL 数值、Evidence/Verification 真实；RAG 引述未取得，组合业务完成被阻断。
- **Gate D Presentation Quality：PASS**。截图可读、无凭据/连接串/本机路径；Fake 与真实服务边界在页面与报告中明确。

## 8. 局限与下一轮最小改进

1. **默认 Fake 不能完成真实 RAG**：Fake transport 的查询与 host-bound goal 不一致，被 `RAG_QUERY_POLICY` 拒绝。若要在无付费模型前提下展示 SQL+RAG，需要宿主提供**精确的脚本化检索决策**（不放松守卫），或显式授权的真实模型 Run；本轮不修改产品。
2. **UI 未投影 failed Run 详情**：组合失败后页面只显示到合同确认，未显示错误与 blocked 证据；建议下一轮单独审计用户可见失败投影（需产品修改授权）。
3. **展示截图 02/03 非“执行瞬间”**：实际确认/审批已由浏览器完成，但截图使用展示专用 pending/awaiting 状态；严格展示应下一轮在同一实际 Run 上一次性采集。
4. **截图公开展示**：01/03/04/05/06 可直接用于 README 的 Chat-first、审批、执行与 SQL 证据链；02 需注明“有限合同展示”；**不得用本轮素材宣称 SQL+RAG 成功**。是否把图片纳入仓库由用户另行决定（当前 local-only，未提交）。
5. **人工语义审查**仍为 `NOT_VERIFIED`；本轮不涉及。

## 9. Git 与保留边界

- 新增本地成果：`artifacts/showcase-browser/20261101-demo/`（截图、日志、Host 私有配置、机器记录，均被 Git 忽略）。
- 新增本地报告：本文件（未提交）。
- 既有 8 份未跟踪研究文件保持不变，未混入本轮结果。
- 未修改 `src/`、测试、Migration、`.github/`、README、架构图；未 Commit、未 Push、未合并 main、未改变仓库 Private 状态。
- 隔离容器与 Volume 保留用于复核；未删除。
