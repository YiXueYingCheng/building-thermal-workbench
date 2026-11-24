# 建筑热环境工作台

请从包根目录的 [README](../README.md) 和 [安装说明](../docs/INSTALL.md) 开始。计算数据由本地工作区创建，源码包不附带私人运行记录。

在「对照总览 → 读取配对结果」选好需求指标和地图分区，将图片样式设为「等积双图」，即可导出可编辑 Origin 工程。打开下载的 .opju，在 RegionValues 按分区修改 B 列（降低率，%）或 C 列（单位温控面积降低量，kWh/m²），按 Enter 后查看 RegionalPair。每一行对应一个固定的地图分区，请保留行序。图层色标可在 Origin 中双击编辑。改值只影响下载的工程。

此导出在 Windows 上调用本机已激活的 Origin。本研究端验证使用 OriginPro 2025b，以及绘图 Python 中的 originpro 1.1.15 和 OriginExt 1.2.6。普通图片及数据包可独立导出。
