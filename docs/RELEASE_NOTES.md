# v0.72.1 · 建筑热环境工作台公开预览

本次完善从 GitHub 开始试用的说明与入口。主页增加真实工作台和 Drawing26 平面截图，明确 Windows、64 位 Python 3.12 及 EnergyPlus 26.2.0-4bd7a1f26f；补充下载完整性校验、首次试用反馈分类，并修正旧的仓库网址表述。

新增 `scripts/verify_manifest.py`，无需第三方依赖即可核对清单中的文件，明确报告文件缺失、内容变化或清单格式问题。核对方法见 `docs/VERIFY_DOWNLOAD.md`，首次使用流程见 `docs/FIRST_TRIAL.md`。

计算逻辑、Drawing26 / ECA 数据、模型模板、既有结果和许可证均未改变。此次没有新增仿真；原版的 43 项自检、7 个接口检查及两日反馈复算记录继续保留，本次检查单独记录在 `docs/VALIDATION.md`。独立电脑试用反馈需另行核实，不以开发机复验替代。

推荐下载附件 `building-workbench-v0.72.1.zip`，可用相邻 `.sha256` 核对完整性。旧版本 v0.72.0 继续保留。反馈可在仓库 Issues 使用“首次试用反馈”模板，自动标注 `first-trial`。

代码 MIT；自有文档、样例和结果 CC BY 4.0；destep、地图等第三方原署名和许可保留。已知限制仍适用：Drawing26 通用导入因门洞边界问题停止，示例走专用模板；结果不等同于全年节能率或设备电耗。详见 `docs/KNOWN_ISSUES.md`。
