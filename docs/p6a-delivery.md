# P6A 交付：授权文档与真实 pgvector 检索

日期：2026-10-21；基线 cdccf28。用户新增的 codex-prompts-v2.3.md 已读取并保留原内容。本轮只实施 P6A，保留 P0–P5B，不进入 P6B/P6C/P7/P10，不自动提交/推送。

本文保留初次交付与两次真实模型负结果。后续基于 1d9e96e 的完成控制/Stop Hook/恢复修复与补充语义验收见 [定向修复交付](rag-completion-repair.md)，不覆盖下面的历史记录。

## 修改文件与复用接口

| 文件/模块 | 实际修改 |
|---|---|
| rag/contracts.py、parsing.py | 权威 scope、版本 manifest、精确 locator、配额；纯 UTF-8 TXT/Markdown 解析、切块与原件 hash |
| rag/models.py、pyproject.toml、uv.lock | 固定 BGE 中文 ONNX/tokenizer 文件、512 维真实本地推理；固定 ONNX Runtime 1.31.0 / tokenizers 0.23.3 |
| migrations/versions/0005_scoped_rag.py、db/management.py、configure_local.py、.env.example | 固定四表、独立 rag_ingest/rag_reader；新增角色凭据保留旧值，不修改历史迁移/Seed/Volume |
| rag/storage.py | 单事务追加原件/索引/向量；精确 pgvector 检索、只读/超时/参数化 scope、原文/span/vector hash 验证 |
| rag/mcp.py、runtime/mcp_server.py | 在已有 MCP SDK/transport 下实现隔离 RAG profile 与客户端，无写入/SQL/任意文件工具 |
| orchestration/contracts.py、tools.py、coordinator.py、loop.py | 扩展可选定位元数据、宿主验证与真实检索次数上限；仅明确真实 RAG 的静态 FinalDecision 交付要求，不重写 Loop/DAG/Tool Registry；RAG Scope 固定在受保护前缀与 ContextScope |
| persistence/session.py、journal.py | 原 Durable 绑定 RAG/index/Dataset/source pin，原日志重建尝试数与重放，原 Serializer 增加有限 DTO；不创建第二个 Checkpointer |
| rag/cli.py、cli.py、scripts/rag_recovery_probe.py、measure_rag.py | 显式 model-fetch、reviewed ingest、read-only query、durable --rag-scope、故障演示与脱敏小样本测量 |
| tests/test_rag_contracts.py、test_rag_postgres.py、tests/fixtures/rag/ | 合法合成来源、固定同义 Gold、注入夹具、真实 CPU/PG/MCP/跨进程验证 |
| CI、.gitignore、README、AGENTS、架构/路线图/恢复说明、ADR-010、rag-pipeline.md | 部署与实际停止点；Python 3.13 隔离环境和模型缓存均忽略，不提交私密数据 |

原 RAG fixture 继续回归。context.py、context_contracts.py、memory.py 与迁移 0001–0004 不改；原 SQLGlot、业务 Reader、MCP、P3 Verifier、Gateway 预算/取消与 L0–L4 机制保留。

## 关键不变量

1. 用户明确批准具体文件与 target，模型无 ingest/DDL/下载能力；固定 role 和独立 MCP 进程隔离 SQL/RAG 凭据。Dataset 从可信 P2 Scope 绑定，新会话确认实际版本，不能靠文档或模型授予权限。
2. Source/Document/Chunk/index、模型文件与 chunker 版本/hash 都可复核。原件 BYTEA 与向量同事务追加，失败回滚；更新/切块重建保留旧索引，不隐式切换版本或删除数据。
3. RAG MCP 返回真实候选文本和定位/score，服务端、客户端与原任务 Verifier 复核；近邻分数不等于业务事实或 P3 verified。空结果明确 unavailable，错误引用/越权明确拒绝。
4. 完整候选存私密 Artifact 后才给模型预览/ref；公开 Trace 不含正文/向量。Durable 的可信授权/版本/预算/不确定调用边界继续生效，恢复不能从旧摘要重授权限。

## 真实运行与测试

本地 PostgreSQL 17.11 + pgvector 0.8.6，head 0005；原有 240 客户保留。显式运行 configure_local --add-rag-roles / db-init / migrate / health，无重 Seed/删卷。模型为固定提交/文件 SHA 的本地真实 BGE，不依赖 Embedding API Key，不使用随机向量伪装真实模型。

```powershell
$env:PYTHONUTF8 = '1'
$env:DATAPILOT_RUN_DB_TESTS = '1'
.venv\Scripts\python.exe -m pytest -q --tb=short
.venv-313\Scripts\python.exe -m pytest -q --tb=short
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
git -c core.safecrlf=false diff --check
```

| 最终真实执行 | 原样结果 |
|---|---|
| Python 3.11.16 最终全量，真实 PG 开启 | **459 passed, 1 skipped in 406.48s (0:06:46)** |
| Python 3.13.15 最终全量，真实 PG 开启 | **459 passed, 1 skipped in 379.28s (0:06:19)** |
| 新增自动化测试 | **36 项：18 项本地契约 + 18 项真实 PG/神经 Embedding/MCP 集成**，均包含在两次全量 |
| Ruff / format / whitespace | 全部通过 |
| 跳过项 | 常规 live API pytest 未开启 opt-in；不把 Mock/本地 Embedding 当作供应商推理 |

JUnit 为 460 tests / 0 failures / 0 errors / 1 skipped，分别在忽略的 artifacts/p6a/final-311.xml 和 final-313.xml。两次均在最后的真实 RAG 静态交付格式说明变更后运行；机器记录见 [p6a-validation.json](research/p6a-validation.json)。两版 Python 均实际按 uv.lock 安装新依赖，并补跑 uv sync --locked --offline。GitHub Actions 已加入模型部署和角色配置；本轮未推送代码，不能冒称远端 CI 已运行。

已实际跑通 CLI ingest→query，示例“哪些措施有助于提升顾客续订意愿？”返回 onboarding.md 的精确原文段，cosine=0.6693642338920904；fixture=false、原件版本/片段 SHA、offset/行号齐全。原始输出仅保存在本地忽略的 artifacts/ 下。本文不把一个查询扩写为任务成功率或产品优势。

### 真实模型负结果与用量

另执行两次明确 opt-in 的 DeepSeek Flash smoke，均未通过任务完成验收，不属于上表自动化通过数：

| 实验 | 真实结果 | API 调用 / input / output / reported total / cache-read Token |
|---|---|---|
| 初次真实 Worker | 检索与 read_context 成功；最终返回叙述文本，`MODEL_OUTPUT_INVALID` 阻断 | 4 / 4688 / 788 / 5476 / 2432 |
| 明确静态 FinalDecision 交付格式后的新 Run | 两次检索后仍请求检索，`RAG_ATTEMPTS_EXHAUSTED` 阻断 | 3 / 2467 / 249 / 2716 / 1152 |

两次合计 7 次模型调用、8192 reported Token，保留失败耗用，没有自动重发。第二次 Run 含 MCP/加载等总时延 7416.291 ms；模型调用耗时和四个真实 MCP 同义检索的测量见机器记录。供应商报告的缓存读取不是可归因的节省额，缺少账单，不填写货币成本。

第一个失败仅促使真实 RAG 静态前缀更明确，没有接受任意文本代替 `artifact_ids`。第二个失败后保留限制与负结果，不再继续付费调参。真实 PG/本地神经模型/MCP 数据流与 Fake 决策下的 Worker/恢复已验证；**真实 DeepSeek RAG 自主完成质量仍未验收**。没有用直接检索成功或 fixture 抹掉该差异。记录只导出 usage、状态、来源定位/hash，不导出模型 Prompt、正文或向量。

## 安全、故障与失败案例

- 真实多文档同义 Gold：四个预登记问题分别检索 onboarding/billing/release，复核原件 substring、原始 SHA、片段 SHA、行号与 index。
- 新内容/文件版本/切块参数变化产生新索引；旧索引可读，相同输入幂等。注入中途故障证明新 Corpus/原件/索引整体回滚。
- 空文件、空 scope、无效 query、owner/索引/文件白名单伪造、跨 Dataset 拒绝；reader 无写入/DDL/业务 schema 权限。
- 原件、片段、向量分别被篡改时拒绝；定位/版本错误的客户端引用不接受。原文与向量不进入公开 Trace。
- 恶意 Markdown 要求查询/删除客户或读取 .env，RAG Worker 尝试后被既有能力边界拒绝；这证明权限约束，不宣称已全面解决模型对 Prompt Injection 的理解问题。
- 真实 PG statement timeout 注入与同一个真实 MCP 会话重试成功；未知 MCP 超时仍按 P5B uncertain 停止。正常暂停和工具结果提交后 crash 的新进程恢复复用已提交工件/响应，不重复扣减预算。
- 早期授权测试的短查询“客户上手”被 0.55 阈值过滤；未降低阈值，授权测试使用预登记的同义 Gold，短查询漏召回作为限制保留。
- 检索次数测试的 Fake 初稿没有 usage，先被原预算保护终止；为测试第三次请求的专门限制，fixture 明确返回 15 个模拟 Token，未放宽预算。常规未知 usage/超额回归仍执行。

## 未实现与风险

P6B 的 P3→P4 可信多来源报告、UI、API、Langfuse、多租户/RLS、长期 Memory、自动保留清理均未实现。PDF/HTML/OCR/混合检索/重排/ANN 优化不在本阶段。索引授权按完整快照，本阶段没有部分文件的 Merkle 证明或生产撤权系统；本地可信宿主负责是否继续提供旧授权。

四个合成同义问题不是完整经营分析评测；score 阈值未校准，短查询与不同领域可能漏召回。同步 CPU 推理/原件验证带来冷启动和 I/O，输入/时间有界但不是 OS 沙箱。模型下载依赖公开源可用；无模型就失败，不能降级为 fixture。真实 DeepSeek RAG smoke 尚未通过，结构化交付与有限重检索下的模型行为是已知风险；本地 Embedding 与 Fake 账本不能代替这项质量验证。

Python 3.13 使用仓库内隔离安装/环境；uv 额外生成的全局启动器经路径和创建时间确认后已撤回，未替换原 Python 3.11。仓库外用户文件、业务数据和 Docker Volume 未删除。

本轮停在 P6A，不自动实施后续阶段。是否接受当前检索基础设施交付、以及如何处理真实模型负结果，交由用户验收；不得据此宣称整个 Gate C 或 P6B 已完成。
