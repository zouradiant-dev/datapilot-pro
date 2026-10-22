# ADR-013：HTTP 产品边界与原 Durable 生命周期

本轮用户明确授权 P6C。FastAPI 是唯一业务入口，Streamlit 是可替换的 HTTP 客户端；不在 UI 导入 Agent、MCP、数据库或维护代码。

可信本地主机发放会话并固定 owner，API 检查 Host/Origin/Session/CSRF。Dataset/version 与 Corpus grants 由可信导入/宿主授权建立；run_id 不构成授权。人工 Schema/Metric/审核须显式确认，LLM 无批准工具。

Web outbox 只记录幂等命令与 dispatch 状态；固定有界本地进程执行原 P5B run_durable。LangGraph 原 Checkpoint、Run 锁、Journal、预算及 P3/P4/RAG 证据是权威，HTTP 任务不能用内存 ask 替代。读状态不执行节点或修复 unknown 调用，恢复只走既有检查。

API 只返回有限状态/已验证报告/引用元数据，不暴露私密工件、原始行、SQL、Prompt、文档正文或凭据。默认回环监听；Docker 内部监听与仅回环端口映射必须单独说明。未来 React/Tauri 可直接复用同一 OpenAPI/DTO，生产认证/RLS 留 P10。
