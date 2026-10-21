# DeepSeek Flash 最小 Live Transport 适配

日期：2026-10-21。范围：P5A 后单独授权的供应商兼容增量，不推进 P5B/P6，不增加 RAG/UI/Checkpoint。

## 官方接口与本地基线

核对 [DeepSeek 快速开始](https://api-docs.deepseek.com/quick_start/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考与工具循环](https://api-docs.deepseek.com/guides/thinking_mode/)。文档当前列出 `deepseek-flash`，默认开启思考；带 tools 的思考请求要求回传历史 reasoning_content。本次仅启用非思考模式，不承诺该附加字段的完整支持。

实际检查锁定的 `langchain-openai==1.7.2`：ChatOpenAI 将 `max_tokens` 改写为 `max_completion_tokens`，并且不提取供应商特有 reasoning_content。DeepSeek 官方列出的输出限制参数是 `max_tokens`；因此采用公开 extra_body 注入，不修改依赖源码或覆盖私有方法。

## 实现与使用

- `Settings.model_provider` 只能取 `openai_compatible`（默认）或 `deepseek`，不按模型名称猜供应商，不静默切换 Fake。
- `llm/provider.py:create_chat_model` 是共享构造入口，NativeTransport 与旧 JSONModelClient 共用。DeepSeek profile 固定 `use_responses_api=False`，不设 ChatOpenAI 的 max_tokens 字段，改在 extra_body 中发送 `max_tokens=settings.max_output_tokens`、`thinking={type:disabled}`。HTTP Mock 实际捕获最终 JSON，确认字段位于顶层且没有 max_completion_tokens。
- 原 NativeTransport 的 bind_tools/ainvoke、Gateway 的输入预算与用量结算、P5A 摘要入口、取消和错误脱敏保持原路径。SDK retry=0，错误由原 Loop/图机制按现有规则处理，不增加一层供应商重试。
- 不添加强制 JSON response_format/strict beta；Planner/最终响应继续由原 Pydantic 契约验证，Worker 继续使用原生 tool calling。工具 ID/参数/权限与 Evidence 引用检查不变。
- 保持现有依赖锁、数据库角色、SQLGlot、只读事务、超时/行数/输出限制和真实 MCP 边界。

在仓库本地 `.env` 设置：

```dotenv
DATAPILOT_LLM_MODE=live
DATAPILOT_MODEL_PROVIDER=deepseek
DATAPILOT_BASE_URL=https://api.deepseek.com
DATAPILOT_MODEL=deepseek-flash
DATAPILOT_API_KEY=
```

Key 填入本地空值处；不要粘贴到聊天或公共日志。也支持 `https://api.deepseek.com/v1`；两种 URL 均经 HTTP Mock 验证路径。默认输出 1200 tokens、超时 30 秒与现有运行预算不扩大；复杂请求可由用户在原配置允许范围内调整。

```powershell
uv run --locked datapilot health
uv run --locked datapilot ask '查询客户总数' --mode live --json
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_RUN_LIVE_TESTS='1'
uv run --locked pytest tests/test_live_model.py -q
```

最后两行会真实调用外部模型并消耗供应商额度，需事先在本地配置自己的 Key。`--json` 是本地诊断输出，可能包含业务工件，勿公开真实数据。

## 验证边界与风险

新增 `tests/test_deepseek_transport.py`，用真实 LangChain/OpenAI SDK 配合 httpx.MockTransport 捕获 HTTP；不是 Mock 一个 respond 函数，也不是供应商端验证。10 个本地用例覆盖两个 base URL、content=null 的原生工具回合与 ID 配对、用量、无工具 Planner、旧同步客户端、401/429/500 单次请求与脱敏结算、超时取消、通用 profile 不回归、错误 profile/缺 Key 拒绝。

另有独立 integration 用例：HTTP 决策仍为 Mock，经 run_question → 原图/Worker → 真实 MCP → PostgreSQL 查询客户数 240，再回传真实工件引用，不把这个测试命名为真实 DeepSeek E2E。原 CSV/XLSX→PG、MCP、SQL 安全和语义/上下文测试包含在完整回归中。

本轮实际执行（仓库根目录、Python 3.11.16；原锁定依赖不变）：

| 命令 | 实际结果 | 边界 |
|---|---|---|
| `python -m pytest tests/test_deepseek_transport.py -m 'not integration' -q --tb=short -p no:cacheprovider --basetemp=artifacts/deepseek/targeted --junitxml=artifacts/deepseek/targeted.xml` | 10 passed, 1 deselected，2.01 秒 | 供应商 HTTP Mock，无网络推理 |
| `uv run --locked --offline pytest -q --tb=short -p no:cacheprovider --basetemp=artifacts/deepseek/regression --junitxml=artifacts/deepseek/regression.xml`，DB opt-in=1、live opt-in=0 | **383 passed, 1 skipped，98.51 秒** | 包含真实 PostgreSQL/MCP 与新增闭环；唯一 skip 是 opt-in live |
| `uv run --locked --offline pytest tests/test_live_model.py -q --tb=short -p no:cacheprovider --basetemp=artifacts/deepseek/live-pytest --junitxml=artifacts/deepseek/live-pytest.xml`，DB/live opt-in 均为 1 | **1 passed，5.25 秒，0 skipped** | 2026-10-21 15:53 正式补跑此前 skip 的真实 DeepSeek→MCP→PG pytest |
| `ruff check .`、`ruff format --check .` | 均通过 | 静态/格式检查 |

真实 XML 仅保存在忽略的 artifacts/deepseek/；以上通过数来自执行，不把计划验收项计入结果。

初始回归时真实 Key 缺失，故上表唯一 live pytest 保持 skip；不将后续 smoke 追记成该 pytest 通过。用户随后在本地配置 Key，2026-10-21 使用原 `Settings(llm_mode='live')` 与 `run_question('查询客户总数', include_artifacts=True)` 实际复测一次，模型为 deepseek-flash，真实 MCP/PG 返回 `customer_count=240`，`status=succeeded`、`completion=completed`、SQL 任务验证 passed，生成实际工件引用。2 次模型调用，reported/total tokens 均为 2297、usage_complete=true；整个 Run 耗时 3.66 秒。完整本地记录为忽略文件 `artifacts/deepseek/live-count-20261021T075128848960Z.json`，不提交原始工件。

用户进一步授权补跑后，实际运行 `tests/test_live_model.py::test_real_model_postgres_workflow`：**1 passed in 5.25s**。该用例断言 live 模式、执行 succeeded、真实结果 `[[240]]`；JUnit 中 tests=1、failures=0、errors=0、skipped=0。这是正式 Live pytest 通过，区别于此前独立 smoke；没有再次执行全量测试，不能将上述历史完整回归改写为同次运行 384 passed。

后续单独授权 P5A 真实压缩 A/B 实测：20 次 DeepSeek 调用、75,304 tokens，16 组执行通过，源数据走真实只读 MCP/PG，长历史明确为宿主回放。L4 的真实摘要额外成本已计入且出现费用/时延负面结果；另跑完整回归为 388 passed、1 个主动关闭的 live skipped，见 [详细实测](p5a-live-context-ab.md)。没有扩大为复杂 SaaS 业务评测。

隔离网络环境的首次请求返回 MODEL_ERROR，无 SQL 结果；允许联网后同一配置成功。失败调用未知用量按原账本保守预留，不记为成功调用或已确认供应商消耗。终端输出未附加到聊天，以上是独立复测，不声称读取了用户原终端结果。

这只证明一个真实模型客户数闭环；没有验证真实工具选择总体正确率、复杂经营指标、账号余额或缓存/费用收益。思考模式、reasoning_content、流式输出与 Responses API 不属于本次交付；若后续启用思考，需单独验证历史保留、P5A 压缩、归档和 Token 预算，不能只增加开关。
