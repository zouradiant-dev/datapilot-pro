# ADR-017：Qwen Embedding 的显式兼容绑定

2026-10-29，P7 Migration Phase 1。默认 BGE、历史封存与生产库不切换。

## 决策

- 继续复用原 RAG IngestionService、Repository、真实 stdio MCP、Worker/ToolRegistry、完成收据、Report 和 Durable。新增 `0008` 的 `rag.chunks_1024`，原 `rag.chunks vector(512)` 和 0001–0007 不变；两表共享原 Corpus/Source/Index 外键。精确 cosine 查询由内部维数白名单选择固定表，不接模型提供的表名或 SQL。
- 宿主 `RagScope.embedding_profile` 为显式 opt-in。缺省仍是 BGE；新增 CPU-FP32 / CUDA-FP16 两个固定 Qwen profile。ModelSpec 固定原生1024维、同一权重 revision、六个文件 SHA 和推理 recipe，精度不同形成独立 IndexVersion。Scope 不含任意模型路径/可执行命令/阈值工具参数。
- Qwen Search 与原始 Goal Score 使用独立策略名称和新 Dev 的校准记录；策略 SHA 写入 IndexManifest，进入 IndexVersion。数值相同也不能混用 BGE 策略。宿主 `min_score` 只可提高校准下限。Required/Supplement、Partial/fact_coverage、P3 和权限验证不改。
- 现有 BGE tokenizer=0.23.3 与 Qwen 已验证 Transformers 4.57.1 的约束冲突。保留原 `pyproject.toml`、`uv.lock`、Python 环境和缓存；单独锁定 `.venv-qwen` 依赖。它执行同一 MCP Server 源码，不是第二个检索服务。Qwen 显式使用该固定部署环境，禁止自动下载、远程模型代码和 CPU/GPU 静默降级。BGE 额外校验其声明的原依赖，不能将 Qwen tokenizer 的输出标成旧 recipe。
- RagScope/IndexManifest 新字段缺省时从序列化投影省略，保留旧 hash。原 `retrieval_goal` 接收可选可信检索句柄，仅将实际模型的 Goal 策略穿透原编排、报告及持久身份构建；不改 Journal/Ledger/Saver、Verifier 算法或恢复引擎。恢复仍重查宿主 scope、索引和原工件，模型/精度/策略错绑拒绝。
- 只在全新隔离测试库迁移；请求中不执行 DDL。生产 Web 入口不选择新 profile，不自动迁移已有库。超时仍为10秒；取消/超时不证明外部调用未执行，unknown 继续阻断自动重发。

## 边界与后续

本轮验证 Windows、固定 Python3.11 Qwen 子进程和3.11/3.13宿主；不宣称 Linux/CUDA全平台部署完成。初次GPU依赖/模型冷加载存在超过10秒的观察，需单独做稳定冷启动及资源竞争准入。任何生产切换、长期模型驻留、Web绑定、付费模型或新 Benchmark 都需下一阶段授权。实测、失败历史及命令见 [交付报告](../research/p7-qwen3-embedding-migration-phase1.md)。
