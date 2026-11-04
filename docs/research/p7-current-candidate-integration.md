# P7 当前候选整合与本地完整范围验证

日期：2026-11-04，Asia/Singapore。**本轮已收口。** 当前分支 `p7-engineering-candidate-v1`，HEAD 仍为 `2628b61`，工作区改动保留；没有 Commit/Push，也没有触发远端 CI。

## 本轮改动

- 默认 pytest 纳入 `evaluation/p7_v3_current`，原 20 项评测入口测试改为公开合成输入与临时绑定。旧 Manifest 和独立 Oracle 的私密文件只在显式操作时读取，干净公开副本不再依赖本地 Holdout/凭据。
- 历史 Formal 绑定继续拒绝源码漂移；没有覆写旧 Freeze 或关闭 Hash 校验。
- 新候选工具绑定 raw SHA256、源码/依赖/评测/测试快照、修复后的评分版本。最终 425 文件包包含安装所需 README、公开 JSONL 与意图清单，直接在快照上完成双版本非集成验证。
- CI 测试范围由实际 collection 生成，替代 1748 固定声明；当前实际为 1828 = 1420 非集成 + 408 集成。保留双版本、锁定依赖、真实 PG/MCP、覆盖率、失败证据上传及 opt-in 边界。
- 新 60 题在非付费准备中绑定了当前修复与 v3 评分；来源只读复验 54 条 pins 检查和 6 条拒绝控制通过。这不是业务质量成绩。负责人已将其正式 Live 及独立消融准备推迟到本轮之后，本轮不继续启动。
- 私密 handoff 压缩包单独忽略，不混入代码交付；中英文 README 和评测索引指向当前状态。

## 实际验证

| Python | 最终 425 文件快照非集成 | 真实 PG/MCP 最终范围 | failed / errors |
|---|---:|---:|---:|
| 3.11.16 | 1420 passed | 345 passed / 63 skipped | 0 / 0 |
| 3.13.15 | 1420 passed | 345 passed / 63 skipped | 0 / 0 |

3.11 集成分两批覆盖同一份 408 身份清单：首轮 123 passed、62 skipped、223 setup errors；错误均为 Windows 系统 Temp ACL。改用本轮专属临时目录后，对**原 223 个身份**精确复验，222 passed、1 CUDA opt-in skip，无失败或错误。首轮原件保留，不冒称一次干净全量运行。

3.13 在另一全新 PG17/pgvector 实例上一次执行完整 408 项，345 passed、63 skipped，无失败或错误。两版本最终集成身份集合完全相同。63 项逐条由 JUnit 核对，为 Qwen/CUDA opt-in 62 项、真实模型 opt-in 1 项。

两版本均出现一次畸形 `total_tokens` 的 Pydantic 序列化警告，来自 `bad_usage` 故障注入；对应测试通过，未屏蔽警告。工程模型决策为 Fake/本地 HTTP Mock，数据库、MCP、BGE、P3 和恢复链路按测试实际执行，不冒称独立模型业务质量。

Ruff check、format check（379 文件）及 git diff --check 通过；两个现有环境的 `uv pip check` 通过。未改依赖版本或锁文件。干净公开副本另有 1420 passed。

## 已授权 053 单题结果

本轮唯一真实付费模型执行已完成：新 Run `58a8b282-97dd-4b04-ab84-616f0354f033`，**v3 严格通过、partial、4 calls / 7139 Token、unknown=false**。

`fact_1=true`、`fact_2=false`；RAG 仍为 insufficient、Worker 未完成；已知事实显示，缺失事实保持缺失。采集签名、账本用量、16 项评分维度和 STOP 已核对；1/1 Run 许可已消费，不使用剩余额度重跑。原十题 v2 9/10 保留。详见 [单题 Live 结果](p7-053-current-candidate-live-results.md)。

053 执行时使用 421 文件候选 `ce54a620…`。其后只补齐打包工具及测试与公开验证输入，最终 425 文件候选为 `cdb520d5…`。两包业务源码、Worker、评分器和评分依赖逐文件 Hash 一致；旧执行快照与签名保持原样，不把旧 Run 改签为新包执行。

## 完整性与边界

- 132 份历史冻结、Gold、Seal、STOP 等受保护文件 SHA256 重新核对，变化 0。
- 最终候选 Manifest SHA256：`cdb520d5f97ba1159e6345b69690335a109411df762e882162a5228e3b992974`。
- 本地工程范围验证完成；**完整远端 CI：NOT_RUN**，不能写成 GitHub Actions 已通过。
- 53 单题回归、新 60 题、旧 Holdout 和独立消融分别计数；P7 整体验收仍不由本轮自动推定。
- 两个本轮新建测试容器已经校验名称/标签后停止；卷、数据库和证据保留。历史评测实例未停止、未重置。

机器摘要及 JUnit/Manifest SHA256 见 [p7-current-candidate-integration-results.json](p7-current-candidate-integration-results.json)。完整日志、原始 JUnit、421/425 两份快照和单题签名在本地忽略目录 `artifacts/p7/current-candidate-integration-20261104/`。
