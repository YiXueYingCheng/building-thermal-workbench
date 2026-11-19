# 第三方声明

项目自身的版权与许可不覆盖下列第三方内容。再次分发时应保留其原声明。

| 随包内容 | 署名与许可 | 详细说明 |
| --- | --- | --- |
| destep 转换规则参考与源码归档 | Copyright (c) 2024 Hongyuan Jia，MIT | [参考作用与实际使用方式](docs/DESTEP_REFERENCE.md)；[原许可](dependencies/dest_compatibility/destep-LICENSE.md)；[项目](https://github.com/hongyuanjia/destep) |
| Köppen–Geiger 地图 | Beck et al. (2023)，CC BY 4.0 | [地图来源、论文、数据与修改](building-workbench-next/third_party/THIRD_PARTY_MAPS.md) |
| 陆地轮廓 | @d3-maps/atlas 1.0.0，Copyright © 2026 Georgii Bukharov，MIT；底层 Natural Earth 数据为公有领域 | [atlas 原许可](building-workbench-next/third_party/atlas-LICENSE.txt) |

## destep 在本平台中的作用

destep 为 DeST 数据解释与 EnergyPlus 模型映射提供了参考。本平台转换程序记录了对中面几何、构造层序、朝向和全年作息解码规则的核对，并参考了窗口类型与属性表的对应关系。当前运行的是本平台独立实现、具有适用范围限制的 Python 转换流程；没有执行 destep 的 R 包或调用其转换函数。

随包 `destep-source.zip` 保存所参考的源码快照。通用转换时，本平台读取该归档、计算 SHA-256，并将其写入 `source-manifest.json`，用于追溯参考来源；这项记录不表示执行了 destep 或验证了两套转换器的数值等价。公开示例使用已准备的模型模板，登记和计算时不重新运行上述通用转换。

原作者署名 **Copyright (c) 2024 Hongyuan Jia**、原 MIT 许可和源码归档均完整保留。ECA 控制、光学切换日历、方案管理、队列与结果比较由本平台代码实现，热环境数值求解由 EnergyPlus 执行。具体规则、调用位置和来源版本见 [destep 参考说明](docs/DESTEP_REFERENCE.md)。

## 外部组件与数据

Python 环境、EnergyPlus、Microsoft Access Runtime 和 Windows 字体不随包提供，使用者分别安装。Python 依赖版本见 requirements-lock.txt；许可清单和外部组件入口见 [依赖说明](docs/DEPENDENCIES.md)。

天气文件通过原站下载，来源与校验值见 [气象说明](examples/weather/来源说明.md)。数据使用者应保留相应数据集的引用和条件；本项目不把气象数据改为自身的代码或示例许可。

生成的气候地图在图内注明 Beck 等来源、CC BY 4.0 和显示缩减，并在导出包附带地图说明与 atlas 许可。单独分享、改图时也应保留这些信息。

## 随包作息与公用配置库

`resources/reference-library` 保留原材料、构造、日作息和全年时刻表及来源编号，包含 DeST、EnergyPlus 示例与用户项目来源。作者已授权公用参考快照随平台公开；源项目文件及独立研究材料不新增收录。作者的整理与修改、软件原有参数及已识别的第三方示例分开记录，不统一改称作者原创。详见 [参考快照出处](resources/reference-library/PROVENANCE.md)。本项不改变 Drawing26、destep 或其他原有署名与许可。

## EnergyPlus 示例参考及本轮来源清单

随包公用参考库的 EP-EXAMPLE 部分来自 EnergyPlus 26.1.0 PurchAirTables.idf，含 8 个材料和 3 个构造；已逐项核对并保留 [同版本原许可](LICENSES/EnergyPlus-26.1.0.txt)。旧记录哈希对应提取的 material-library.json，官方原 IDF 的身份另记，二者不混用。这些条目不改用本项目 CC BY 4.0，也不表示任何原作者为本平台背书。

来源、具体条目及排除项见 [随包清单](docs/REFERENCE_DISTRIBUTION_REVIEW.md)。用户于 2026-11-15 明确允许作息与公用配置库随平台公开；其他此次讨论的源建筑与独立材料不纳入。上述内容不改变 destep、地图、Drawing26 和其他原署名、原许可证。
