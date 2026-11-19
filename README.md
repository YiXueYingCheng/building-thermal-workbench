# 建筑热环境工作台

**v0.73.14 · 公开预览版**

新计算清单会合并等价的只读文件作息。逐地点补算、材料铺设范围对照、热阻与光学状态导出见[本版更新](docs/RELEASE_NOTES.md)。

从材料库把双状态实体材料选入建筑外墙后，在“材料 → 应用与构造”逐墙选择铺设范围，在“工况 → 材料控制”从已铺墙中选择热阻反馈组。支持已通过导入核对的普通建筑和 Drawing26 示例。平面可切换楼层，也可直接用墙号清单。北京五层已校准的专用方案沿用原控制范围；同一建筑可另用通用材料方案试验选墙。

表面光学切换指按工况规则选择 A 或 B 组外表面光学参数，用于当前暴露在室外的表面。材料库登记可选参数，材料应用指定目标构件和层位；工况分别设定表面光学切换和热阻调节。

在工况对照的地点明细中，若已确认并入的短步长补算与对侧步长不同，可点击“仅此地点按不同步长纳入”，确认豁免。导出包中的 pairing-summary.csv 并列严格与含豁免两套汇总，地点表保留两侧实际步长。

工况对照中，打开步长不一致的地点明细，可以为已通过的一侧单独加算。通过后点击“仅在本对照选用”，这组对照会把该地点和其他已配对地点一起汇总、导出。原批的通过结果仍可查看。

打开“本批结果”，在失败地点的“查看明细”里选择补算步长并提交。通过核验后回到原地点，点击“确认并入原批汇总”。原失败尝试可随时下载。地点明细与导出保留原步长和采用步长，工况比较只汇总两侧实际步长一致的地点。

新算例自动记录逐预热日的房间极值。在计算队列展开算例可查看预热趋势，失败后在结果明细核对具体房间、温差及收敛限值。

本版支持按建筑实际所选外墙、屋面，同时运行光学切换日历与实体材料热阻调节。已有 JECA 方案可直接打开，在“工况 → 材料控制”启用可调热阻，到“光学切换与参考”采用本方案日历，然后保存方案、重新生成输入并提交。可调实体层按 1 分钟求解，每 5 分钟判断一次。日历仍使用原构造参考算例的步长。材料 JSON 可从公用材料库导出、在另一台设备导入。详见[材料说明](docs/MATERIAL_INPUTS.md)。

方案总览、工况窗口和生成输入前均显示表面光学切换与热阻调节的状态，以及同时受两项控制的构件数。已采用的日历随方案版本保存。从指定版本另存后，可以直接查看该版本各地点的光学参数组、切换日期和原警告。完整核对由用户启动，切换方案后可在同一页面返回查看原任务。其他工况的结果登记可以同时进行。生成输入时仍按地点核对来源。

- **[下载 v0.73.14 公开预览包](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/download/v0.73.14/building-workbench-v0.73.14.zip)** · [SHA256 校验文件](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/download/v0.73.14/building-workbench-v0.73.14.zip.sha256)
- [首次试用与反馈指引](docs/FIRST_TRIAL.md) · [下载完整性校验](docs/VERIFY_DOWNLOAD.md) · [全部历史版本](https://github.com/YiXueYingCheng/building-thermal-workbench/releases)

Windows 本地研究工作台，用于整理建筑、材料、工况和计算范围，核对输入后调用 EnergyPlus，比较并导出建筑显热需求结果。

- [本轮功能与验收范围](docs/RELEASE_NOTES.md)
- [安装与首次使用](docs/INSTALL.md)
- **已有 v0.72.2、v0.73.11 至 v0.73.13 或 v0.73.14-rc.1 至 rc.9：先看 [升级与备份恢复](docs/UPGRADE_TO_0_73_14.md)，从新包运行 `Upgrade Workbench.cmd`，不要直接覆盖旧目录。**
- [结果警告的核对与用户采用](docs/RESULT_REVIEW.md) · [批量采用与输出时间尺度](docs/BULK_REVIEW_AND_OUTPUT.md)
- [房间作息、气象、墙面与 CPU 控制的更新说明](docs/REMOTE_FEEDBACK_LOCALFIX.md)
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

[GitHub 仓库](https://github.com/YiXueYingCheng/building-thermal-workbench) · [v0.73.14 发布说明与附件](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/tag/v0.73.14) · [旧版 v0.72.2 下载（保留）](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/tag/v0.72.2)。推荐引用请注明实际使用版本；作者信息见 [AUTHORS.md](AUTHORS.md)。

[普通 Windows 启动、后台诊断与批次恢复](docs/START_AND_RECOVER.md)：AI 协助部署后，日常使用请从普通 Windows 会话启动；页面提示会区分后台未就绪、批次暂停和资源等待。
