# ADR-002：动态上传表、导入服务与受控查询权限

日期：2026-10-21。状态：P2 已落实下述最小文件导入/版本/查询闭环，后续语义/证据与生产权限仍为规划。Day 1 Reader 行为保留。

P1 实施补充：已实现本地 Parser/Profile/Preview/Confirm（见 [说明](../data-ingestion.md)），尚未执行本 ADR 的数据库导入/角色/动态查询设计。确认配置需在未来 P2 可信入口重验，不因本地 reviewed 字段而获得 DDL 权限。

P2 实施补充：新增冻结迁移 `0002_dataset_catalog.py`，只创建 catalog.datasets/versions/tables/columns；Schema/角色由显式 `db-init` 创建。uploads 归 datapilot_ingest 所有，catalog 归 Owner；原 0001 未修改。确认被重新完整计算，导入/元数据/逐表 SELECT 授权/ready/指针同事务。客户端作用域不是工具参数，未指定版本时首次访问固定至会话结束。原件在忽略目录按 hash 原子发布，数据库失败后保留快照；用 catalog source_ref 对账，未实现自动清理或完整故障事件 Registry。具体接口、授权边界和验收见 [P2 说明](../dataset-ingestion.md) 与 [交付](../p2-delivery.md)。以下“拟/目标”保留设计背景，P2 未实现 metric_bindings/evidence/import_batches 等未来表。

## 背景与迁移所有权

现有 SQL 策略只允许 `saas` 五表，`verify_reader` 固定验证 datapilot_reader，健康检查写死迁移版本 0001。原“Schema 只经 Alembic”规则需要明确动态表例外。

| 对象 | 变更所有者 | 边界 |
|---|---|---|
| saas、rag、catalog 的固定表/索引/约束 | 新 Alembic 迁移 | 历史 0001 冻结；不在查询期 create_all |
| 角色、Schema 命名空间及初始所有权 | 显式 admin 权限初始化，沿用既有 initialize 边界 | 先创建 catalog/uploads 再用 Owner 迁移固定表；不假设当前 Owner 有数据库 CREATE 权限 |
| uploads 下每次导入的物理表 | 独立受限 Ingestion Service | 已确认 Schema、事务化 DDL+插入+元数据+发布授权；不是 LLM 工具 |
| 运行检查点元数据 | Gate C 前明确专门迁移方案 | 当前无自动建表例外，见 ADR-001 |

uploads 的动态表不是为每个文件生成 Alembic revision，也不能让 SQL Agent 建表。原规则据此作范围明确的扩展，不放宽管理账号隔离。

## 导入过程与可信边界

`接收 → 隔离原件/计算 hash → 安全解析 → Profile/推断 → Preview → 用户确认 → 事务入库 → 发布版本`。

- 上传名只用于显示；物理路径/表名由服务端不透明 ID 生成，拒绝路径穿越、保留名称及标识符注入。列名规范化后仍保留原名映射；SQL 标识符使用驱动的 Identifier 构造，不拼接用户输入。
- CSV 识别 BOM、编码、分隔符；失败/歧义明确报告。XLSX 检查包内容与结构、压缩/解包上限、Sheet/行/列/单元格长度；不执行宏、公式、脚本或外部链接。不把公式缓存静默当当前真实数值。
- 初始候选配额：文件 10 MiB、10 Sheet、单表 100 列、累计 100,000 数据行；另需解压字节/entry 数、运行时限与单元格限制。P1 测试后配置化，不将压缩文件大小视为完整资源保护。
- 类型采用采样候选+全量校验。前导零 ID 保持 TEXT；金额精确 NUMERIC/Decimal 或已确认整数分；日期保留时区/格式歧义，未知类型保留文本或要求确认，不静默丢行/取整。
- SchemaConfirmation 绑定原件 SHA256、解析策略版本、proposal hash、Sheet 选择、列映射和业务确认；源文件或 Proposal 变化使旧确认失效。Schema 预览不是业务关联已成立的证明。
- 数据类型/DDL 来自代码白名单；确认界面不能注入任意 CHECK/DEFAULT/函数/SQL。关联键先作为可信确认后的元数据，实体唯一性和 JOIN 基数还需验证。

## 身份与权限配置

| 身份（目标） | 权限 | 不持有 |
|---|---|---|
| 既有 admin/owner/seed | 原初始化、固定迁移、合成 Seed | 不传入解析器/Worker/MCP |
| ingest | uploads CREATE、其创建表的写权限；catalog 必要元数据 DML；受控发布 SELECT grants | SUPERUSER/CREATEROLE/任意 schema DDL；模型 API Key |
| 既有 datapilot_reader | 原 saas 五表只读 | uploads、rag、导入 DDL |
| upload_reader（拟新增独立配置） | 已发布上传表的 SELECT、必要 schema USAGE，只读/超时 | INSERT/UPDATE/DELETE/TRUNCATE/CREATE、角色继承/提权 |
| catalog 服务 | 受限元数据访问、授权与版本解析 | 任意业务 SQL 或模型自报权限 |

首版单用户：upload_reader 可读该本地用户已发布表，**选定 Dataset/Version 的进一步限制由可信 Server 作用域+AST 精确白名单实施**。这不等于数据库级逐数据集或生产租户隔离；若要求该隔离，应另建每数据集角色/RLS/独立库的 ADR，不虚称现有角色已经做到。

MCP Server 使用独立凭据配置与角色验证 profile，不简单删除 verify_reader 的检查或把所有表塞入 BUSINESS_TABLES。保留 saas profile 的拒绝行为，新增 upload profile 验证只读、无成员继承、无写入/创建权限、只允许已发布表。运维 Seed 和 DB 健康检查是非模型基础设施例外，业务问答始终走真实 MCP。

## Registry 与事务

catalog 拟保存 datasets、versions、tables、columns、relations、import_batches、mapping/confirmation、metric_bindings、evidence 的最小必要元数据，固定结构用新迁移。不是要求 P2 一次建完所有未来模块。

生命周期：`previewed → confirmed → importing → ready / failed → archived`。Preview 文件状态与数据库事务状态分开；ready 只在表、数据、元数据和 SELECT 授权原子提交后可见。失败回滚；失败诊断不可泄露值/凭据。

重导入创建新版本，不覆盖旧版本。幂等键至少包含原件 hash、已确认映射/解析版本及目标数据集；内容相同而映射不同不能错误去重。文件 hash 不是业务记录去重键；后续增量连接器需要 external_record_id 和撤销/退款语义。发布版本在应用层不可变，受信 ingest 的所有权权限不等于数据库强制 WORM。

原件在受控目录保存并登记 hash/保留期，模型只拿 file_ref。文件系统与 PG 不共享原子事务：先安全保管原件，再提交 DB；失败保留可追踪孤立文件状态，清理走显式运维流程，不能假称跨文件系统原子性。删除需明确确认，追踪表/原件/证据/缓存；本轮及自动测试不删除现有数据或卷。

## MCP 契约草案

- `list_datasets()`：仅返回当前可信主体范围内的数据集摘要。
- `get_dataset_schema(dataset_id, version?)`：解析已授权 ready 版本，返回表列、映射、已确认关系/指标、质量限制。
- `query_dataset(dataset_id, version, sql)`：Server 从会话/服务端绑定 scope 解析物理表；模型参数只能在该范围内选择，不能扩大授权。检查语法/物理表/函数/cast、DB grants、READ ONLY、超时、外层 LIMIT 和输出体积。

返回 QueryArtifact/Evidence ID、dataset/version、列类型、SQL/hash、row_count、truncated、时间、错误码。truncated 预览不能被当全量事实；全量统计要在数据库聚合或受控产物上计算。数据库名、schema、角色、文件路径不由模型自由选择。跨 Dataset JOIN 只在服务端明确绑定多源 scope 后支持，初版优先同 Dataset 多表 JOIN。

验收：非法文件/配额/字段注入、确认过期、事务回滚、并发重导入、版本切换、跨 scope 拒绝、系统表/写入拒绝、Reader grants、截断、原 saas 五表全部回归。参考 [ADR-003](0003-local-single-user.md)。
