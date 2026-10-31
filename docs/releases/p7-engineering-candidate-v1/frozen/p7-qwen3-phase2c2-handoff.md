> 公开脱敏副本。历史原件 `docs/research/p7-qwen3-phase2c2-handoff.md` 保持不变、仅本地保留。
> 原件 SHA256：`b24f1e1034c3494ec6e140a3021205d3c470dec9870a7e457824ab46949ccccf`。仅替换本机路径和不可公开工件链接，历史结论/分数不变。

# Phase 2C.2 运行中接续记录

当前工作是 100 条新公开 Dev 的 BGE/Qwen 配对评测，非付费。产品源码、阈值、旧 Gold/Scorer/Seal 未改；不得自动提交推送。

- 仓库：`<LOCAL_PATH>`，分支 `p7-ci-verification-20261028`，HEAD `f8b122438d2c67ab26e618ecded72ecc18454015`。
- 新代码：`evaluation/qwen_expanded_quality/`、`tests/test_qwen_expanded_quality.py`。输入 `cases.json` 共100条，每类2 Dev/8 Validation。
- 工件：`artifacts/p7/qwen-expanded-v1/`；新库 `datapilot_test_qwen_expanded_v1_20261030`，PG17/pgvector隔离实例55441。未Seed，旧库不写。凭据只在忽略的 `environment-private.json`，不要打印。
- `registration.json` 是原Gold/实现预登记；准备阶段旧SQL checker日期写死导致 `metrics.log` 失败，未运行任何检索。只修正独立SQL对照接线，另建 `registration-r2.json`；Gold/Source/Scorer/产品不变。实际执行绑定 r2，SHA `a7f63d93754619d481c6d4bdc3d007a66fc7eabbee46b5c70b7cace21e391171`，父Gold登记SHA `851dbe5284161fa83721e823d83ade55a90333a7fd98e8db5a94738188fc178c`。
- 10份CSV已独立Decimal+真实MCP SQL核对，原Registry测试口径登记；200个索引已生成，绑定在 `bindings.json` 与 `bindings-seal.json`，同Corpus/Source/Chunk，两套ModelSpec/IndexVersion。
- 两版契约11项及相关定向回归各212项通过；Ruff通过。完整pytest/远端CI/付费Live未执行。
- 历史921个文件SHA已核对一致（原662＋Phase2C.1 259），见 `historical-integrity-before.json`。

当前仅已启动 Batch 0（20 Dev x2），统一脚本串行执行原 Durable/Inspector。后台exec session为97039。先读 `batch-0-runner.log`、`scores/` 和 `stopped.json`，判断是否还在运行；禁止重复启动或覆盖既有 dispatch。

批次结束后先执行独立离线复评：

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m evaluation.qwen_expanded_quality.summarize --index 0
```

如果 `stopped.json` 存在：立即停止所有新派发，保留200总分母与not_run，生成最终BLOCKED报告；不修产品/Gold/Scorer、不复跑当前案例。

只有 Batch 0 seal complete=true、offline_equal=true、stopped=false，才允许下一个批次：

```powershell
.venv/Scripts/python.exe -u -m evaluation.qwen_expanded_quality.runner batch --index 1
.venv/Scripts/python.exe -m evaluation.qwen_expanded_quality.summarize --index 1
```

其后按2/3/4逐批同样执行，绝不跨过未完成/失败/未封存批次。每个case immutable intent；未知调用结果禁止重发。每批40观测；普通质量失败继续，false completed/越权/未知/预算或评分完整性错误停止。

不要在Validation上修改任何规则。源文件/预登记/评分器每Run检查Hash；产品为Host Goal v2，默认BGE不变。资源采样是每秒进程树RSS/整卡GPU，不能称为CUDA allocator精确峰值。MCP/准备/检索/Worker/报告/Inspector计时在签名collection及原日志中，BGE没有独立显式prepare阶段需如实标记。

结束或停止后，还需：真实新库的有界BGE/P3/恢复/unknown定向回归（可复用上轮pytest入口但必须加载本轮env、输出新标签，不能误写旧库）；历史封存再核验；汇总时延/采样资源；逐例归因；生成 `docs/research/p7-qwen3-phase2c2-expanded-quality.md/.json`、最终seal。结果必须区分20 Dev和80 Validation；不完整Validation不做总体推断。

NEXT SESSION PROMPT：继续Phase2C.2，先读本交接与用户附件c18d1355任务全文，保留全部修改。先收集当前Batch 0状态，禁止重跑；按上面的freeze/stop/批次seal规则接续。无付费调用、不切BGE、不改产品或Validation、不提交推送、不进Gate3。完成结果与报告或安全停止后结束。


## 后续安全停止补记

Batch 0已完整40/40、离线一致；Batch 1在ex074/Qwen触发false_completed硬停止。总75/200观测，125 not_run。`stopped.json`已存在，绝对不能继续batch或one入口。仅允许离线复评/只读审计/交付；当前结果BLOCKED。不得把旧交接中“按2/3/4继续”当作恢复授权。所有后续修复/新评测需要负责人另行授权，当前80 Validation不能修后续跑仍称独立。

## 交付收尾

正式报告 `p7-qwen3-phase2c2-expanded-quality.md/.json` 已保存，记录全部100对计划、75已观测和125 not_run。收尾仅做静态校验、离线统计与结果封存，不再启动业务或兼容性 Runtime。后续以正式报告与 `artifacts/p7/qwen-expanded-v1/stopped.json` 为准；本文件之前的在途批次继续命令不再适用。
