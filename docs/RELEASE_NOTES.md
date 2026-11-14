# v0.73.11 公开预览版 · 2026-11-15

**Windows 本地研究工作台公开预览版。** 从下方附件下载 `building-workbench-v0.73.11.zip`；同名 `.zip.sha256` 用于校验。旧版下载继续保留。

新用户请看 [首次试用](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/FIRST_TRIAL.md)；v0.72.2 用户请先看 [升级与备份恢复](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/UPGRADE_FROM_0_72_2.md)，使用新包中的 `Upgrade Workbench.cmd`，不要直接覆盖旧工作区。

运行环境：Windows、64 位 Python 3.12；实际计算使用完整 EnergyPlus 26.2.0-4bd7a1f26f 安装。普通 ACCDB/MDB 导入另需 Access ODBC。程序环境、引擎和天气原文件需要按说明准备。

## 使用上的变化

- 另存方案时一次命名；各保存版本可单独备注，对照和来源选择显示版本信息。
- 工作区方案入口收拢，最近打开真正进入对应方案；对照页面更紧凑，兼容三/四工况组织，旧三工况保持原样。
- 新建、复制和编辑材料使用统一表单，区分计入热阻与蓄热、仅计热阻、仅表面光学。物性、太阳吸收/反射、可见光继承、状态名称与密度推算依据明确显示；保存材料与采用到方案分开。
- 公用作息与房间日计划共用查看、复制、编辑和版本流程；修复参考库跳转和中文输入，气象下载提供全选。公用参考库共 1,028 项随包提供；源项目文件与独立研究材料不新增收录。
- 计算准备、提交和已有结果的状态关联更清楚。可查看现有结果的输出频率及已具备数据的逐日范围，缺少逐时数据时明确提示。
- 保留空间统计、保留汇总后的比较/导出及受控清理/方案删除的既有范围，先显示影响和保留项；本次不扩展删除，也不清理真实研究资料。
- 新增独立的 Drawing26 门洞修补版供普通 ACCDB 导入；原公开模板、原始库和既有结果保持不变。
- 携带多页面同时加载时的连接容量修补，以及空工作区只读查询修补。
- 新增 v0.72.2 升级与备份恢复助手：先检查、备份和校验，再只更新发行文件；恢复前另存升级后现场，保留新增资料。

## 已验证与未验证

全新 Python 环境、空工作区、原路径 v0.72.2 升级、两态短算例、旧数据保留、比较与导出已完成隔离验收；86 项相关回归通过。此前还完成修补版普通导入和自然/温控两个三日算例，均通过。记录日期和范围见 [安装验收](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/LOCAL_INSTALL_ACCEPTANCE.md)、[修补版说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/examples/drawing26-repaired/README.md)。

没有把开发版专用实体 ECA 算法迁入通用材料入口。通用材料的两个状态仍按固定状态分别计算；计入蓄热并不自动意味着运行中调阻可用。原 ECA 示例保留其特定接法和接受范围。

本次新增升级助手 9 项检查及独立旧版升级/恢复演练：27 条原数据库记录保留，升级前后及恢复后的两态结果与比较/导出一致，升级后新增方案、备注和导出均保存在恢复现场副本中。见 [升级与恢复验收](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/UPGRADE_ACCEPTANCE.json)。

本轮没有重跑全年研究、扩大删除功能，或宣称大型结果性能及另一台 Windows 设备安装已验证。

## 升级与许可

请先看 [v0.72.2 升级指引](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/UPGRADE_FROM_0_72_2.md)，保留原安装路径、配置、data、runs、生成 assets 和外置结果。不要整目录覆盖研究工作区。

自有代码 MIT、自有说明与既定示例 CC BY 4.0 的范围保持；Drawing26、destep、地图和其他原许可/署名保留。公用参考库随包清单及排除项见 [参考库公开范围](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/REFERENCE_DISTRIBUTION_REVIEW.md)。此次公用库范围已确定，源项目文件与独立研究材料不新增收录。欢迎按 [首次试用指引](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.11/docs/FIRST_TRIAL.md) 反馈安装、升级及示例复现情况；[旧版下载](https://github.com/YiXueYingCheng/building-thermal-workbench/releases) 继续保留。
