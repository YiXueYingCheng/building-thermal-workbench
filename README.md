# 建筑热环境工作台

**v0.73.11 · 公开预览版 · 2026-11-15。** 欢迎未参与开发的使用者从 GitHub 获取并试用。作息和公用配置参考库已按作者确认的范围随包提供；源项目文件和独立研究材料不额外收录。

- **[下载 v0.73.11 公开预览包](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/download/v0.73.11/building-workbench-v0.73.11.zip)** · [SHA256 校验文件](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/download/v0.73.11/building-workbench-v0.73.11.zip.sha256)
- [首次试用与反馈指引](docs/FIRST_TRIAL.md) · [下载完整性校验](docs/VERIFY_DOWNLOAD.md) · [全部历史版本](https://github.com/YiXueYingCheng/building-thermal-workbench/releases)

Windows 本地研究工作台，用于整理建筑、材料、工况和计算范围，核对输入后调用 EnergyPlus，比较并导出建筑显热需求结果。

- [本轮功能与验收范围](docs/RELEASE_NOTES.md)
- [安装与首次使用](docs/INSTALL.md)
- **已有 v0.72.2：先看 [升级与备份恢复](docs/UPGRADE_FROM_0_72_2.md)，再双击新包中的 `Upgrade Workbench.cmd`。**
- [原 Drawing26 / ECA 模板示例](examples/README.md)
- [Drawing26 修补版普通导入示例](examples/drawing26-repaired/README.md)
- [材料计算方式与适用范围](docs/MATERIAL_INPUTS.md)
- [参考库来源、具体条目与公开范围](docs/REFERENCE_DISTRIBUTION_REVIEW.md)
- [已知限制](docs/KNOWN_ISSUES.md) · [许可范围](docs/LICENSE_SCOPE.md) · [第三方声明](THIRD_PARTY_NOTICES.md)

![方案编辑与流程总览（公开基线界面）](docs/images/workbench-editor.jpg)

运行环境为 Windows、64 位 Python 3.12。仅打开空工作区不要求已登记引擎；计算需要完整的 EnergyPlus 26.2.0-4bd7a1f26f 安装。普通 ACCDB/MDB 导入另需 Access ODBC；专用模板登记不依赖该驱动。

在包根目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if (-not (Test-Path .\building-workbench-next\config.json)) { Copy-Item .\building-workbench-next\config.example.json .\building-workbench-next\config.json }
.\.venv\Scripts\python.exe -B -X utf8 .\building-workbench-next\launch.py --check
.\.venv\Scripts\python.exe -B -X utf8 .\building-workbench-next\launch.py
```

之后可双击 `Start Workbench.cmd`。默认地址 http://127.0.0.1:8776/，以本目录配置为准；只在本机监听。首次建立空工作区，示例登记、材料保存、气象下载均不会自动提交计算。

新安装请使用上面的步骤。旧用户不要直接用新包覆盖原目录；升级助手会保留原配置、方案、结果和 Python 环境，先备份再更新。

自有代码采用 MIT；已明确范围的自有示例、结果和文档采用 CC BY 4.0。Copyright (c) 2026 Zhao Bencheng。公用参考库保留原来源及第三方条件，具体范围见随包清单。引擎、Python 环境、天气原文件、本次验收工作区和实际研究数据不随发行包提供。

[GitHub 仓库](https://github.com/YiXueYingCheng/building-thermal-workbench) · [v0.73.11 发布说明与附件](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/tag/v0.73.11) · [旧版 v0.72.2 下载（保留）](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/tag/v0.72.2)。推荐引用请注明实际使用版本；作者信息见 [AUTHORS.md](AUTHORS.md)。
