# P7 Git 仓库整理与 Push 前交付

本页记录 2026-10-31 的推送前状态。后续发布与双版本 CI 见正式交付记录。[远端 CI](p7-formal60-48k-acceptance.md#远端-ci)

2026-10-31开始的仓库整理。**Git Consolidation: PASS**；**Local Commits: CREATED**；**GitHub Push: AWAITING_APPROVAL**。只创建本地候选，不自动 Push、PR、合并 main 或触发远端 CI。

## 起始状态与远端

起始分支 `p7-ci-verification-20261028`，HEAD `f8b122438d2c67ab26e618ecded72ecc18454015`，最后一次实际提交时间 `2026-10-28T22:03:54+08:00`。初始383个 tracked 文件，38项修改、236个 untracked；274个候选文件约8.85 MB，无 staged 文件、无删除。另完整登记147696个 ignored 路径，未读取模型权重内容、未上传该清单。

只读 Fetch/ls-remote 核实 `origin` 为 `https://github.com/zouradiant-dev/datapilot-pro.git`。远端 main `18271d7b5159dff7e01bb1e6edd3257f9fd78be4`，起始HEAD相对其领先2/落后0；原远端研究分支与起始HEAD相同。候选名未占用后创建 **`p7-engineering-candidate-v1`**。没有 reset、stash、rebase、cherry-pick、覆盖分支或合并。

完整起始状态、逐文件大小/Hash/分类、tracked/untracked/ignored列表和原Diff保存在 local-only `artifacts/p7/git-consolidation-v1/`；不在公开报告中复刻本机目录、凭据或环境清单。

## 本地提交分组与源码对应

| 组 | 本地提交身份 | 内容 |
|---|---|---|
| A | `a37fb43e2487d6df8d4b10267749b726d60ae9e7` | `feat(p7): consolidate goal confirmation and opt-in Qwen runtime`；153文件（122新增、31修改、0删除）：强耦合核心/Web、安全与对应测试、公开合成研究输入、迁移0008、Qwen可选依赖/容器、Demo驱动 |
| B | 含本文的文档提交，使用下方 Git 命令唯一定位 | `docs(p7): publish engineering candidate and consolidation record`；README/AGENTS/既有文档、ADR与公开交付索引、精确忽略规则、脱敏摘要 |

这些是当前工作区成果的两次整理提交，不虚构近期开发历史，也不声称每个中间 Commit 都独立做过完整验收。为避免把包含本文的 Commit SHA 自引用写入内容，文档提交使用 Git 本身定位；最终交付消息及 local-only `post-commit-record.json` 给出两次实际完整 SHA、数量和剩余状态：

```shell
git log -1 --format=%H -- docs/research/p7-git-consolidation.md
git log --oneline f8b122438d2c67ab26e618ecded72ecc18454015..p7-engineering-candidate-v1
git diff --name-status f8b122438d2c67ab26e618ecded72ecc18454015..p7-engineering-candidate-v1
```

原工作区源码树仍为 **`5a11a01af573c7ee456f2fac7946051f1ce829fe9eba2ba8624370f6c4d7f3a1`**，无本轮产品逻辑修改。Git原有换行归一化后，提交blob源码树为 `5d0884dc22d6868a83ba9745c5a5c5de861a080f4c1736f4bdf19f95eb9ae5de`：111个源码文件归一化内容全等，10个文件仅EOL导致字节Hash差异。逐文件原始/提交Hash、EOL与产品Commit在[公开映射](../releases/p7-engineering-candidate-v1/source-freeze-mapping.json)。没有修改Git换行配置、原工作区字节或旧Freeze来强行对齐。

提交文件完整列表由上述 Git diff 和 local-only `approved-files.json`、`commit-groups.json`、`core-commit.json` 记录。所有产品源码、测试、必要研究脚本、公开合成输入、Qwen实现与锁文件均纳入；没有重要源码故意留在未提交区。

## 排除与公开材料

不上传 `.env`/真实DSN/API Key、Cookie/Session、HMAC密钥、数据库/备份、权重/模型缓存、venv、GPU缓存、原始Trace、签名采集包、完整本机审计清单或 `artifacts/`。不引入Git LFS。

原 `.gitignore` 已覆盖上述目录。本轮仅增加**9个精确文件规则**：三份原工程冻结/Demo/Backlog、三份带本机路径的旧交接Markdown、三份大型逐Run JSON。原件保留且Hash不变，不用广泛规则隐藏源码或测试；[公开副本溯源](../releases/p7-engineering-candidate-v1/publication-provenance.json) 列出每项原件SHA、公开替代文件和变更种类。

另增一条精确 `.gitattributes` 规则，保留负责人 `docs/codex-prompts-v2.5.md` 原有的Markdown双空格换行。v2.4/v2.5全文Hash均与起始盘点一致，未编辑规划内容；只将该文件的合法换行语法与普通尾随空白区别处理，其余文件仍执行原Diff检查，没有修改业务断言或全局Git空白配置。编辑时曾暂时覆盖原有三行夹具属性，Diff复核后在提交前恢复；最终只追加规则，CSV的LF与XLSX的binary属性原样保留。

公开层新增六份脱敏Markdown副本、三份白名单聚合JSON、Demo摘要、源码映射、索引与链接清单。没有上传原始完整运行上下文来修复链接，没有改变实验分数、Gold、Scorer、Seal或STOP。

[GitHub交付索引](../releases/p7-engineering-candidate-v1/README.md) 是当前阅读入口；[链接清单](../releases/p7-engineering-candidate-v1/local-only-links.json) 列出历史文档中全部不随Git发布的本地工件及既有缺失引用。历史报告保持原样，不能把其本地有效链接当成远端可访问；新公开入口的实际链接另做白名单存在性核验。原工程冻结三份文档仅在本机保留，公开副本不冒称原件。

README 增加三项独立验收结论、公开索引和边界，纠正旧0005 Schema head与RAG“待实现”表述；未重写技术方案。默认仍BGE，Qwen仍可选；保留RAM失败、四类过拒、日期澄清UI风险、独立人工NOT_VERIFIED、质量/Live PENDING。

## 安全扫描与限制

没有发现已安装的 gitleaks/trufflehog/detect-secrets。实际采用本地有限模式、UTF-8/AST/JSON检查、敏感JSON字段检查、体积/二进制检查、逐文件Hash清单和命中上下文核验；不是全面秘密扫描或完整产品安全审计。

- 对全部待提交文本及654个历史文本blob检查Provider/GitHub Token、私钥和带凭据URL；两个历史二进制fixture不做文本扫描，无超限跳过blob。
- 历史URL扫描初次保守阻断三处，确认它们分别是 `test_config.py`、`test_dataset_policy.py` 和 `test_rag_contracts.py` 的localhost非法角色/环境脱敏合成测试。原扫描结果保留，另写裁决，不删除命中。新增命中为合成 `x` DSN及测试HostPolicy/HTTP常量；没有发现真实生产凭据进入历史。
- `.env.example` 的 CHANGE_ME、CI短生命周期固定测试口令和负例测试凭据显式识别为样例，不当作真实秘密，也不能拿来部署生产。
- 待提交文件无权重/数据库/运行日志，无新增用户主目录路径、未解释的敏感字面值或异常二进制；最大文件254789字节，低于GitHub文件限制。
- 老提交中的本机路径仍可存在于旧交付/工具，未重写历史；本轮不新增这类暴露。模式扫描不能保证识别所有非标准密钥、个人资料或环境敏感信息，后续公开前仍建议使用独立秘密扫描工具审查。

每组只按明确白名单 `git add -- <paths>`，核对 staged 清单、Hash、归一化内容、stat、mode/删除、secret patterns与`git diff --cached --check`，不用`git add .`、force或no-verify。原始工件与忽略路径保留，不以工作区状态为理由删除文件。

## 实际验证

| 检查 | 结果 |
|---|---|
| 冻结产品/测试/迁移/锁等264文件 | 与本轮起点精确匹配 |
| Phase 2C.5 Seal | 原Seal SHA匹配；444个条目中10个旧Web源码版本由后续2C.6 Seal与当前Freeze精确解释，不恢复旧实现 |
| Phase 2C.6 / 2C.7 / Engineering结果Seal | 99 / 128 / 77文件匹配，无新差异 |
| 历史Gold/Seal/STOP | 按现有完整性Manifest逐项Hash核对，旧记录不改；2222路径的既有审计记录保留 |
| Ruff check | `python -m ruff check .` 通过 |
| Ruff format | `python -m ruff format --check src tests scripts migrations evaluation`：349文件已符合格式 |
| Python 3.11 / 3.13定向pytest | 各3 passed，0失败/跳过；JUnit保留 |
| JSON/公开文档链接/Diff/暂存区 | 公开副本与新索引检查；历史local-only单独列明；逐组diff检查 |
| 五Run、真实PG/MCP、重启/撤回/unknown | 只读引用已封存结果，未重新执行 |
| 新全量pytest、Qwen资源补验、远端CI、DeepSeek | NOT_RUN |

本轮两个Python环境实际运行的三个节点：`test_confirmation_dtos_never_accept_host_attestation_or_actor`、`test_ui_pending_reload_requires_three_explicit_decisions_and_preserves_original`、`test_legacy_host_hash_stays_stable_until_profile_is_explicit`，均在 `tests/test_web_goal_confirmation.py`。本地日志/JUnit位于 `artifacts/p7/git-consolidation-v1/unit311.*`、`unit313.*`，不拿历史CI成功当作本候选CI结果。

## Push计划与停止边界

待用户明确回复 **“确认推送”** 后，才允许推送上述已审核候选分支：

```shell
git push -u origin p7-engineering-candidate-v1
```

该命令不推 main、不force、不建PR、不合并；远端分支若在确认前发生冲突，停止并重新核对，不能覆盖。预计现有 `DataPilot checks` 工作流会因Push触发Python3.11/3.13及隔离PG/BGE检查；当前远端结果为NOT_RUN。得到确认后记录实际CI，不自动修改源码/断言追绿。

本轮不部署、不运行Gate3、不调用模型或写历史数据库。原工程候选为ACCEPTED只指限定脚本Demo；Independent Business Quality与DeepSeek Live Gate继续PENDING。没有已知未解释的源码漂移或需要覆盖处理的Git冲突；扫描覆盖限制、旧资料local-only与远端CI尚未运行均明确保留。
