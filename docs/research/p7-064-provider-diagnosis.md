# 064 单题诊断性 Live 准备

日期为 2026-11-04，时区 Asia/Singapore。状态为 READY_TO_REQUEST_NEW_SINGLE_CASE_LIVE。本轮实际付费调用为 0，完整 CI 为 NOT_RUN。

## 复现与修复

本地 HTTP/1.1 保活端点配合真实 ChatOpenAI、NativeTransport 和原 run_async，复现了第一次调用成功、第二次在新的事件循环中抛出 RuntimeError。异常链的消息精确为 Event loop is closed。服务端收到两次 HTTP 请求，说明客户端异常也可能发生在请求已经到达服务端之后。旧 064 的实际供应商侧处理结果仍无法由现有记录确定。

SDK 默认异步 HTTP 客户端按端点和 timeout 缓存，保活连接属于创建它的事件循环。旧准入脚本逐次调用 run_async，每次关闭循环。修复后，同一准入批次的 start、approve、collect 都在一个 asyncio.Runner 内执行。

Gateway 对非 SDK 异常追加经过限定的异常类名和 provider_await / response_commit 阶段。原始异常正文不写入诊断。SDK 异常已有的 HTTP 状态与安全 request ID 保留。

## 实际验证

| 验证 | Python 3.11 | Python 3.13 |
|---|---|---|
| 本地保活 HTTP 连续 Worker 调用及 Provider 定向测试 | 13 passed，1 deselected | 13 passed，1 deselected |
| 真实隔离 PG 的 HTTP 503、读取超时和连接失败负例 | 3 passed | 3 passed |

三项 PG 负例均验证首次请求保守结算、账本预留保留、后续请求被原 Journal 拒绝、HTTP 请求总数为 1。四项单题 Permit 检查通过，包括未授权、错误绑定、过期拒绝，以及内存测试 Permit 到达替身 Worker。实际模型请求为 0。

初次 PG 检查因 Docker Engine 未运行，每版三项连接失败。已保留初始 JUnit。正常启动现有 Docker Desktop 和专用容器 datapilot-p7-g2-60-postgres-1 后，负例全部通过。

日志、JUnit、修复前复现和机器结果位于 `artifacts/p7/064-provider-diagnosis-20261104/`，入口为 `verification.json`。

## 新单题身份

新 Campaign 为 `p7-final50-admission-064-diagnostic-v1`。新 Run ID 为 `d4dfd8c5-d9fc-5e7a-b663-a7e4033defe1`。完整配置和 source/evaluation 身份见 `artifacts/p7/final50-admission-handoff-20261104/064-diagnostic-v1/preflight-final/`。其中 `launch-configs.json` 只有 064，合同与上一轮 064 逐字段一致，Gold 为 213 events。

绑定 SHA256 为 `1dbe79f039ac248df74fb69ca69062215654688517e0a6a39c5409f5b54ec329`。每 Run 上限为 8 次调用、18,000 Token，串行执行。Provider 为 deepseek-flash，thinking disabled，temperature 0，SDK 重试 0。新模板为 `authorized=false`。启动时验证完整绑定和到期时间，并使用独立的一次性派发声明目录。

原 064 unknown、3424 Token 预留、原 STOP、原 Permit 及 017 评分的文件 SHA 已重新核验一致。此记录支持申请一次新的 064 诊断性执行，真实 Live 结果待验证。

## 执行命令

负责人授权后，由宿主按新模板生成 `064-diagnostic-v1/owner-permit.json`，填入本次授权引用及明确到期时间。精确命令为下列脚本。

```powershell
& 'D:/桌面/llm-learning/datapilot-pro/artifacts/p7/final50-admission-handoff-20261104/064-diagnostic-v1/run-live.ps1'
```

脚本连接专用隔离库，只选择 064 的新 Campaign 和 Run。旧 017 已通过，077 尚待后续处置。

## 修改范围

- `src/datapilot/orchestration/model.py` 增加脱敏异常类型和阶段。
- `tests/test_deepseek_transport.py` 增加非 SDK 异常脱敏与预算保留测试。
- `evaluation/p7_v3_current/final50_admission_control.py` 共享事件循环，新增固定的 064 单题准备和执行参数。
- `evaluation/p7_v3_current/test_admission_lifecycle.py` 使用本地 HTTP 保活连接验证两次 Worker 调用。

Ruff、format 与 git diff --check 通过。修改保留在本地工作区，尚未提交或推送。
