# 工作台使用文档

## 安装或升级

- **第一次运行**　[安装与依赖配置](INSTALL.md) · [首次试用，从示例到两日算例](FIRST_TRIAL.md) · [核对下载文件](VERIFY_DOWNLOAD.md)
- **已有方案和计算结果**　[升级到 v0.73.16、备份和恢复](UPGRADE_TO_0_73_16.md)
- **启动或调度遇到问题**　[普通 Windows 启动、后台诊断与批次恢复](START_AND_RECOVER.md) · [运行依赖](DEPENDENCIES.md)

## 建模与计算

| 要做什么 | 从这里开始 |
| --- | --- |
| 导入建筑，或试跑 Drawing26 | [示例与两种导入路径](../examples/README.md) · [修补版建筑的普通导入](../examples/drawing26-repaired/README.md) · [门构造与材料记录](DOOR_IMPORT_LOCALFIX.md) |
| 配置房间作息、导入气象、选择计算范围 | [房间配置和气象操作](REMOTE_FEEDBACK_LOCALFIX.md) · [作息、方案和计算流程](WORKFLOW_MANAGEMENT.md) · [气象文件来源](../examples/weather/来源说明.md) |
| 登记材料，给外墙铺设材料或启用热阻与光学切换 | [材料参数、铺设范围和控制设置](MATERIAL_INPUTS.md) · [参考材料与构造](REFERENCE_LIBRARY_AND_MATERIALS.md) · [工作区起始库](STARTER_LIBRARY.md) |
| 队列暂停，或需要更换结果盘 | [恢复批次调度](START_AND_RECOVER.md) · [结果位置与存储管理](STORAGE_MANAGEMENT.md) |

## 查看、比较与导出结果

| 遇到的情况 | 操作说明 |
| --- | --- |
| 计算完成，但结果有警告 | [逐项复核与采用](RESULT_REVIEW.md) · [批量采用待复核结果](BULK_REVIEW_AND_OUTPUT.md) |
| 某个地点预热失败，或者对照两侧的求解步长不同 | [单地点补算、确认并入和跨步长对照](RESULT_REVIEW.md#预热失败时只补算一个地点) |
| 想获取逐日、逐时或逐步数据 | [设置结果保存频率](BULK_REVIEW_AND_OUTPUT.md#设置输出频率) · [查看算例时序明细](RESULT_TIMELINE.md) |
| 导出热阻、光学状态或两种配对口径 | [选择数据包的指标与时间尺度](BULK_REVIEW_AND_OUTPUT.md#导出批次数据包) · [严格配对与含豁免汇总](RESULT_REVIEW.md#两侧求解步长不同怎样做工况对照) |

## 查范围、来源与版本

- [功能范围与结果解释](SCOPE.md) · [已知限制](KNOWN_ISSUES.md) · [本版更新](RELEASE_NOTES.md) · [验收记录](VALIDATION.md)
- [参考库分发范围与条目清单](REFERENCE_DISTRIBUTION_REVIEW.md) · [许可与署名](LICENSE_SCOPE.md) · [第三方声明](../THIRD_PARTY_NOTICES.md)
- [旧版本下载](https://github.com/YiXueYingCheng/building-thermal-workbench/releases) · [历史变更](../CHANGELOG.md)

维护工作台请从[仓库目录与模块地图](../building-workbench-next/MAP.md)进入。使用脚本登记材料可查[材料接口](MATERIAL_AGENT_API.md)。
