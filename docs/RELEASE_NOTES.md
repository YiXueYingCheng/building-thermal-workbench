# v0.72.2 · 日历窗口修复与公用参考库

修复 Drawing26 翻面日历核对完成后仍显示“正在核对日历”、缺少保存与采用按钮的问题。原因是页面把 Drawing26 的简化核对结果按另一种建筑的详细格式读取，导致显示中断。现在兼容两种结果；显示异常会结束等待并提示重新核对。

计算队列“批次与进度”的任务范围默认改为“全部记录”，其他筛选仍可选择。

ACCDB 导入新增日间、夜间、连续使用三份透明演示模板；显示参数数值、单位、来源和完整工作日/周末作息。它们不是规范配置，不自动套用。材料库直接提供只读 ECA 示例，可复制、修改并保存自有版本。详见 [公用参考说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.72.2/docs/STARTER_LIBRARY.md)。

本地已验证日历预览、独立保存、明确采用及方案保存；原 TEST 方案保留。48 项 Python 检查和 5 项日历页面回归检查通过。保存与采用不启动计算，本次没有新增仿真。原模型、求解逻辑、Drawing26 / ECA 文件和既有示例结果未变；完整记录见 [验证说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.72.2/docs/VALIDATION.md)。

推荐下载附件 `building-workbench-v0.72.2.zip`，相邻 `.sha256` 用于完整性核对。v0.72.0、v0.72.1 继续保留。已有工作区请先备份并保留原目录，不要用新包的空配置覆盖自己的配置和数据；新版本可解压到独立目录试用。

代码 MIT；自有示例与文档 CC BY 4.0。Drawing26 许可及 destep 等第三方原署名、许可证均保留。已知模型范围和通用导入限制继续适用，详见 [已知限制](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.72.2/docs/KNOWN_ISSUES.md)。
