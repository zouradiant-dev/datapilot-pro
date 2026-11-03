# P7 Final 50：合并、物化与逐项准入

日期：2026-11-03。计划 **50**；物化到 `datapilot_p7_current`；未执行正式 Agent，未调用 DeepSeek。

## 1. 50 条 Manifest

- 总 Manifest：`artifacts/p7/final-evaluation-v1/total-50/manifest.json`
- Lane：SQL-only **17** / RAG-only **17** / SQL+RAG **16**
- retained：v3 未执行 31 条（10/10/11）
- new：supplement-19（7/7/5）
- 50 条 launch config：`artifacts/p7/final-evaluation-v1/total-50/launch-configs.json`

没有覆盖旧 v3 Case/Gold/Seal；19 条 Gold 在 supplement-19/private，旧 31 条 Gold 保持 v3 sealed。

## 2. 物化

- PG：`datapilot-p7-current-v1-postgres-1`
- DB：`datapilot_p7_current`
- Network：`datapilot-p7-current-v1_default`
- 记录：`artifacts/p7/final-evaluation-v1/total-50/materialization.json`
- 8 个 Dataset 与 9 个 Corpus 已追加物化；不重 Seed、不清库。
- Dataset/Corpus/Source/Document/IndexVersion 与 v3 pins 的匹配：
  - 7/8 datasets 精确一致；
  - 9/9 corpora/index 精确一致；
  - `future` 计划 v2 实际 v1，影响 `p7-holdout-v3-017`，标记 BLOCKED，不静默重映射。
- 19 条复用同一公开合成数据身份；Gold 语义未变。

## 3. 50 条 preflight

| 状态 | 数量 |
|---|---:|
| READY | **44** |
| EXPECTED_HOST_REJECTION | **6** |
| BLOCKED | **0** |
| 合计 | **50** |

逐条结果：`total-50/manifest.json` 的 `preflight` 数组。

预期宿主拒绝：
- `p7-holdout-v3-018`：REPORT_SCOPE_INVALID
- `p7-holdout-v3-019`：VERSION_NOT_AUTHORIZED
- `p7-holdout-v3-039`：DOCUMENT_NOT_AUTHORIZED
- `p7-holdout-v3-059`：DOCUMENT_NOT_AUTHORIZED
- `p7-holdout-v3-040`：DOCUMENT_NOT_AUTHORIZED
- `p7-holdout-v3-060`：DOCUMENT_NOT_AUTHORIZED

阻塞：
- `p7-holdout-v3-017`：`future` v2 已通过显式 DATE Schema Confirmation 追加；usage metric 计划 v3→实际 v1，definition_sha256 相同，显式记录映射；Gold 未改，READY。

## 4. 预算（实际 preflight 结果）

- planned：50
- READY Runtime：**44**
- expected host rejection：6
- blocked：0
- attempts：**352**
- token units：**792000**
- peak estimate：**USD 0.9504**
- concurrency 1；provider timeout 30s；task 180s；campaign 10,800s；SDK/outer retries 0
- 普通业务失败继续；unknown/safety/budget/identity/integrity 停止
- 账单：not_reconciled

## 5. 授权与命令

授权模板：`total-50/authorization-template.json`，`authorized=false`；未创建 Permit。

正式 50 条执行命令：**当前不可用**。现有 `current_binding` 是控制/probe 入口，不是 50 条正式 Runner；本轮没有把它伪装成正式执行命令。

可执行 preflight/物化核验命令：

```powershell
Set-Location 'D:\桌面\llm-learning\datapilot-pro'
$env:PYTHONUTF8='1'
& .venv\Scripts\python.exe artifacts\p7\build_total50.py
```

该命令会重写 total-50 manifest/preflight；正式执行命令待 50 条 Runner/Collector 接线完成。

## 6. 结论

- 50 条任务清单和 50 条 launch config 已生成；
- 44 条 READY，6 条预期宿主拒绝，0 条 BLOCKED；017 已映射 READY；
- 物化与身份映射已落盘；
- **不具备正式 50 条执行入口**，因此不能标记 READY_FOR_PAID_AUTHORIZATION；
- 没有 DeepSeek/付费 Permit/Commit。
