# v0.73.12 公开预览版 · 2026-11-15

修复 v0.73.11 第三方试用中遇到的导入、输入准备和结果复核阻塞。旧版下载保留，已有研究资料不会自动采用或重算。

- 结果按实际时段、步长和输入核对，移除通用流程对开发期五层建筑全年私有报告的依赖。一月和短期计算可正常复核。
- 完整结果的警告由使用者填写理由、用途范围并明确确认后采用；原始警告和结果保留，采用说明随比较和导出保留。缺失输出、严重错误和校验不一致仍须处理。
- 首次导入后自动进入方案，显示编辑等入口；再次导入保留当前编辑。
- 中文工作区使用独立英文引用缓存；输入准备等待内存时实时读取资源设置。
- 下载脚本被 Windows 拦截时给出明确处理方法，不修改全局执行策略。
- 升级助手增加官方 v0.73.11 → v0.73.12 的备份、原路径更新和恢复，精确登记执行文件兼容关系，让已有结果继续核对。

从附件下载 `building-workbench-v0.73.12.zip` 和同名 `.zip.sha256`。新用户看 [首次使用](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.12/docs/FIRST_TRIAL.md)；v0.73.11 用户看 [升级与恢复](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.12/docs/UPGRADE_FROM_0_73_11.md)，v0.72.2 用户看 [对应说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.12/docs/UPGRADE_FROM_0_72_2.md)。将新包单独解压，从新包运行 `Upgrade Workbench.cmd`，不要直接覆盖旧目录。

Windows、64 位 Python 3.12；实际计算仍使用 EnergyPlus 26.2.0-4bd7a1f26f。普通 ACCDB/MDB 导入另需 Access ODBC。许可证、署名与随包示例授权范围不变。

验证范围见 [本次验收记录](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.12/docs/RELEASE_VALIDATION_0_73_12.json)，结果处理语义见 [用户复核说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.12/docs/RESULT_REVIEW.md)。已做本地隔离数据和接口验证，最终窗口布局与其他设备的使用体验仍需试用反馈。
