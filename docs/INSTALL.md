# 安装与首次使用

已验证 Windows、64 位 CPython 3.12.7。本分发包沿用已完成的同机独立目录验收；第二台机器、全新 Windows 与不同 Office 组合尚未验证。

## 安装与启动

解压到可写且较短的路径，如 `C:\Workbench\building-workbench`。保留包内目录关系。按照根目录 README 建立 `.venv` 并安装 `requirements-lock.txt`。启动使用该环境的解释器，不必激活环境或改变系统脚本策略。

如果从 Git 检出而缺少 `config.json`，先将 `building-workbench-next/config.example.json` 复制为同目录的 `config.json`；双击启动入口会自动完成该步骤。默认端口为 8776，可在配置中修改；启动器不会终止占用端口的其他程序。重复启动保留工作区数据。

## 示例与计算引擎

按 [示例说明](../examples/README.md) 下载长沙气象、登记 Drawing26 模板和 ECA。示例登记不读取 Access；导入自己的数据库时才需要 ODBC。

从 [EnergyPlus 官方发布页](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0)取得 Windows 26.2.0。当前转换器绑定版本字符串 `26.2.0-4bd7a1f26f`；保留安装目录内完整引擎文件，在工作区设置选择 `energyplus.exe`。引擎登记会校验文件，登记本身不启动计算。

示例安装完成后刷新工作区；如服务尚未重读目录，关闭属于本工作区的服务后重新启动。先核对方案的建筑、材料、时段和步长，再生成输入、核对清单、提交计算。完成后选择对应版本的实际结果批次进行比较。

## 导入自己的 ACCDB/MDB

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
