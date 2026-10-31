# Gate 2B：SQL NUMERIC 定点序列化最小修复

2026-10-25，按项目负责人明确授权，只修复原 SQL Tool 的 Decimal 结果边界。最终 `ready_for_live_authorization=true`，可独立申请 Live 授权；`live_allowed=false`。本轮没有调用 DeepSeek、执行正式业务 Holdout、进入 Gate 3 或提交推送。最终状态和验收证据见 [结构化记录](research/p7-numeric-serialization-fix.json)；[旧诊断](p7-zero-revenue-diagnosis.md) 和原 rejected 记录作为历史保留。

## 修改与边界

唯一生产代码修改位于 [tools/sql.py](../src/datapilot/tools/sql.py) 的 `_serialize_cell`：新增 13 行、替换 1 行。

1. 非有限 Decimal（NaN、sNaN、Infinity）返回受控 `VERIFICATION_ERROR`。
2. 根据符号、系数位数和指数，在格式化前保守计算定点输出长度，超过原 P3 80 字符上限时返回 `RESULT_TOO_LARGE`。极端指数不会先展开巨量字符串，零也没有专用绕过。
3. 使用 `format(value, "f")` 无损保留精度与 scale，不经过 float，不依赖 Decimal context precision 舍入，不截断或静默降级。

没有修改 P3 严格解析器、六层 Verifier、SQL 业务配方、Semantic/Metric 定义、权限、依赖或迁移。原文本单元格 4096 字符及总结果配额继续生效。普通 SQL NUMERIC 也受 80 字符上限约束；超限明确拒绝，不承诺支持任意 PostgreSQL NUMERIC 精度。

## 失败反例与测试

先在旧源码真实执行指数零反例：`1 failed`，实际输出 `0E-20`，不符合定点契约。保留 `artifacts/p7/numeric-serialization-fix/before.log/xml`、`sql-before.py` 和旧 SHA。修复后两版本本地边界用例各 **30 passed**，覆盖指数零、普通/带 scale/负号零、非零小数、极小数、80 字符边界、大精度、非有限输入、极端正负指数、超长文本及非法输入。极端输入测试确保拒绝发生在格式化之前；原 P3 仍拒绝来自文本/模型的 `0E-20` 和 float。

新增真实 PG/MCP 测试验证定点输出可被原 parser 接受，并验证 NaN/Infinity、过大/过小指数返回原受控错误。最终 Python 3.11：**262 passed、2 deselected，486.93 秒**；Python 3.13：**262 passed、2 deselected，496.54 秒**。没有 skipped，也未使用旧 CI 冒充本轮验证。不将 Mock/Fake 或定向 P3 检查描述成真实模型业务效果。

适用回归包括 SQL AST/Reader、CSV/XLSX 导入/金额、MCP、P3 指标与证据、Report、Runner/Collector/Scorer、预算/Checkpoint/恢复及 Web 恢复。为遵守本轮范围，显式排除两个包含初始化/迁移/grants 重入或 Seed 入口的测试；没有重新 Seed、清库或删卷。

```powershell
# 启动器只使用 guard 验证过的 Gate 2B PG，清除继承模型密钥。
.venv\Scripts\python.exe artifacts/p7/numeric-serialization-fix/run-regression.py 311
.venv-313\Scripts\python.exe artifacts/p7/numeric-serialization-fix/run-regression.py 313
.venv\Scripts\python.exe scripts/p7_campaign.py preflight
.venv\Scripts\python.exe scripts/p7_business_evaluator.py check
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check --extend-exclude docs/codex-prompts-v2.5.md .
git diff --check
```

受保护 v2.5 文档中的旧 Python 示例格式问题不在本轮修改范围，限定格式检查明确排除它；不冒称整个工作区格式检查通过。用户 v2.4/v2.5 文件保持原 SHA。

## 真实定向 P3 结果

在原 `datapilot_p7b` / `127.0.0.1:55440` 隔离实例通过原 MCP、`analyze(client=None)` 和原 Registry 追加新证据，每条单独执行，不启动模型或正式 Agent Run：

| Case | 新结果 | 原六层检查 | 新 Evidence ID |
|---|---|---|---|
| bh2-016 | 0 CNY | 全 passed / verified | `19c811b1-5cc7-4cea-9fe4-53c3fed02e7b` |
| bh2-052 | 0 CNY | 全 passed / verified | `f5edd2a2-3612-469a-8fb8-ffd9f2690e6c` |
| bh2-047 | 447.56 CNY | 全 passed / verified | `c1f8454e-bc75-49b8-a70f-6df0f3358b65` |

具体 Verification ID、query/result hash 和原始 scale 留在 [新验收工件](../artifacts/p7/numeric-serialization-fix/targeted-p3-after.json) 及逐 Case 私有 JSON。两次分别读取旧 Evidence/Verification，确认原零值 Evidence `4f1ccf99-901f-4e2c-abc0-d0054aa8094d`、Verification `dcd34f1c-de7a-4fa3-b260-de4385eb85dd` 的完整内容和 rejected verdict 不变；旧 047 的 verified 也不变。新记录没有覆盖历史，没有修改口径来获得结果。

## 60 条准入与实验边界

重新预检 60 条：53 条普通 Runtime 就绪、6 条预期宿主预检拒绝、1 条保留 `SEMANTIC_NOT_CONFIRMED` 的故意缺定义负例（060）。这对应 **54 个唯一 Runtime Run 配置**，不是已执行的 54 个 Run；正式 Run 实际为 0。

12 个 Semantic / 20 个 Metric 的获批身份、版本与 hash 一致；C 两项、019 的 Metric v999999、048 的 Dataset v999999 仍缺失。每 Run 8 次模型调用、18,000 Token、1,200 输出的原上限和精确授权 scope 不变。060 不补单位/定义，也不把未确认口径改成 verified。冻结 Scorer 继续按原严格拒答语义记分，未达其要求的答案仍会失败；准入不是业务正确率保证。

## 实现冻结与停止点

保留旧 active freeze 的完整字节和旧 SQL 源码/SHA，记录本轮唯一授权源码差异。建立 [新实现 freeze](research/p7-business-v2-numeric-fix-freeze.json)，并使既有 Runner 使用的 `p7-business-v2-freeze.json` 指向同一新冻结内容，无需修改 Runner 或预算/恢复机制。未来 Live 许可必须绑定新实现 freeze SHA，旧许可不能复用。

v1/v2 Gold、Seal、输入、指标定义和模型候选保持不变；本轮是执行结果表示契约的版本变更，不是重设业务答案。旧诊断及首次失败不能追溯记为通过。最终回归/准入和新 freeze 通过后才可标 `ready_for_live_authorization`；该状态不授权 DeepSeek，也不等于 Gate 2/P7 完整效果验收。本轮至此停止。
