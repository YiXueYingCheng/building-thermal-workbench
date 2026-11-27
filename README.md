# 建筑热环境工作台

在 Windows 本机整理建筑、材料、作息和气象，核对输入后调用 EnergyPlus，比较不同工况下的建筑显热需求，并导出结果。

**[下载 v0.73.16 公开预览版（ZIP）](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/download/v0.73.16/building-workbench-v0.73.16.zip)** · [SHA-256 校验文件](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/download/v0.73.16/building-workbench-v0.73.16.zip.sha256) · [本版更新](docs/RELEASE_NOTES.md)

- **第一次使用**　[安装工作台](docs/INSTALL.md)，然后按[首次试用指南](docs/FIRST_TRIAL.md)完成一个两日算例。
- **升级已有工作区**　将新包解压到独立目录，从新包运行 `Upgrade Workbench.cmd`。支持的旧版本和备份步骤见[升级与恢复](docs/UPGRADE_TO_0_73_16.md)。
- **查操作或找源码**　按任务查[使用文档](docs/README.md)，按功能查[仓库目录与模块地图](building-workbench-next/MAP.md)。

![工作台的方案编辑界面与计算流程](docs/images/workbench-editor.jpg)

## 运行环境

需要 Windows 和 64 位 Python 3.12。运行模拟时还需要完整的 EnergyPlus 26.2.0-4bd7a1f26f 安装。普通 ACCDB/MDB 建筑导入需要 64 位 Microsoft Access ODBC 驱动。[依赖说明](docs/DEPENDENCIES.md)

<details>
<summary>首次安装的 PowerShell 命令</summary>

在解压后的包根目录运行。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if (-not (Test-Path .\building-workbench-next\config.json)) { Copy-Item .\building-workbench-next\config.example.json .\building-workbench-next\config.json }
.\.venv\Scripts\python.exe -B -X utf8 .\building-workbench-next\launch.py --check
.\.venv\Scripts\python.exe -B -X utf8 .\building-workbench-next\launch.py
```

</details>

配置好以后，双击 `Start Workbench.cmd` 即可启动。默认地址为 `http://127.0.0.1:8776/`。需要检查后台或恢复暂停的批次时，见[启动与恢复](docs/START_AND_RECOVER.md)。

## 许可与引用

自有代码采用 MIT，已明确范围的自有文档、示例和结果采用 CC BY 4.0。公用参考库按条目保留来源与第三方条件。引用时请注明实际使用的版本。[许可范围](docs/LICENSE_SCOPE.md) · [参考库清单](docs/REFERENCE_DISTRIBUTION_REVIEW.md) · [第三方声明](THIRD_PARTY_NOTICES.md) · [引用信息](CITATION.cff)

[全部历史版本与下载](https://github.com/YiXueYingCheng/building-thermal-workbench/releases) · [版本变更记录](CHANGELOG.md) · [作者](AUTHORS.md)
