# Full CI Recovery Handoff

2026-11-01。**完整workflow已恢复，尚未Push；双版Full CI均NOT_RUN。**

- 分支 `p7-engineering-candidate-v1`；开工本地/远端 `2f2f1694525cf2d677d9df13a449090836f1e731`。
- 独立本地提交：`fix(ci): restore complete dual-version regression workflow`；准确SHA见最终答复、`git log -1`及 `artifacts/p7/full-ci-recovery-v1/commit-verification.json`。
- 白名单仅 `.github/workflows/test.yml` 与本轮三份交付。八份旧未跟踪报告原样保留，禁止清理/误提交；业务和测试源码未改。
- 双版各1724项全量收集、388项integration收集，原60项均包含；既有workflow测试各5通过。完整PG执行未发生，不重复跑此前已可信的业务/质量实验。
- [报告](p7-full-ci-recovery.md)、[JSON](p7-full-ci-recovery.json)；完整证据在 `artifacts/p7/full-ci-recovery-v1/`，保留全部旧结果与203份保护文件。

## 仅在获得新的完整CI推送授权后执行

先只读核对：

```powershell
git branch --show-current
git status --short
git log -2 --format='%H %s'
git show --stat --oneline HEAD
git diff --check
git ls-remote origin refs/heads/p7-engineering-candidate-v1
.venv\Scripts\python.exe -m json.tool docs/research/p7-full-ci-recovery.json
```

本轮并未授权Push。等待用户明确确认完整CI推送；不要复用31项的授权。确认唯一白名单提交及父/远端基线一致后，普通推送：

```powershell
git push origin HEAD:refs/heads/p7-engineering-candidate-v1
```

应仅触发一次 `DataPilot checks`，Python3.11/3.13、全新隔离PG17/pgvector、固定BGE/角色/迁移，完整非集成与无Node白名单的全部PG集成。

## 完成后的核验及停止

- 下载两版完整日志、ZIP、JUnit、源码SHA；核对GitHub digest、Commit、`scope=full-ci/full_ci=true`仅为范围元数据。
- 当前完整身份1724、integration388、预计非集成1336。两版原60个失败身份必须都实际存在且按真实结果报告。
- 唯一动态身份：`test_qwen_lifecycle.py::test_process_metadata_cannot_target_current_or_system_process[os.getpid()]`。原源码未改，各pytest进程PID不同；保留原值，仅用报告中唯一self-PID规则核对该参数。0/1/-1和其他身份不得归一化或忽略。
- 历史63项skip来自62 Qwen/CUDA、1付费Live opt-in；这不是尚未执行的本轮skip成绩。未来读取实际skip理由，不能用预期填结果。
- 成功分别报告全量passed/failed/errors/skip及安全边界；失败只保留Node/异常/根因，不热修、重跑、追加提交或进入P7开发。付费模型和GPU专项仍需独立授权。

## NEXT CODEX SESSION PROMPT

继续DataPilot Pro Final Full CI Recovery。先读AGENTS、docs/research/p7-full-ci-recovery.md/json和本Handoff，保留八份旧未跟踪报告与全部artifacts。核对当前唯一fix(ci)提交及远端基线2f2f1694525cf2d677d9df13a449090836f1e731。已完成双版1724/388完整收集、各5项workflow合同通过及静态检查，产品/测试源码未改。只有用户明确授权本次完整CI推送后才推送四文件白名单提交，等待一次DataPilot checks完整双版本运行；无授权则停止。下载全部日志/JUnit/Artifact/源码SHA并按真实分母核对；唯一self-PID参数按报告说明记录。失败只归因，不改核心、不补提交、不重跑，不调用付费模型、不启动GPU专项、不触碰历史Docker或用户库、不继续P7。
