# Docker历史数据保护：Phase A身份门禁阻断

2026-11-01，北京时间。此记录仅为本地只读审计，不是恢复成功记录。基线 `645be24a18870f3cbce570e18dede610f891cafa`，分支 `p7-engineering-candidate-v1`；原CI归因报告两份本地未提交文件保留。

## 必须停止的实际发现

用户要求：若无法证明旧盘与当前盘是两个不同文件，立即停止。

当前Codex进程视图中，常规Docker数据路径和Codex私有路径的Win32底层身份完全相同。不能把两个不同字符串当成两份已保护的原件，也不能把从同一文件读出的两份Hash当作新旧盘验证。

| 项目 | 常规路径候选 | Codex私有路径候选 |
|---|---|---|
| 请求路径 | `C:\Users\Radiant\AppData\Local\Docker\wsl\disk\docker_data.vhdx` | `C:\Users\Radiant\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Docker\wsl\disk\docker_data.vhdx` |
| GetFinalPathNameByHandleW | `\\?\C:\Users\Radiant\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Docker\wsl\disk\docker_data.vhdx` | 同左 |
| 卷序列号 | `d001f826` | `d001f826` |
| 文件ID | `01bd000000037a4d` | `01bd000000037a4d` |
| 长度 | 38,526,779,392字节，35.880859375 GiB | 同左 |
| 创建时间UTC | 2026-10-20T13:22:27.3424797Z | 同左 |
| 修改时间UTC | 2026-11-01T03:24:17.4380106Z | 同左 |
| 文件头 | `vhdxfile`，只读8字节 | 同左 |
| 硬链接数量 | 1 | 1 |
| Get-Item链接属性 | LinkType/Target为空 | 同左 |
| ACL Owner | 当前Windows用户Radiant | 同左 |
| 全文件SHA256 | **NOT_RUN**，先满足身份门禁 | **NOT_RUN**，两路径当前指向同一对象 |

上述事实证明当前进程看到同一个对象；**不证明正常Windows宿主中绝不存在另一份约1.6 GB文件**。重定向机制与MSIX包数据虚拟化一致，但具体机制仍属于推断，需外部普通宿主验证；不能因此认定发生了NTFS硬链接或数据丢失。[微软MSIX运行模型](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes)

已停止扩大扫描、占用检查、磁盘Hash和后续操作。没有挂载、复制、写VHDX、替换、压缩、修复或删除任何数据盘。

## 其余已经核实与尚未核实事项

- Docker Desktop程序：`D:\downloads\DockerDesktop\Docker Desktop.exe`，文件版本 `4.96.0.243774`。CLI `29.9.1`，当前context `desktop-linux`，端点为 `npipe:////./pipe/dockerDesktopLinuxEngine`。Server为null，管道不存在，不是当前已启动且空容器的实测。
- WSL列表只有 `docker-desktop`，Version 2、Stopped。只见wslservice进程，没有Docker backend或vmmem进程。**没有执行shutdown或启动Docker**。完整旧盘占用情况尚未证明：共享只读句柄成功不等于没有其他进程持有句柄。
- 有界查找仅涉及两个已知Docker WSL目录，另看到 `main\ext4.vhdx`，109,051,904字节；这不是先前声称的约1.6 GB业务数据盘，不据此替代新盘身份。
- Codex包：`OpenAI.Codex_2p2nqsd0c76g0`，安装目录版本 `26.1027.3384.0`。旧盘候选位于包LocalCache，不能作为唯一安全备份。普通升级与reset不是同一操作；应用reset会永久删除应用数据，当前不执行任何应用清理/重置。[微软Reset说明](https://learn.microsoft.com/en-us/windows/msix/desktop/managing-your-msix-reset-and-repair)
- 观察时C盘可用239,459,921,920字节，D盘可用316,114,771,968字节。D盘总可用空间理论上足以容纳已见旧盘及另一份同量级盘；尚未创建或验证备份目标目录权限，也未确认新盘真实大小。
- 148条容器记录、7个Volume、历史DataPilot数据库卷属于用户提供的先前结果。本轮未取得原离线清单位置，也未重新遍历VHDX文件系统，**不得写成已重新验证**。
- 尚未核实正常宿主的Docker配置数据路径、WSL注册BasePath、全部祖先目录联接及真正新盘的独立文件ID。触发身份停止条件后没有继续读取这些项目。
- 没有访问PostgreSQL、执行迁移/Seed或创建CI测试Run。历史容器未启动不能当作数据丢失；本轮也不宣称数据完整。

## 下一次只读核验：必须来自普通Windows宿主

请从Windows开始菜单单独启动PowerShell，**不要使用Codex内置终端或其子进程**，执行：

```powershell
& 'D:\桌面\llm-learning\datapilot-pro\.venv\Scripts\python.exe' -I `
  'D:\桌面\llm-learning\datapilot-pro\artifacts\p7\docker-disk-audit-20261101\readonly_identity.py' `
  --output host-win32-identity.json
```

该脚本只读两条固定候选路径，每份8字节，记录最终路径、卷序列号、文件ID与大小；不启动Docker、挂载或复制VHDX。输出以独占创建方式保存到同目录 `host-win32-identity.json`，文件已存在则拒绝覆盖。脚本只接受两个固定输出文件名，不接受磁盘写入/恢复参数。

如果普通宿主仍无法看到两个不同底层文件，继续BLOCKED；不要尝试通过复制、重命名或重置应用来“制造”两份身份。若宿主证实新旧盘不同，重新核对其绝对路径、大小、占用与配置绑定，然后再提交完整备份审批。

## 条件性备份计划：尚未执行，也尚未获得停止服务确认

候选持久目录：`D:\DockerBackups\DataPilotPro\20261101-recovery-01\`（**仅计划，未创建**）。后续须确认不存在同名备份；如已存在，另用新编号，绝不覆盖。

- 旧盘：由普通宿主核验的私有历史原件 → `old-history-original.vhdx`。
- 当前盘：由普通宿主核验的当前配置实际原件 → `current-before-recovery.vhdx`。目前不能把常规路径视图当成这一原件。
- 必要Docker设置、WSL发行版元数据和可选较小启动盘另行只读登记；敏感配置不进入公开日志。
- 执行前再核验磁盘可用空间和目标ACL，并展示停止Docker、必要时WSL shutdown的精确影响范围，取得用户确认。即使当前已停止，也不能假定执行时仍静止。
- 源文件只读打开并禁止其他写入/删除共享；若已有写占用导致无法获得该句柄，停止，不强制卸载或终止未知进程。目标CreateNew，复制前后核对文件ID、大小、修改时间；流式Hash与独立读取目标及稳定源文件的SHA256一致后才标记VERIFIED。
- 复制失败/变化/Hash不符：停止；原盘保留，失败目标明确标为未验证，不删除或重命名原盘，不启动后续恢复。

[Docker官方备份与恢复](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)要求备份VM数据文件前完全停止Docker；WSL2默认盘路径为LocalAppData下Docker/wsl/disk/docker_data.vhdx。配置了自定义位置时应使用实际位置。本轮未满足路径身份门禁，不能直接照默认字符串执行替换。

## 恢复与回滚：尚未准入

恢复操作、目标绝对路径和精确回滚命令必须在新旧盘身份及两个备份全部验证后另行确定。现阶段无法提供可安全执行的替换命令，任何覆盖均未授权。

后续原则：旧原件与已验证旧备份保持不动，恢复使用独立工作副本；原当前环境也保留可验证备份与配置。若官方方法需要替换当前路径，必须先记录该实际物理目标，正常退出后操作；回滚仅恢复经过验证的当前盘及原配置，不删除历史盘、Volume或WSL发行版。不能启动成功时先停机保全，不反复强制启动或修复数据库。

强制确认口令仍为 **“确认恢复旧 Docker 数据盘”**；只能在备份验证完成、精确方案展示后申请。当前不要求用户给这句确认，也不会把本任务或只读核验当作恢复授权。

当前没有改变任何磁盘或配置，因此本轮无需实际回滚。

## CI与最终状态

隔离PG创建及四个冻结pytest Node ID的3.11/3.13执行全部NOT_RUN。未复用历史数据库、Run、Journal或Ledger；未运行付费模型/历史STOP，未修改产品或Git提交。

| 项目 | 当前状态 |
|---|---|
| Historical Docker Disk | **FOUND**：35.88 GiB候选文件存在；历史逻辑内容未重新验证 |
| Backup | **NOT_RUN**：身份门禁阻断，SHA/目标副本尚未建立 |
| Docker Recovery | **BLOCKED**：无法在当前进程视图证明新旧原件不同；未进入恢复审批 |
| Historical Data Integrity | **NOT_VERIFIED**：VHDX签名不等于容器/PG数据完整性 |
| Isolated PG Acceptance | **NOT_RUN** |
| Git Push | **NOT_AUTHORIZED** |

本地原始Win32结果：`artifacts/p7/docker-disk-audit-20261101/win32-identity.json`，时间 `2026-11-01T05:06:53.632540+00:00`。其最终路径和文件ID是停止依据，不以文件名/容量相似作推断。保存本记录后停止，等待普通Windows宿主只读身份结果；不继续备份、恢复或测试。
