# 安装与首次使用

> 当前版本为 v0.73.14 公开预览版。已有 v0.72.2、v0.73.11 至 v0.73.13 或 v0.73.14-rc.1 至 rc.9 用户请看 [升级与备份恢复](UPGRADE_TO_0_73_14.md)，使用新包中的 Upgrade Workbench.cmd；不要直接覆盖旧工作区。

> v0.73.11 已加入：原公开模板与原始库继续保留；另有独立的 [Drawing26 门洞修补版普通导入示例](../examples/drawing26-repaired/README.md)，已验证普通导入及短期计算。请按文件版本区分，旧结果不自动替换。

已验证 Windows、64 位 CPython 3.12.7。本分发包沿用已完成的同机独立目录验收；第二台机器、全新 Windows 与不同 Office 组合尚未验证。

## 安装与启动

解压到可写且较短的路径，如 `C:\Workbench\building-workbench`。保留包内目录关系。按照根目录 README 建立 `.venv` 并安装 `requirements-lock.txt`。启动使用该环境的解释器，不必激活环境或改变系统脚本策略。

如果从 Git 检出而缺少 `config.json`，先将 `building-workbench-next/config.example.json` 复制为同目录的 `config.json`；双击启动入口会自动完成该步骤。默认端口为 8776，可在配置中修改；启动器不会终止占用端口的其他程序。重复启动保留工作区数据。

## 示例与计算引擎

按 [示例说明](../examples/README.md) 下载长沙气象、登记 Drawing26 模板和 ECA。示例登记不读取 Access；导入自己的数据库时才需要 ODBC。

从 [EnergyPlus 官方发布页](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0)取得 Windows 26.2.0。当前转换器绑定版本字符串 `26.2.0-4bd7a1f26f`；保留安装目录内完整引擎文件，在工作区设置选择 `energyplus.exe`。引擎登记会校验文件，登记本身不启动计算。

示例安装完成后刷新工作区；如服务尚未重读目录，关闭属于本工作区的服务后重新启动。先核对方案的建筑、材料、时段和步长，再生成输入、核对清单、提交计算。完成后选择对应版本的实际结果批次进行比较。

## 导入建筑模型：先确认文件来源

工作区设置和编辑方案中的入口统一为“导入建筑模型”。当前读取的是 **DeST 项目数据库（`.accdb` / `.mdb`）**。DeST 是建筑能耗模拟软件；项目数据库保存房间、围护构造、作息等模型信息。ACCDB 和 MDB 是数据库格式名称，不代表所有同后缀文件都能导入。

查找文件时：

1. 到 DeST 工程的保存文件夹查找，数据库名称通常与图纸或工程相近；具体位置和命名随版本、保存方式而异。
2. 看不到后缀时，在 Windows 资源管理器的“查看”中显示“文件扩展名”，或查看文件属性。
3. 选择模型数据库，而不是只有计算结果的数据库。两者可能使用相同后缀；先“检查所选文件”，核对识别出的房间数、楼层和面积。
4. 如果模型由他人创建，向提供者索取项目模型数据库。无需先用 Access 打开或另存。

其他格式后续按来源接入各自的读取和核查流程；当前通用入口名称不意味着已支持 IDF、epJSON、IFC、gbXML 或 CAD 图纸。各格式接入后仍需明确模型、构造与作息的保留、缺失及映射情况。

需要 64 位 PowerShell 可读取的 Microsoft Access ODBC 驱动，参考 [Microsoft 365 Access Runtime 官方安装说明](https://support.microsoft.com/en-gb/access/download-and-install-microsoft-365-access-runtime)。先核对已有 Office 的位数和安装方式。应用读取源文件副本；会检查房间、作息、得热、温控、遮阳和地面条件，检查通过后才加入列表。

PowerShell 提取脚本使用进程级 RemoteSigned；组织策略仍然有效。下载标记或签名要求导致读取失败时，应按本机管理要求处理可信文件，不建议修改全局策略。

## 数据、字体与故障检查

运行记录、输入快照和结果位于 `building-workbench-next/data`；作息缓存位于 `assets`。备份应覆盖整个工作区及其引用的外部文件。源码升级请先备份，再按变更说明处理，不能用空工作区覆盖已有研究。

图表缺字时在配置中填写有权使用的 `plot_font`；本包不复制 Windows 字体。依赖检查可用 `launch.py --check --json`，服务日志位于 `data/server.stderr.log`。端口冲突时修改配置，不关闭其他工作区。

## 自检

在包根目录运行：

```powershell
cd building-workbench-next
..\.venv\Scripts\python.exe -B -X utf8 -m unittest test_workspace_setup test_runtime_settings test_example_setup test_public_controls test_weather_quality
```

这些检查使用临时工作区和合成气象，不启动 EnergyPlus；实际计算验收与适用范围见包内 `验收结果` 和 [范围说明](SCOPE.md)。

## v0.73.12 已解决的问题

- 导入提示 `extract_database.ps1` 未签名：Windows 拦截了下载的脚本，不表示建筑文件坏了。确认本包来源可信后，在包根目录 PowerShell 执行 `Unblock-File -LiteralPath ".\building-workbench-next\extract_database.ps1"`，再重试导入。此操作仅移除这个文件的下载标记，不修改全局执行策略；单位管理策略仍限制时请联系管理员。
- 第一次确认导入建筑后会进入来源方案并出现编辑、比较和计算入口。再次导入保留当前正在编辑的方案。
- 工作区可以含中文；需要英文引用路径的气象/作息文件会复制到当前用户的独立缓存。若账户及临时目录均含中文且没有可用英文位置，可在 config.json 中设置 `"reference_cache_root": "D:/BTWB-references"`，选择可写的独立英文完整路径；不必搬动整个工作区。
- 输入准备显示等待内存时，资源设置现在会实时读取。请根据可用内存调整预留或关闭占用较高的应用；没有取消资源保护。
- 结果复核按实际时段核查，详见 [警告与用户采用](RESULT_REVIEW.md)。

[普通 Windows 启动、后台诊断与批次恢复](START_AND_RECOVER.md)：AI 协助部署后，日常使用请从普通 Windows 会话启动；页面提示会区分后台未就绪、批次暂停和资源等待。
