# CI #25 单项修复接续

2026-11-01。**本轮没有 Push，没有启动新 CI，没有运行 PG。**

## 已保存状态

- 分支：`p7-engineering-candidate-v1`；基线/本轮重新读取远端：`c7606be7d8838433abc1fb3a9aa643516e07fdf6`。
- 一个本地 `fix(test): separate CI25 contract and runtime citation guards` 提交包含两个测试文件、现有 workflow 及三份本轮交付文件；准确 SHA 见 `git log -1`、本轮答复或 `artifacts/p7/ci25-single-failure-repair-v1/commit-verification.json`。
- 旧六份未跟踪 Docker/CI 报告保留且不在提交中。不要 `git clean`、reset、rebase 或上传它们。
- 原 #25 双版各 1332 unit passed / 14 PG passed / 1 failed 的原件：`artifacts/p7/ci22-batch3-actions-v1/`。
- 本轮最终双版各 64 passed / 0 failed / 0 skipped；精确 PG Node 各收集 1 项，未执行；Ruff/format/diff 通过。
- 新日志、JUnit、62 个保护文件哈希与断言审计：`artifacts/p7/ci25-single-failure-repair-v1/`。不要覆盖或无故重跑。
- 详细根因、31 项方案及精确身份：[报告](p7-ci25-single-failure-repair.md)、[JSON](p7-ci25-single-failure-repair.json)。

## 下一步命令与停止条件

首先只读核对（从仓库根目录运行）：

```powershell
git branch --show-current
git status --short
git log -2 --format='%H %s'
git show --stat --oneline HEAD
git diff --check
.venv\Scripts\python.exe -m json.tool docs/research/p7-ci25-single-failure-repair.json
```

重新通过 GitHub API/`git ls-remote origin refs/heads/p7-engineering-candidate-v1` 确认远端没有变化。**等待用户单独明确批准本次 Push**，未批准时停止，不把旧 Batch 3 的批准复用于本提交。

只有批准后，且确认 HEAD 正是唯一待推送白名单提交、远端仍为上述基线，才运行：

```powershell
git push origin HEAD:refs/heads/p7-engineering-candidate-v1
```

此时应出现 `DataPilot CI25 Single Failure - NOT FULL CI`，Python 3.11/3.13 各执行且仅执行：

```text
tests/test_citation_policy_postgres.py::test_real_supplement_only_and_forged_quotes_cannot_fill_required_sources
```

工作流复用原新隔离 PG17/pgvector/BGE/角色初始化，保留全非集成、Ruff/格式/coverage/JUnit/源码 SHA。不要本机恢复 Docker、访问旧数据库或改为其他 PG 实例；不要增加另外 14 项 PG 或完整矩阵。

两版完成后下载带 Run ID、Commit、attempt 的完整日志和 ZIP，验证 digest、scope、源码身份、JUnit 精确 Node、无 skip。要求非法合同 `ValidationError`、有效原件 completed、运行期索引替换 `DOCUMENT_NOT_AUTHORIZED` 以及合同/授权未变的所有断言实际执行。若失败，只归因并停止，不能补提交/自动重跑。

当前累计进度 **28 已验 + 1 待验 + 31 未迁移**。两版新 PG 均通过后才能更新为 **29 已验 / 31 剩余**，仍非 Full CI。下一批集中迁移须另行批准。

## NEXT CODEX SESSION PROMPT

继续 DataPilot Pro CI #25 单项修复验收。先读 AGENTS.md、docs/research/p7-ci25-single-failure-repair.md/json 和本 Handoff，保留六份旧未跟踪记录与所有 artifacts。核对当前分支、唯一 fix(test) 提交及远端基线 c7606be7d8838433abc1fb3a9aa643516e07fdf6。两版各64项定向单元已通过且源码一致，不重复运行；真实 PG 尚未执行。如果用户已明确授权该提交 Push，按白名单仅推送此提交并核验 CI25 单节点双版隔离 PG 日志/JUnit/SHA；否则只报告等待批准。不得修改产品核心、Gold/Seal/STOP、默认 Embedding，不能恢复历史 Docker、调用模型、启动另外14项或完整CI。失败只归因，成功仅更新累计进度与交付，不自动迁移剩余31项。
