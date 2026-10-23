# P6C.1：五项审查问题的最小修复

状态：最终冻结源码的双版本回归与本地部署验收通过。基线 `85e5652bbb57e6099021c88e8a09b8c6d6fa68c3`。本轮用户授权通过后提交、推送并核对 GitHub CI；不进入后续阶段，不调用付费模型。

## 范围与根因

修复开始时，原 P6C.1 增量尚未提交。本轮在该工作区完成以下修复，保留原 Conversation/Message、Outbox、审批与 Durable/P3/RAG 机制。

| 问题 | 最小修改 | 正式反例 |
|---|---|---|
| 明确拒绝的消息锁住聊天输入 | `ui_chat.append` 只在 `WEB_VALIDATION` / `WEB_BODY_LIMIT` 这种提交前校验拒绝时释放待重试意图；网络异常、内部错误和未知结果保留原 body/key | 1 个 Streamlit HTTP Mock 用例 |
| 多时间窗口被缩为单月 | `intent.parse_window` 在相对月、ISO 年月、中文/阿拉伯数字月份之间统一检查窗口数量；多个窗口不自动选第一个，要求澄清 | 3 个混合表达参数用例 |
| 冲突指标被替换为已支付收入 | `intent.resolve` 在选择器和收入关键词匹配之前拒绝英文 MRR 全称、未支付收入；仍不引入新配方 | 2 个口径参数用例，同时检查显式选择器不能覆盖冲突 |
| Corpus 列表截断影响授权 | 原 `WebStore.corpora` 增加可选精确 corpus_id 过滤；`task_payload` 使用此过滤，不再从列表第一页推断授权全集。owner、启用 Dataset、版本、pin/hash 检查保留 | 1 个真实 PG/MCP/本地 ONNX 用例，含原 Run、超 100 元数据、精确读取和坏 hash 拒绝 |
| 旧任务入口接受 NUL | 将原 MessageCreate 的 JSONB 文本校验复用为 Web DTO 的 `DatabaseText`，同时用于 CreateTask、DocumentQuery 和 MessageCreate | 1 个真实 PG/HTTP 用例；NUL 和孤立 surrogate 均应返回 422 |

8 个有效失败反例纳入 `tests/test_chat_review_regressions.py`，没有删除原断言或其他有效测试。修复前正式文件真实运行 **8 failed / 35.42 秒**；修复后 **8 passed / 30.97 秒**。加入 pin/hash 和选择器关联断言后，连同原 Chat DTO/UI 与管理页 ACK 丢失用例，**44 passed / 42.29 秒**。stdout、JUnit 保存在忽略目录 `artifacts/p6c1-review-fixes/`。

新增的 `DatabaseText` 是同一文本校验的复用，避免 Chat 与旧 API 再次分叉；可选 `corpus_id` 复用原查询与校验，不另建授权系统。没有新增 Scheduler、状态机、恢复引擎、账本、业务配方、权限角色或迁移。

Corpus 反例中的目标文档通过真实本地 ONNX 摄取；100 个填充项仅是该独立测试 owner 的授权元数据，不声称进行了 100 次真实检索。测试只追加自身合成数据，不删除已有数据库、重新 Seed 或操作 Volume。

## 最终提交范围与冗余检查

修复开始时，基线之后的 P6C.1 实现尚未提交，因此最终提交同时收录该既有实现与本轮修复，不能只提交依赖未跟踪 Chat 模块的补丁。既有增量的逐组说明在 [原交付文件表](chat-first-ui.md) 和 [ADR-015](adr/0015-chat-first-conversation.md)。本轮修复直接修改 `web/contracts.py`、`chat_contracts.py`、`intent.py`、`ui_chat.py`、`store.py`、`service.py`，增加正式反例与本交付记录；没有触及 P3/P4/P5B/P6A/P6B 核心。

新增文本类型复用原校验，精确 Corpus 读取复用原 SQL 和授权校验；没有新增持久字段。`ui.py` 删除的大段页面逻辑已由既有 P6C.1 移到管理页和共享组件，原管理页 ACK 丢失测试保留全部有效断言。本轮不再移动界面代码。管理页仍保留独立的报告展示代码，原交付“一份报告投影”的表述过强；暂未复现该重复导致的正确性缺陷，不为消除重复扩大本轮修改。

对历史核心链路的复核与完整回归有明确覆盖范围，不表示证明所有历史源码不存在缺陷。已有五项有效发现全部保留失败证据及正式回归，不以删除测试缩减 Diff。

## 验证记录

最终冻结 192 个源码/测试/迁移/脚本/fixture/依赖文件，两个版本串行执行完整 pytest。命令：

```powershell
$env:DATAPILOT_RUN_DB_TESTS='1'
$env:DATAPILOT_RUN_LIVE_TESTS='0'
$env:DATAPILOT_LLM_MODE='fake'
.venv\Scripts\python.exe -m pytest -q -x --tb=short --junitxml=artifacts/p6c1-review-fixes/frozen/full-py311.xml
.venv-313\Scripts\python.exe -m pytest -q -x --tb=short --junitxml=artifacts/p6c1-review-fixes/frozen/full-py313.xml
```

| Python | passed | failed / errors | skipped | 秒 | 源码一致 |
|---|---:|---|---:|---:|---|
| 3.11.16 | 640 | 0 / 0 | 1 | 2106.247 | true |
| 3.13.15 | 640 | 0 / 0 | 1 | 2261.434 | true |

唯一 skip 为未授权的 Live 模型测试；真实 PG/MCP 没有跳过。冻结清单在每次完整运行开始/结束均一致。细节见 [机器验证记录](research/p6c1-review-fixes-validation.json)。

浏览器实际完成 2001 字符消息被 422 拒绝、原对话恢复输入、条件确认、提交、人工审批、300 CNY 的真实 P3 报告及 API/UI 重启后历史读取。新 Run `4f359af8-87ac-4b9c-8b04-a3d74fce0de5`，同一会话、报告、P3 ID/hash/verdict、预算与 3 条 Journal 调用重启前后完全一致。3 个原历史 Run 的部署前后引用与预算也未变化。Fake 仅替代模型决策，不代表真实模型 E2E。

运行实例 19 个 Web 源码 hash 与冻结源码一致；OpenAPI 与已提交契约相同。Ruff check、format check（235 文件，仅排除用户未改动的 v2.5）、JSON/Markdown 引用与 git diff --check 通过。没有删除旧数据、重新 Seed 或删除 Volume。

提交/推送在上述本地验收完成之后执行；远端 CI 属于推送后的独立核验，不将前次 CI 作为本次证据。

历史 P6C.1 的 632 passed / 1 skipped 双版本记录保留在 [原交付](chat-first-ui.md)；这些是旧冻结源码的有效历史记录，不替代本轮最终回归。新修复只保证受限意图解析的保守拒绝，不宣称完整自然语言理解或真实模型稳定成功率。

## 兼容性与边界

五项审查修复不增加数据库结构；既有 P6C.1 的 0007 会话迁移随其实现一并提交，未修改历史迁移。原 Dataset、Run、Evidence/Verification ID、hash 和 verdict 不应改变。文本校验拒绝原本无法存入 JSONB 的输入。多个明确月份需要用户澄清；明确的单窗口追问、人工时间覆盖与原审批仍保留。Corpus 列表继续有界，精确授权独立于列表截断。

当前对照图表仍仅并列两个已验证窗口；不计算新增长率或因果结论。P6C.1 现有的日期卡片默认值、可信本地单用户和保留期限等边界继续适用。用户 v2.4/v2.5 规划变更不属于提交集合。
