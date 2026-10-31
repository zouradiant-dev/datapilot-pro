# P7 Phase 3B：同语言查询策略 Dev 对照

2026-10-25。**原问优先在本次受控 Dev 中减少了跨语言空召回，但完整候选未通过预注册的保守提案条件。本轮不建议直接修改生产 RAG Agent。** 未调用 DeepSeek，也未运行历史 Holdout；不能将此结果解释为已修复 bh2-026 或产品成功率。

## 1. 冻结设计与最小候选

沿用 [Phase 3A](p7-phase3-rag-diagnosis.md) 的原 RAG/ToolRegistry/MCP、PG17 + pgvector 隔离实例和本地固定 Embedding revision/文件 SHA。新写 6 份中文、2 份英文公开合成短文档，主题为数据导出删除、角色权限、API 配额、密钥轮换、维护通知及客服交接；未复用 Phase 3A 两个评分主题的问题或来源，既有夹具仅用于回归。

12 条查询任务包含 8 条可回答、2 条无对应来源、2 条只有背景而不能确认所请求答案的任务。8 条正例含两个双来源任务和一个英文控制任务；涉及主题/组合并非 12 个独立业务场景，不作为正式业务成功率样本。

两组共同固定 **0.55、Top-k=5、每任务最多两次搜索、相同宿主目标及 Corpus/Source/IndexVersion**。问题、全部改写、来源级/短文 chunk 级相关性及评分方法在首次 Embedding/PG 查询前冻结，SHA256（规范 JSON）为 `a95cc3ab9d0d5dcf30e81be008b2c6e8b8f26a56ea3bbb46ba66e7127f204daf`。没有观察分数后调查询、阈值或标签。

| 组别 | 查询选择 | 空召回以外的行为 |
|---|---|---|
| 原检索机制 + 脚本化自由查询基线 | 五条中文正例预写两次英文改写；其余为固定英文/中文控制查询 | 首次非空即停；两次均空则停止 |
| 同语言候选 | 首次原样使用宿主原问；仅确认 `no_matches` 后，使用一次预写的同语言改写 | 非空但证据不足不触发此空召回策略；无授权、错误或未知结果不重试 |

这是固定查询的机制对照。原生产 Agent 允许模型自主选查询，并非规定必须用英文；**基线不能代表真实 DeepSeek 查询分布**。所有改写为预写测试输入，没有新增翻译器/LLM 入口。候选只有一个 Dev 选择函数，沿用原 SearchArguments 长度校验，不截断；中文/英文字符检查只是测试保护，不能验证改写语义或推广到任意语言。

## 2. 真实 PG/MCP 结果

每个策略均完成 12 条任务，共 24 条观测；每次实际搜索均经原 ToolRegistry、真实只读 MCP 和原引用校验。八份短文均为一个 chunk，chunk 与 Source 粒度在此样本高度相关，不能证明长文/多 chunk 的效果。Recall@5 使用返回片段与预定相关 chunk 的交集，不以分数反推相关性；来源覆盖按不同 Source 去重。

| 指标及真实分母 | 脚本化基线 | 同语言候选 |
|---|---:|---:|
| 正例 Recall@5，8 条逐任务宏平均 | 37.5% | 100% |
| 正例正确来源覆盖，10 个必需来源引用 | 5/10 | 10/10 |
| 正例完整来源覆盖，8 条 | 3/8 | 8/8 |
| 正例错误空召回，8 条 | 5/8 | 0/8 |
| 无关 chunk 命中 / 实际返回 chunk（逐任务去重再汇总） | 0/5 | 0/12 |
| 出现无关片段的任务，12 条 | 0/12 | 0/12 |
| 全部相关背景 Recall@5，10 条宏平均（含两个证据不足例） | 30% | 100% |
| 全部相关来源覆盖，12 个必需背景来源引用 | 5/12 | 12/12 |
| 实际搜索次数 / 二次搜索任务数 | 21 / 9 | 14 / 2 |

两条完全没有相关来源的任务不计入 Recall 分母，其 Recall 为 null，不记为 100%。无关命中是本小样本实测零次，不能承诺生产零误召回。五条成对来源覆盖改善均来自中文原问与英文查询的对照，无正例回退；三个原生语言控制均不变。

全部逐项结果如下；`—` 为没有应召回来源，不能解释为答案已验证。

| Dev 任务 | 基线相关来源 | 候选相关来源 | 保留的问题/解释 |
|---|---:|---:|---|
| export | 0/1 | 1/1 | 基线两次 no_matches |
| roles | 0/1 | 1/1 | 基线两次 no_matches |
| quota | 0/1 | 1/1 | 基线两次 no_matches |
| keys | 0/1 | 1/1 | 基线两次 no_matches |
| maintenance | 0/1 | 1/1 | 基线两次 no_matches |
| english-control | 1/1 | 1/1 | 英文→英文控制 |
| two-export-roles | 2/2 | 2/2 | 双来源中文控制 |
| two-quota-maintenance | 2/2 | 2/2 | 双来源中文控制 |
| missing-biometric | —，空 | —，空 | 均检索两次仍空，保留无对应来源 |
| missing-price | —，空 | —，空 | 均检索两次仍空，保留无对应来源 |
| insufficient-retention | 0/1 | 1/1 | 角色文档没有审计日志保存年数，不能补造数字 |
| insufficient-causal | 0/1 | 1/1 | 维护文档没有随机实验，不能确认提高留存的因果结论 |

候选的正例全部在首查召回，**没有正例证明第二次同语言改写带来额外收益**；候选的两次 fallback 都用于真正缺来源的负例，仍为空。不能把整个改善归功于 fallback。

## 3. 完成判定与提案结论

对实际所得工件只调用原 `validate_submission` 做对抗性 complete 候选检查，没有执行真实模型、生成完成收据或最终报告。基线正例检查接受 3/8、候选 8/8；候选另有两个证据不足例因取回相关背景而允许检索 complete 候选，基线没有取回背景。**RAG 检索完成、证据可定位、最终业务问题可回答是三件事。** 原文中的“未规定年限/没有实验”可以支持诚实说明局限；检索接受并不证明存在年限数字或因果事实。这不是观察到了真实模型错误完成，也不将因果证明要求全部压给 RAG Worker。

预注册的保守提案 Gate 要求两个以上主题提升、无正例回退、无关命中比例不增加，以及不新增证据不足例的 complete 候选接受。最后一项未满足，故 Gate=false；这是对本次提案证据的限制，不是把 RAG 检索完成直接判成错误业务完成。报告层能否始终合法拒答/标明局限，本次未测，不能用召回改善替代该验收。

原问优先具有明确的机制收益，值得保留为下一次独立验证候选；但本轮没有足够依据直接改生产策略。尤其没有验证真实模型自主改写的语义保持、复杂/混合语言、长目标超过 512 字符、非空但漏来源、长文和最终报告边界。最小后续验证方向是仅比较首次原问优先，并单独验证有正例触发的同语言 fallback；仍使用原 Gateway/工具调用与 Journal，不能静默改写已登记调用参数或增加调用预算。本轮没有实施该方案，不提出降低阈值、加 Reranker 或更换 Embedding。

## 4. 验证、材料与停止边界

Python 3.11：新候选保护测试 **13 passed**（0.73 秒）；既有定向回归 **7 passed**（9.84 秒，2 个预导入警告），合计 **20 passed、0 failed/skipped**。后者包含两个真实 PG/MCP 测试（原 Worker 两次搜索硬上限、owner/伪造 index 拒绝），以及五个脚本化完成协议/业务结论分离用例。没有运行完整 pytest 或 Python 3.13 回归；本轮未改变产品源码。

```powershell
.venv\Scripts\python.exe -m pytest artifacts/p7/phase3b-language-strategy/test_candidate.py -p no:cacheprovider -q --tb=short --junitxml=artifacts/p7/phase3b-language-strategy/policy-tests.xml
.venv\Scripts\python.exe artifacts/p7/phase12-integration/isolated-check.py pytest tests/test_rag_postgres.py::test_real_worker_retrieval_attempts_are_bounded_without_changing_fixture_loops tests/test_rag_postgres.py::test_document_owner_scope_and_forged_index_are_denied tests/test_rag_completion.py::test_successful_retrieval_is_separate_from_unverified_business_conclusion tests/test_rag_completion.py::test_true_hash_and_nonempty_semantic_retrieval_do_not_prove_relevance tests/test_rag_completion.py::test_empty_and_nonempty_insufficiency_have_distinct_terminal_reasons -p no:cacheprovider -q --tb=short --junitxml=artifacts/p7/phase3b-language-strategy/targeted.xml
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe check artifacts/p7/phase3b-language-strategy
.venv\Scripts\ruff.exe format --check artifacts/p7/phase3b-language-strategy
git diff --check
```

Ruff、局部 format、Diff 均通过。既有文件 LF/CRLF 提示保留。仅在既有隔离实例追加两个新 Dev Corpus，授权回归夹具另追加一个新测试 Corpus；未迁移、重新 Seed、删数据或改变权限策略。检索阶段零数据库写入、零 DeepSeek 调用。

本轮只新增本报告和本机忽略目录材料：[固定输入/来源/评分方法](../artifacts/p7/phase3b-language-strategy/study.json)、[候选函数](../artifacts/p7/phase3b-language-strategy/candidate.py)、[原工具对照脚本](../artifacts/p7/phase3b-language-strategy/compare.py)、[24 条完整引用观测](../artifacts/p7/phase3b-language-strategy/results.jsonl)、[汇总](../artifacts/p7/phase3b-language-strategy/summary.json)、[独立指标复核与全部失败/负例](../artifacts/p7/phase3b-language-strategy/metrics-audit.json)、[新保护测试 JUnit](../artifacts/p7/phase3b-language-strategy/policy-tests.xml)、[回归 JUnit](../artifacts/p7/phase3b-language-strategy/targeted.xml)、[最终完整性检查](../artifacts/p7/phase3b-language-strategy/validation.json)。原件和向量没有进入公开 Trace；本地材料未上传，不能宣称外部可下载。

开始时记录的 **599 个既有文件字节 hash 未变**，包含 Phase 1/2、Phase 3A、历史 Gold/Seal/Scorer 及原始结果；五个新输入/候选/执行文件在首次检索前冻结后也未改动。原 31 条已观测和 29 条 not_run 保留。本轮没有修改生产 RAG、Prompt、P3、预算或上下文管理，未进入 Phase 4/Gate 3，未暂存、提交或推送。
