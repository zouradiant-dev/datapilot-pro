# ADR-010：P6A 版本化文档与受限 pgvector 检索

日期：2026-10-21；基线 cdccf28。只实施 P6A，不进入报告桥接/UI/多租户。用户新增的 v2.3 文件作为输入保留，不覆盖。

## 复用与缺口审计

已有 RetrievalTools.search / Document / SearchResult、RAG Worker、ToolRegistry、read_context、Artifact SHA、L0–L4、预算/取消、真实 MCP、P2 DatasetScope、P3 Evidence 和 P5B 官方恢复。它们不另建。缺少可信文档摄取、版本/跨度、Embedding、授权向量后端和来源复核。旧 rag.document_chunks 及 fixture 是历史基线，不替代新链路、不修改历史迁移。

新增 rag/ 的 DTO、文本解析/切块、本地 Embedding、摄取和只读 Repository；新 0005；在原 MCP Server/Client 中增加独立 RAG profile，在 Coordinator/Gateway 的既有工具和 Journal 边界接入。P3 Evidence 不与检索分数混同。

## 决策

- 首版仅 UTF-8（含 BOM）TXT/Markdown，把正文当纯文本；不渲染、不执行指令、宏、脚本或链接，不支持 PDF/HTML/压缩包。限制文件数量/大小/总字节、字符/解析时间、chunk 长度/数量和嵌入输入；跨度按原件解码后的 Unicode 字符与行号解释，原始字节 hash 单独保留。
- 选固定 Qdrant ONNX 转换的 BAAI/bge-small-zh-v1.5（512 维、CLS + L2、最大 512 tokens），固定仓库 revision 和文件 SHA；仅 CPU 推理，不训练。依赖 ONNX Runtime/tokenizers；模型只能显式下载到仓库缓存，MCP 不联网下载、不接任意模型路径/URL。缺模型明确失败，不能用随机向量替代。小规模先用 pgvector 精确 cosine 检索与 scope 索引，不引入近似索引召回不确定性；检索分数不等于事实正确。
- 新增 rag_ingest 与 rag_reader，均无 DDL/角色继承/业务 SQL 权限；前者只 SELECT/INSERT 固定新表，后者只 SELECT。Admin/Owner 显式初始化与 Alembic 0005 管理固定 Schema。MCP 无写入/摄取工具，不借给 SQL Worker RAG 凭据，RAG 无 SQL 会话。
- Corpus 身份绑定本地 owner、SaaS 或固定 Dataset/version；宿主显式批准来源与目标。每次索引版本绑定完整文件版本集合、模型文件/推理版本、chunker 配置和检索器版本。新内容/切块/模型形成新不可变索引；不自动切换或删除旧索引。
- RagScope 由可信宿主绑定 corpus/index/document 白名单与 DatasetScope；模型只有 query/top_k。白名单必须完整匹配一个批准的索引快照，避免部分授权时暴露该快照其他文件元数据；更小授权集用独立 Corpus 或新快照。MCP 每次校验 scope、源版本与 hash/原文跨度，不从文档或摘要恢复权限。空检索 unavailable；scope 越权明确拒绝，不能伪造引用。
- 复用原 Document 契约并追加可选定位元数据，保留 fixture 回归；真实检索必须带 source/document/chunk IDs、原件/片段 hash、index/model/chunker/retriever 版本、offset/行号、top_k/score。真实 MCP 客户端与宿主验证器重新校验，Artifact 只是执行引用，不升级为 P3 verified 业务证据。
- Durable 继续用原官方 Saver/Journal：RAG scope 与索引清单绑定运行身份；恢复重新建 MCP 会话、重新校验版本/引用。未知 MCP 超时仍按 P5B uncertain 停止，不用“只读”假装未执行；确认事务失败的检索错误才走有界重试。完整正文只在私密工件/Checkpoint，公开 Trace 不含文本或向量。

源码依据：已核对原 tools.py/loop.py/coordinator.py、MCP profile/DatasetScope、P3 Registry、P5B session/journal；外部资料见 rag-pipeline.md 的官方来源，不复制第三方框架代码。性能及模型效果以实际测试为准。
