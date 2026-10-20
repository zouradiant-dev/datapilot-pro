# P2：受限导入、Dataset 版本与 MCP 查询

范围为 Roadmap D4–D5 / W4–W5，前置 P1 解析/确认已验收。运行条件为可信本地单用户、真实 PostgreSQL 17 + pgvector；不引入 SQLite/FAISS、API/UI 或新 Agent。

## 环境升级

已有 Day 1 数据的仓库根目录执行：

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked
uv run --locked python scripts/configure_local.py --add-upload-roles
uv run --locked datapilot db-init
uv run --locked datapilot migrate
uv run --locked datapilot health
```

配置脚本仅向忽略的 `.env` 补充缺失的 ingest/upload_reader 独立随机密码和 DSN，不覆盖既有角色；部分配置不完整时拒绝自动改写。远端实例须由操作者在本地环境设置对应变量。不要把密码发到聊天或提交 Git。首次创建全新环境仍按 README 的 configure_local→Compose→db-init→migrate→seed；已有数据不要再次 Seed。

`db-init` 使用 Admin，创建 catalog（Owner 所有）、uploads（Ingest 所有）和两种非管理员身份；迁移只使用 Owner，新增 `0002` 创建四张固定 catalog 表。历史 `0001` 未改。health 对照 Alembic head，配置上传 Reader 时检查 catalog 四表及角色权限。

| 身份 | P2 权限 | 禁止 |
|---|---|---|
| datapilot_owner | catalog/saas/rag 固定迁移及显式授权 | 不进入任何 MCP 子进程 |
| datapilot_ingest | uploads CREATE/其对象写入，catalog 必要 SELECT/INSERT/UPDATE，逐物理表授予 SELECT | saas/rag 读写、public CREATE、DB CREATE/TEMP、角色成员/提权；不进入模型工具 |
| datapilot_upload_reader | catalog 元数据 SELECT、已发布 uploads 精确表 SELECT | 写入、DDL、TEMP、SET ROLE；没有 SaaS 凭据 |
| datapilot_reader | 既有 saas 五表及健康元数据 SELECT | uploads/catalog、写入和 DDL；原 SaaS 行为保留 |

所有角色保持 NOSUPERUSER/NOCREATEROLE/NOCREATEDB/NOREPLICATION/NOBYPASSRLS/NOINHERIT；MCP 还会检查无角色成员和实际 grants。默认只读可由用户更改，因此实际权限和每事务 READ ONLY 均保留。

## 导入契约与原子性

1. `ingest preview` 与 `ingest confirm` 继续只处理本地文件，不加载数据库/模型设置。
2. 可信 `ingest import FILE --confirmation JSON --name NAME [--dataset-id ID]` 有界读取原件一次，从同一 bytes 重新解析、生成建议、重建覆盖和完整确认。原件、映射、精度、主键/关系或 hash 任一不匹配即拒绝；不能靠伪造 reviewed/hash 获得 DDL 权限。
3. 原件以 `SHA256.csv/xlsx` 保存在忽略的 `artifacts/uploads/sources/`。写入临时文件、fsync，再同目录独占硬链接发布；同 hash 并发只看到完整快照，已存在文件校验失败不会覆盖。不得用上传名作物理路径。存储文件系统须支持硬链接（如 NTFS/ext4），失败返回明确错误。
4. Ingest 在单个 PostgreSQL 事务内获取 Dataset advisory lock，生成服务端物理表名，使用 SQLAlchemy 引用列/表和确定性类型，按 1000 行批量参数化插入。主键只有经过全量确认才建约束；关系保存在确认 JSON，P2 不创建 FK 或业务语义绑定。
5. 记录 catalog、逐物理表 GRANT SELECT、版本 ready 和 current_version 更新在同一事务提交。任何数据库故障整体回滚，不留下部分表/数据/元数据/授权；旧版本保留。

Name 为最多 63 个 ASCII 字母/数字/下划线，原始中文、空/重复表头作为数据保留。显示 Dataset 名称最多 128 字符，只接受普通文字，不接受路径或 SQL 表达式。物理表名由 Dataset UUID/version/序号生成；从不执行用户提供的 DDL、默认表达式或 SQL 类型。

金额直接使用确定性 Decimal→NUMERIC(precision,scale)，无 float 中转或隐式四舍五入；前导零为 TEXT。DATE、BOOLEAN、BIGINT 及 TIMESTAMP 均按已确认规则。时间戳列拒绝混用无时区/有时区值；有时区值入 TIMESTAMPTZ 后以 UTC 返回，原文本仍在原件中。XLSX 的源 XML 若已有浮点尾差会精确保留，不将未经业务确认的“显示两位金额”视为真实值。

P1 的仅表头/无数据表无法确认，P2 明确拒绝导入；合法 SQL 查不到行时正常返回空结果。查询最多返回 100 行（配置上限 1000）、单文本结果单元格 4096 字符、结果 1 MB；超长单元格明确错误，不悄悄改值。预览本身的限额见 [P1](data-ingestion.md)。

## 元数据与版本

| 表 | 主要字段/约束 |
|---|---|
| catalog.datasets | dataset_id、唯一显示名、current_version、创建时间；当前指针有延迟校验的复合 FK |
| catalog.versions | (dataset_id,version) PK；同 Dataset 的 confirmation hash 唯一；源 hash/ref/文件名/格式/parser/完整确认、状态和行数 |
| catalog.tables | Dataset/version/table_id、Sheet 原名、全局唯一物理表名、行数、确认主键 |
| catalog.columns | Dataset/version/table_id/position、source_column、原名、规范名、逻辑/实际 SQL 类型；规范名在表内唯一 |

单用户本地相同显示名映射到稳定 UUID；新名称创建新 Dataset，显式 dataset_id 必须已存在且名称匹配。同确认重复导入返回 reused=true/原版本；新内容或已确认映射变更建新版本，旧物理表不改。重复旧确认不会意外切换 current_version。`datasets activate ID --version N` 只激活已 ready 的历史版本，使用 Ingest 身份，永远不注册为 MCP 工具。

快照与数据库不共享事务：数据库失败保留 hash 快照，诊断返回明确失败，可按 catalog.source_ref 对账未引用快照。没有自动清理、完整故障事件 Registry 或累计磁盘配额；崩溃也可能遗留临时文件，需显式运维处理。测试不清表、不清库、不删卷，成功合成测试版本会保留。

## MCP、授权与每请求 SQLPolicy

宿主调用 `dataset_session(settings, DatasetScope(bindings=[DatasetBinding(dataset_id=...,version=...)]))`。这个 Python 接口是可信本地入口，不是模型工具。版本为 None 时首次读 ready/current 后固定至会话结束；并发解析有锁。新版本发布/激活后现有会话保持旧版本，新会话读取新指针；也可显式固定历史版本。

| 模型可见工具 | 参数 | 服务端行为 |
|---|---|---|
| list_datasets | 无 | 只列宿主绑定的数据集/实际固定版本，无 wildcard |
| get_dataset_schema | dataset_id | 检查绑定，读取 ready 元数据、原名映射和精确物理表，验证实际 SELECT grants |
| query_dataset | dataset_id,sql | 只为该 Dataset/版本生成 SQLPolicy，执行 SQLGlot + 角色/grants + READ ONLY + 超时/lock timeout + LIMIT/结果限额 |

没有 scope/tenant/role/version/physical_tables 工具参数。伪造额外参数不改变绑定，未授权 dataset_id 明确拒绝。作用域同时包含 A、B 时，也不允许 query_dataset(A) 引用 B 的物理表。CTE/子查询/UNION 的实际关系同样检查；系统表、saas、catalog、危险函数/语句不可绕过。原 SaaS 的静态五表 profile 继续默认生效。

两个 stdio 会话不互传 Reader DSN，也不继承 Admin/Owner/Seed/Ingest/模型密钥或父进程 scope。客户端按能力限制工具名，校验 DTO、Dataset/version/source hash 稳定性和结果 hash；SDK 支持 structuredContent 或 JSON 文本两种协议返回。SQL 错误保留清理后的明确错误码，正常领域失败不会被 SDK 的 ExceptionGroup 吞掉。

DatasetQueryResult 返回 dataset_id/version/source_sha256/query_sha256/result_sha256/result，其中结果 hash 不含运行时延。它是可对账查询产物，**不是** P3 Evidence Registry 或指标语义正确性的证明。

## 运行示例

完整命令见 [README](../README.md#文件入库与动态查询p2需要真实-postgresql)。CLI `datasets schema/query ID --version N` 将版本作为宿主选择传给 MCP，模型不能据此自行扩大权限。`datasets list --dataset ID` 可重复指定已选择 ID；无选中项返回空列表。

首版信任本地宿主、配置和运维 Ingest。upload_reader 在 DB 可读所有已发布上传表，逐 Dataset 边界由 Server scope/AST 约束；不等于生产逐租户 DB 隔离或恶意宿主 OS 沙箱。Ingest 仍拥有 uploads 表，版本不可变是应用约束，尚非 WORM。累计存储、生产认证/RLS、Schema 的业务含义、指标/证据 Registry、自然语言上传分析、多 Agent/UI 均在 P2 之外。
