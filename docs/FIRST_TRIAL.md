# 从 GitHub 下载并完成首次试用

> 当前版本为 v0.73.16 公开预览版。已有 v0.72.2、v0.73.11 至 v0.73.15 或 v0.73.14-rc.1 至 rc.9 用户请看 [升级与备份恢复](UPGRADE_TO_0_73_16.md)，使用新包中的 Upgrade Workbench.cmd；不要直接覆盖旧工作区。

> 普通建筑导入可使用 [Drawing26 门洞修补版](../examples/drawing26-repaired/README.md)。

下文用于 v0.73.16 公开预览版的第三方试用；反馈时请注明使用版本。希望验证的完整流程是：从 GitHub 获取 → 安装 → 登记示例 → 计算 → 查看并导出结果。

## 1. 下载与解压

打开 [v0.73.16 下载页](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/tag/v0.73.16)，在附件中下载 `building-workbench-v0.73.16.zip`，解压到较短、可写的目录，例如 `C:\Workbench\building-workbench-v0.73.16`。请认准附件名中的版本号，不要混用不同版本的包和校验文件。

也可以从 [v0.73.16 标签页](https://github.com/YiXueYingCheng/building-thermal-workbench/tree/v0.73.16) 通过 **Code → Download ZIP** 下载该版本源码；仓库 main 分支以后可能继续更新。自动生成的源码包不包含个人运行配置；按照下一步复制 `config.example.json` 即可。不要直接在 ZIP 内双击运行。

Windows 是本版验证的平台。先安装 64 位 Python 3.12；稍后计算还需安装指定版本 EnergyPlus。软件环境和引擎不在源码包中。

担心下载或解压不完整时，可先按 [完整性校验指引](VERIFY_DOWNLOAD.md) 核对 ZIP 或包内清单。这一步不需要安装工作台依赖，也不是开始试用的必做门槛。

## 2. 安装依赖

在解压后的包根目录（能看到 README.md、requirements-lock.txt 的目录）打开 PowerShell，按顺序执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if (-not (Test-Path .\building-workbench-next\config.json)) { Copy-Item .\building-workbench-next\config.example.json .\building-workbench-next\config.json }
.\.venv\Scripts\python.exe -B -X utf8 .\building-workbench-next\launch.py --check
```

最后的检查区分启动、绘图和数据库导入等功能。首次试用走专用示例模板，不依赖 Access ODBC；不要为了开始示例而先改动现有 Office 安装。

## 3. 登记示例后启动

先从 [EnergyPlus 官方发布页](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0)安装 Windows 26.2.0，当前要求完整版本字符串 `26.2.0-4bd7a1f26f`。保留完整安装目录。

保持 PowerShell 位于包根目录：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\examples\weather\fetch_weather.py --id china34_430000
.\.venv\Scripts\python.exe -B -X utf8 .\examples\setup_drawing26.py --weather .\examples\weather\downloads\CHN_Hunan.Changsha.576870_CSWD.epw --engine "实际安装目录\energyplus.exe"
.\.venv\Scripts\python.exe -B -X utf8 .\examples\setup_controls.py
.\.venv\Scripts\python.exe -B -X utf8 .\building-workbench-next\launch.py
```

第二行的 `实际安装目录` 要换成自己电脑上的 EnergyPlus 安装目录。以上登记步骤不会自动计算。先登记再启动，可以让第一次打开的页面直接载入示例。

浏览器默认打开 `http://127.0.0.1:8776`。后续可双击 `Start Workbench.cmd`。详细配置及故障入口见 [安装说明](INSTALL.md)。

## 4. 跑通一个两日算例

在“工作区说明”的示例中打开“热阻反馈 · 长沙两日”。核对长沙气象、1 月 1—2 日、5 分钟步长和温控模式，查看计算安排，准备输入、核对清单，再提交计算队列。

完成后查看供热、制冷需求和结果状态。本次开发环境及同机独立环境得到供热 **39.876207302993365 kWh**、制冷 **0 kWh**。这是同版本、同输入下的参考值；遇到差异请记录结果与环境，不要直接修改数值或跳过核验。

再运行固定蓬松两日方案（参考供热 **34.48098105597957 kWh**、制冷 **0 kWh**），在已有比较关系中选择这两份方案各自的实际结果批次，尝试导出 CSV、PNG、SVG、PDF 或结果包。确认导出能打开、中文正常，时段和单位清楚。

固定压缩及31日表面光学切换可以后续再试。表面光学切换必须先完成全年逐日参考，不能直接借用其他建筑或气象的日历。完整流程见 [示例说明](../examples/README.md)。

## 5. 反馈使用体验

在仓库 **Issues → New issue** 选择“首次试用反馈”，记录：下载的版本、Windows / Python / EnergyPlus 版本、完成到哪一步、预期行为、实际情况和具体报错。顺利完成也欢迎反馈，并指出说明中让人困惑的地方。

模板会自动添加 `first-trial`（首次试用）标签。维护者会按内容补充 `installation`（安装和启动）、`bug`（程序异常）、`documentation`（说明问题）或 `question`（使用疑问）；反馈者不必自己设置标签。

如果没有看到模板，可以直接新建 Issue，使用上述字段描述。不必上传整个工作区；提供相关错误片段或截图即可，分享前去掉无关的个人路径与私人项目数据。

## 已知范围

这是先公开、再收集独立电脑使用反馈的预览版。本版没有完成第二台机器的安装验收。

## v0.73.12 的历史反馈范围

请优先反馈首次导入后是否能进入编辑、中文目录下能否准备输入、等待内存提示是否清楚，以及一月等非全年结果能否按实际时段核对。遇到警告请试读核查依据；需要采用时自行填写理由和用途范围，检查比较及导出是否保留说明。旧用户请先完成备份升级并核对原方案、结果和保存路径。反馈附版本、卡住步骤、报错文字及必要日志；避免公开个人原始项目和路径。

## v0.73.16 本次重点试用

新用户先按本文安装、登记引擎和气象，再导入修补版 Drawing26 或自己的建筑。旧用户先按 [升级入口](UPGRADE_TO_0_73_16.md) 备份升级，核对原方案、版本、结果和保存位置。

可以选同一建筑做两个工况，保存对照，然后关闭并重开结果。核对双方方案版本、月度负荷和已收录的地点。导入气象时可以选引用已有文件，再到气象库确认文件位置。使用逐日结果时，可以直接导出整栋建筑的供暖与制冷需求。

反馈附版本、操作步骤、预期与实际现象、报错文字或截图。涉及结果请保留原日志；不要在公开 Issue 上传私有建筑、原始研究结果或个人路径。

[普通 Windows 启动、后台诊断与批次恢复](START_AND_RECOVER.md)：AI 协助部署后，日常使用请从普通 Windows 会话启动；页面提示会区分后台未就绪、批次暂停和资源等待。
