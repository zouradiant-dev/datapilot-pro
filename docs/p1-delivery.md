# P1 / D2–D3 实际交付记录

日期：2026-10-21（Asia/Shanghai）。只交付文件解析、画像、Schema 建议与确认。本轮未进入 P2；没有新建数据库表/角色/迁移，没有增加 Multi-Agent 或 UI。

## 实现和文件

- 新增 `src/datapilot/ingestion/`：contracts（含六项核心 DTO）、common（配额/序列化）、parser（CSV/统一入口）、xlsx（ZIP/XML 预检与精确数值）、types（确定性标量）、profiling、confirmation、cli，以及模块说明。
- `src/datapilot/cli.py` 仅注册 ingest preview/confirm 并更新帮助文字；原 db-init/migrate/seed/health/ask 保留。
- 新增 5 个 `tests/test_ingestion_*.py`，共 **81 个本地测试用例**（含参数化），覆盖格式/资源/攻击、完整数据类型验证、质量/关系、覆盖配置和 CLI。不是 81 个业务分析 benchmark 任务。
- 新增 `tests/fixtures/ingestion/` 三份合法合成文件与 manifest；`scripts/generate_ingestion_fixtures.py` 可逐字节复现，无生产资料。
- pyproject.toml/uv.lock 增加 openpyxl=3.1.5、defusedxml=0.7.1、传递依赖 et-xmlfile=2.0.0；原锁定包没有删除或升级。
- 更新 README/AGENTS、架构/路线图和 ADR-002 的 P1 状态；新增 [使用与边界说明](data-ingestion.md)、本记录与 [机器可读结果](research/p1-results.json)。保留此前未提交的 P0/研究改动。

严格契约包括 UploadFileInfo、ParsedTable、ColumnProfile、SchemaProposal、SchemaConfirmation、ParseError。所有输入、原始行列/文本、解压、XML、预览均有限额。确认是审阅配置，不是数据库权限。

CSV 支持 UTF BOM、显式编码、分隔符、表头检测/选择、中文/重复/空列名。XLSX 支持多 Sheet 与选择、空列、公式文本、数值原始词法、日期/格式提示；不执行公式/宏/外链。类型由采样建议+全列验证确定，保护前导零和 Decimal 精度，歧义回退 TEXT；主键/关系候选、空值/重复/IQR 和原名映射均可预览。用户覆盖重新全列验证，原件/Proposal/选项变化使旧确认失效。

## 真实执行与结果

本机 Windows / Python **3.11.16**，实际下载、锁定并安装上述新增依赖。首次离线锁定因无缓存失败，随后联网完成；最终 `uv sync --locked --offline --python .venv/Scripts/python.exe` 成功（91 个通用锁定包，当前平台检查 87 个安装包）。

最终回归命令在仓库根目录执行：

```powershell
$env:PYTHONUTF8 = '1'
$env:DATAPILOT_RUN_DB_TESTS = '1'
$env:DATAPILOT_RUN_LIVE_TESTS = '0'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --cov=datapilot.ingestion --cov-report=term-missing --cov-report=json:artifacts/p1/coverage.json --junitxml=artifacts/p1/pytest.xml
.\.venv\Scripts\ruff.exe check . --output-format concise
.\.venv\Scripts\ruff.exe format --check .
```

实际结果：**140 passed, 1 skipped in 16.37s**。

| 类别 | 本次结果 | 说明 |
|---|---:|---|
| P1 新增本地文件/契约/CLI | 81 passed | 真实 CSV/XLSX 和故障包，无 DB/模型调用 |
| 原单元/Mock/Mock HTTP | 48 passed | 不等同真实模型 |
| 原真实 MCP stdio 协议 | 1 passed | 真子进程、握手、工具列表；无 DB |
| 原真实 PG17+pgvector 集成 | 10 passed | Fake 决策+真实 MCP/PG、独立 SQL、角色/超时/错误/向量回滚 |
| 原真实模型 E2E | 1 skipped | 未配置 API 凭据且未 opt-in，不声称 live 通过 |

P1 ingestion 范围覆盖 **916/993 statements，约 92.25%**，不是全项目或数据库 Server 子进程覆盖率。Ruff check/format 最终通过；中途格式检查发现的长行与文档代码块已修正。

## 实际运行的 CLI 示例

以下命令使用正常入口实际成功执行，不依赖数据库/模型：

```powershell
uv run --locked --offline datapilot ingest preview tests/fixtures/ingestion/customers_utf8_bom.csv --header present --output artifacts/p1/customers-preview.json
uv run --locked --offline datapilot ingest preview tests/fixtures/ingestion/saas_multi_sheet.xlsx --header present --output artifacts/p1/workbook-preview.json
uv run --locked --offline datapilot ingest confirm tests/fixtures/ingestion/saas_multi_sheet.xlsx --proposal artifacts/p1/workbook-preview.json --reviewed --output artifacts/p1/workbook-confirmation.json
uv run --locked --offline datapilot health
```

CSV 预览为 **1 表、3 行**；XLSX 为 **3 表，数据行分别 3/3/1**。确认 JSON 已生成，源/Proposal hash 匹配；公式仍为 `=2+2` 文本，空列保留。文件已存在时不覆盖，复现请用新输出名。

健康实测：status=healthy、postgres_version_num=170011、pgvector=0.8.6、migration=0001、customers=240。原业务/测试/迁移/Compose 指纹与 P0 基线核对，只有预期的 cli.py、pyproject.toml、uv.lock 三项变化，原 SQL/MCP/Graph/DB 源码及所有既有测试未改。

本地日志、JUnit、coverage、CLI JSON、完整性记录位于被忽略的 `artifacts/p1/`。提交摘要不包含密钥、DSN 或真实经营数据。

## 未完成与限制

- 未实现 P2：受限建表/插入、Dataset Registry、动态 MCP 查询；目前不能查询上传数据。
- 未增加多 Agent、RAG、UI、真实模型推理或生产租户隔离。
- 本机只验证 Python 3.11.16/Windows；既有 CI 配置覆盖 3.11/3.13，本轮未运行 GitHub CI 或本机 3.13。
- 不支持 XLS/XLSM/XLSB、ZIP64/分卷、复杂合并表头或全部 Excel 显示/公式语义；公式只作文本，宏/外部关系拒绝。旧编码/区域数字/日期含义不能可靠自动判断时，须用户明确选择或保留 TEXT。
- deadline 是协作式检查，不是 OS 沙箱；资源保护与输出限额已测试，不声称可承受任意恶意宿主或无限大文件。

本阶段至此停止。
