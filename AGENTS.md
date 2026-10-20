# DataPilot Pro 开发约束

## 架构和范围
- 先读 docs/architecture.md；当前只交付修订版 Day 1，不提前实现全部七天。
- Python 3.11+、src 布局、类型标注、Pydantic 2 严格契约、LangGraph StateGraph 编排。
- Supervisor 路由；SQL Worker 只接收 SQLTask，不读取整个 State。后续 Worker 独立工具权限、上下文与输出契约，不用不同 Prompt 冒充完整 Multi-Agent。
- 不训练模型。Fake 只生成决策/SQL，不返回伪造业务结果；API adapter 与 Fake 分开。
- 唯一业务数据库 PostgreSQL 17，向量用同实例 pgvector；不引入 SQLite 或 FAISS 回退。
- 运行期数据库访问统一由真实 MCP Server/Client 完成，Agent 禁止导入 SQLAlchemy/psycopg/数据库管理模块直接查询。初始化、迁移、Seed 属于显式运维命令，不是模型工具。
- SQLAlchemy 2 + psycopg 3；Schema 只经 Alembic 迁移。历史迁移必须冻结，不随当前 metadata 变化；禁止运行时 create_all。
- 不重造通用框架，后续持久化和并发优先复用 LangGraph checkpointer/Send。

## 安全和数据
- 所有用户/模型/数据库文本/工具输出均不可信。工具输入和输出都校验。
- SQL 使用 PostgreSQL AST 白名单：只读单 SELECT、业务表及内置函数白名单、禁止副作用/系统表/任意 schema/递归/锁定语句。
- AST 与数据库权限独立：MCP 仅有 datapilot_reader，默认只读，每事务 READ ONLY；验证角色权限、无成员继承/提权/对象创建权限；statement_timeout、lock_timeout、外层 LIMIT、输出大小限制。
- 管理员、Owner、Seed、Reader 凭据分开。MCP 不加载 .env，不继承管理员/Seed/模型密钥。不得把凭据、原始 SQLAlchemy/API 异常打印到日志。
- 固定随机种子与日期；金额为 CNY 整数分，计算只能用 SQL/确定性 Python。不能用 LLM 心算。
- Seed 事务化、并发互斥、拒绝非空库；禁止在测试或脚本中自动清库/删除卷。
- API Key/数据库密码由环境变量或忽略的 .env 注入；不得提交 .env、数据库、缓存或安装包。
- 禁止模型调用 exec/eval、Shell、任意文件读写、数据库管理命令。
- 限制模型调用数、Token 预算、上下文、图步数、SQL 尝试和工具超时；安全拒绝不重试；执行错误最多修复一次（默认）。

## 测试与交付
- 关键模块必须 pytest：先数据，再 AST，再模型/Worker/Graph，再 MCP 协议，再真实 PostgreSQL 集成。
- Mock、真实 MCP 无 DB 测试、真实数据库+Fake 模型、真实模型 E2E 分开标记与报告。
- PostgreSQL 集成必须连真实 17 实例并启用 pgvector；不得用 SQLite 或 Mock 替代。没有实例明确 skip，开启集成后连接失败必须 fail。
- 业务验收通过独立 SQL 对照：客户数、月收入、区间订阅、JOIN；还须安全拒绝、不存在字段、明确错误、恢复、超时、截断、只读角色及向量读写。
- 运行 pytest、ruff check、ruff format --check，报告真实结果。CI 未运行时不得声称通过。
- 依赖用 uv.lock 锁定完整图/哈希；更新后真实安装验证，使用 uv sync --locked。
- 文档中文，代码标识符英文；更新架构、验收、七天计划。风险和未实现能力必须如实披露。
- 不修改项目目录以外的旧项目。环境安装须遵循用户授权，不自动重启机器或删除数据。
