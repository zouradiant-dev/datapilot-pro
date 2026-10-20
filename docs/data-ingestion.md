# P1：CSV/XLSX 安全解析、画像与确认

状态：D2–D3 / Roadmap W2–W3 实现；只在本地读取文件并输出 JSON，不建表、不调用模型/MCP，不实现导入 commit、UI 或多 Agent。完整真实验证见 [P1 交付记录](p1-delivery.md)。

## 使用

依赖以 uv.lock 为准，新增 openpyxl 3.1.5、defusedxml 0.7.1，传递依赖 et-xmlfile 2.0.0；原依赖版本保持。openpyxl 官方说明默认 XML 防护不足，建议安装 defusedxml，本项目另行先做 ZIP/XML 预检，不仅依赖库默认配置。[官方说明](https://openpyxl.readthedocs.io/en/stable/#security)、[固定版本](https://pypi.org/project/openpyxl/3.1.5/)、[defusedxml](https://pypi.org/project/defusedxml/0.7.1/)。

在仓库根目录运行（不需要 API Key 或数据库）：

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked
uv run --locked datapilot ingest preview tests/fixtures/ingestion/customers_utf8_bom.csv --header present
uv run --locked datapilot ingest preview tests/fixtures/ingestion/invoices_semicolon.csv --header present
New-Item -ItemType Directory -Force artifacts | Out-Null
uv run --locked datapilot ingest preview tests/fixtures/ingestion/saas_multi_sheet.xlsx --header present --output artifacts/preview.json
uv run --locked datapilot ingest confirm tests/fixtures/ingestion/saas_multi_sheet.xlsx --proposal artifacts/preview.json --reviewed --output artifacts/confirmation.json
```

`--output` 的父目录应已存在；输出文件已存在则拒绝覆盖，重跑选择新文件名。输出可能含预览样本，应放在被忽略的 artifacts/，不要将真实上传文件或预览提交 Git。成功退出码 0，明确错误 JSON 写 stderr，退出码 2。

CSV 可用 `--encoding gb18030`、`--delimiter ';'` 或 `--delimiter tab`；XLSX 可重复 `--sheet Customers --sheet Invoices`。`--header auto|present|absent` 控制首行。API 的 ParseOptions.sheet_headers 可逐 Sheet 设置不同表头策略。

无 BOM 时默认严格 UTF-8；UTF-8/16/32 BOM 自动识别，显式相反字节序拒绝。其他编码需用户显式选择，不以替换字符或多编码盲猜伪造成功。分隔符从逗号/分号/Tab/竖线检测，无法确定返回 DELIMITER_REQUIRED。

auto 是可审阅启发式：有首行标签及后续数值/日期证据才建议表头，并输出 HEADER_INFERRED、header_row。全是文本等歧义情况保留首行为数据并标 HEADER_AMBIGUOUS；此时确认被拒，须显式指定 present/absent 后重新预览。格式错误、行宽不同不自动补救或丢行。全空记录跳过但报告数量，空列保留。

## DTO 与 Python 接口

`src/datapilot/ingestion/contracts.py` 提供严格 Pydantic DTO（extra=forbid、严格类型、长度上限）：

| DTO | 信息 |
|---|---|
| UploadFileInfo | 显示名、格式、字节数、文件 SHA256、实际编码/分隔符、工作表 |
| ParsedTable / ParsedDataset | 所有受限原始标量、原行号、原名→规范列名、表头行、空行与公式/格式诊断 |
| ColumnProfile | 采样/最终类型、null/原始值 distinct/重复、例子、精度/scale、范围、IQR 异常、确认提示 |
| SchemaProposal | 受限 Dataset Preview、候选键/关系、文件/解析内容/配置/Proposal hash |
| SchemaConfirmation | 已审阅映射、全量验证后的类型/日期格式/键/关系、配置及 Confirmation hash |
| ParseError / ParseFailure | 有界 code/message 和可选表/列定位；不回显原始文件异常或凭据 |

```python
from datapilot.ingestion.contracts import ParseOptions, ConfirmationOverrides, ColumnOverride
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.confirmation import confirm_file

source = "tests/fixtures/ingestion/customers_utf8_bom.csv"
parsed = parse_file(source, options=ParseOptions(header="present"))
proposal = propose_schema(parsed)
changes = ConfirmationOverrides(
    columns=[
        ColumnOverride(
            table_id="table_1",
            column="column_1",
            normalized_name="customer_id",
            logical_type="TEXT",
        )
    ],
    primary_keys={"table_1": ["column_1"]},
)
confirmation = confirm_file(source, proposal, reviewed=True, overrides=changes)
```

规范列名为有长度上限的 ASCII snake_case，中文原名完整保留，无法转成 ASCII 的名字用 column_N；重复/空表头加唯一位置名并提示。规范名只供映射，P1 不生成 SQL。保留列顺序；table_N 由选中工作表顺序决定，不是数据库表名。

## 类型与质量政策

- 全部原始标量保留为字符串或空值，不用 float 表示金额。XLSX 数值直接保留源 XML 的数值词法，避免 openpyxl 转 float 后丢精度；不承诺恢复文件生成前已经被 Excel 舍入的数值。
- 先对前 sample_size 个非空值提出建议，再对全列验证；后段脏值回退 TEXT、报告 SAMPLE_TYPE_MISMATCH，不隐藏或过滤该行。confidence 是启发式标记，不是校准概率。
- 前导零编号保留 TEXT；明确纯零格式（如 00000）的数字显示为文本并提示格式转换。强行改 INTEGER/NUMERIC 会失败，避免丢零。
- INTEGER 为有符号 64 位范围；其他数字用 Decimal，NUMERIC(p,s) 限 p≤38、s≤18；联合精度也验证，不四舍五入。非有限/超范围/货币符号/百分比/未知区域格式保留 TEXT 并提示。
- ISO 日期验证日历有效性；斜线日期保留 TEXT，用户指定 DD/MM/YYYY 或 MM/DD/YYYY 才转换。ISO timestamp 保留原时区；无时区提示，混合有/无时区回退 TEXT。Excel 1900 虚构闰日 serial 60 保留原串，不悄悄变成 2 月 28 日。
- 空字符串/空单元格为空值，空格、NA、null 等文字不自动抹成缺值。重复统计按原始非空值/原始行计算；主键最终按确认类型转换后的全量值验证。
- IQR 异常只作确定性分布提示，不证明业务异常、不删行。候选主键只是无空且全量唯一的单列候选；候选关系需同名、类型一致、父列唯一、子列全量非空值为父集合子集。均需人工选择，不推断业务真实性。
- Profile 例子最多 5 个，预览最多 20 行；长预览单元格显式裁到 200 字符并给截断标志，原始 ParsedTable 不变。截断数据不用于推断、键/关系验证或数值统计。

## 用户覆盖与确认

CLI 的 `--overrides overrides.json` 接受：

```json
{
  "columns": [
    {"table_id": "table_1", "column": "column_1", "normalized_name": "customer_id", "logical_type": "TEXT"}
  ],
  "primary_keys": {"table_1": ["column_1"]},
  "relation_ids": []
}
```

对歧义日期覆盖为 `logical_type=DATE` 时可指定 `date_format=DD/MM/YYYY`。列/键引用均用源规范名；输出同时带 source_column 与用户确认的新名。关系从 Proposal 的 relation_id 显式选择，类型覆盖之后重新验证。

confirm_file 会重新解析原件、重建 Proposal 并核对文件/完整内容/策略与配置；源、预览、Sheet/表头或阈值变更都会使旧确认失效。所有类型覆盖校验全列，主键检查空值和重复，关系再验类型和子集；空表可预览但不能确认。

Confirmation 是本地审阅配置，hash 不是签名或授权。P2 将来仍须使用可信原件重新验证、进行权限检查后才能入库。当前没有管理凭据或入库工具。

## 配额与 XLSX 安全边界

| ParseLimits 默认值 | 配额 |
|---|---:|
| max_file_bytes | 10 MiB |
| max_sheets / max_columns | 10 / 100 |
| max_total_rows / max_cells | 100,000 数据行 / 500,000 扫描单元格 |
| max_cell_chars / max_parsed_bytes | 8,192 字符 / 32 MiB 解码内容 |
| max_zip_entries | 512 |
| max_entry_bytes / max_uncompressed_bytes | 32 MiB / 64 MiB |
| max_compression_ratio | 200 |
| max_xml_elements / XML 深度 | 2,000,000 / 64 |
| max_seconds | 每个处理操作 30 秒协作式期限 |
| sample_size / preview_rows / max_preview_bytes | 100 / 10 / 2 MiB |

API 可传 ParseLimits；CLI 暴露文件、行、列、Sheet、解压字节配额。配置本身有硬上限，不能改成无限。扫描行含空行，给表头留有限余量；数据行总量仍严格检查。

先扫描 ZIP 中央目录记录数量及一致性，在 ZipInfo 大量分配前拒绝异常；再检查成员/总解压量/压缩比/重复与路径/加密/压缩方式，用禁止 DTD/实体/外部解析的 defusedxml 遍历所有 XML。限制工作表实际坐标、元素/样式/共享串数量，不信任 dimension。之后 openpyxl read_only、data_only=False、keep_links=False 读取；文件不解压到磁盘。P1 不接受 ZIP64/分卷包。

宏/嵌入二进制/ActiveX/外部连接/外部 Relationship 拒绝；公式保留文本、整列按 TEXT 待审，不执行或信任缓存。数组/数据表公式及非标准/损坏单元格明确拒绝。重复/乱序/不一致坐标、伪装格式、非法 XML 返回错误。

这是本地有配额的解析器，不是 OS 级资源沙箱。期限按读块/事件/循环检查，不能强制杀死 C 扩展或 OS 阻塞。未实现超大文件后台队列、完整 Excel 显示/公式语义、复杂合并表头、自动单位换算、任意跨文件关系发现；不支持 XLS/XLSM/XLSB。遇到不支持的内容应改为简单 CSV/XLSX 或明确修正后重试。

## 样例与复现

`tests/fixtures/ingestion/` 有中文 BOM CSV、分号账单 CSV、三工作表 XLSX，全部 synthetic，无真实客户资料；manifest.json 记录 SHA256。`scripts/generate_ingestion_fixtures.py` 固定内容、文档时间与 ZIP 时间，测试验证重新生成字节一致。

新增测试覆盖契约、CSV/XLSX 解析、资源/恶意包、精度/歧义/后段脏值、主键/关系、确认失效、CLI 与 fixture；原 SQL/MCP/PG 测试单独回归，详见交付记录。
