# CI Final Migration Handoff

2026-11-01。本地集中迁移已完成；**本批 PG 未执行、未 Push、Full CI 未验证**。

## 已保存成果

- 分支 `p7-engineering-candidate-v1`；开工基线/远端 `b3328e003cf5e1fc997c28c2228bf23209562699`。
- 一个本地 `fix(test): migrate final 31 CI contracts without changing trust boundaries` 提交；完整 SHA 见 `git log -1`、最终答复及 `artifacts/p7/ci-final-migration-v1/commit-verification.json`。
- 11 个既有文件 + 三份交付；不包含七份旧未跟踪 CI/Docker 报告。不要清理它们或忽略目录。
- Python 3.11/3.13 最终各 **281 passed / 0 failed / 0 skipped**，各 6 项被非集成 marker 正常排除；独立 PG 收集各 **31 项**且与原 JUnit 精确相等，无额外身份或 skip/deselected。
- 原 assert/raises 全保留，产品/共享工厂/Gold/Seal/STOP 未改；117 份保护文件 SHA 一致。
- 证据目录 `artifacts/p7/ci-final-migration-v1/`：`nodeids.json`、`before.json`、`audit.json`、双版本日志/JUnit/源码 SHA、静态检查、交付与 Commit 验证。已有结果不可覆盖，不无故重跑。
- 详细报告：[迁移记录](p7-ci-final-migration.md)、[机器记录](p7-ci-final-migration.json)。原 #26 验收仍为29/60，31项真实验证待执行。

## 下一次先做的只读检查

仓库根目录运行：

```powershell
git branch --show-current
git status --short
git log -2 --format='%H %s'
git show --stat --oneline HEAD
git diff --check
.venv\Scripts\python.exe -m json.tool docs/research/p7-ci-final-migration.json
git ls-remote origin refs/heads/p7-engineering-candidate-v1
```

核对 HEAD 为本次唯一白名单提交、父提交与远端均为上述基线，工作区与七份保留报告未漂移。用户必须明确回复 **“确认最终31项定向推送”**。没有授权时停止，不复用 CI25 或旧 Batch 的授权。

仅在授权且上述条件成立后执行：

```powershell
git push origin HEAD:refs/heads/p7-engineering-candidate-v1
```

应触发 **DataPilot CI Final Migration — 31 Cases — NOT FULL CI**。复用全新 GitHub Actions PG17/pgvector，双版各31个精确原身份，保留全非集成/Ruff/format/日志/JUnit/源码身份。不要手动 rerun、恢复历史 Docker 或配置用户数据库。

完成后下载两版完整 Artifact/Job 日志，核对 GitHub ZIP digest、Commit、Scope、源码 SHA、JUnit 名称/数量/跳过、原断言实际执行。尤其核对两个低信任负例和可信 Host 正向路径，原3次调用、Journal/Ledger、搜索、refs、重复恢复相等。若失败，只归因并保留；不热修核心、不追加提交、不自动重跑。

只有全部真实通过才能记原60项全部定向验收；随后完整CI必须另获独立授权并恢复所有原PG测试，不以这31项替代完整矩阵。

## NEXT CODEX SESSION PROMPT

继续 DataPilot Pro CI 最终31项定向验收。先读 AGENTS.md、docs/research/p7-ci-final-migration.md/json 和本Handoff，保留七份旧未跟踪报告和全部 artifacts。核对唯一 fix(test) 提交、父/远端基线 b3328e003cf5e1fc997c28c2228bf23209562699。本地双版各281通过、各31原身份收集已完成且源码一致，不重复测试。仅在用户明确授权“确认最终31项定向推送”后推送白名单提交并检查一次双版隔离PG定向CI，下载核对全部证据；未授权就停止。旧run_question保持低信任，合法语义成功走原Host/Coordinator或run_durable(report_scope)，不修改产品API/Goal/P3/Report/Durable，不访问历史Docker或用户库，不调用付费模型。失败只归因，成功只更新真实进度与交付；禁止自动运行完整CI、重跑或扩大修复。
