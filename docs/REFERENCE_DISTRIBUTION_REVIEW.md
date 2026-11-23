# 公用参考库来源与公开范围

2026-11-15，作者已明确允许作息和公用配置库随平台公开，其他此次讨论的资料不额外纳入。本决定取代此前“先列清单、暂不扩大授权”中针对公用库的待定状态，不改变既有 Drawing26、ECA 示例与第三方署名、许可。

## 本次随包内容

公用库包含 **1,028 项：897 个材料、47 个构造、28 个日计划、48 个全年计划、8 个房间配置**。清单为 [REFERENCE_ITEMS.csv](REFERENCE_ITEMS.csv)，来源摘要为 [REFERENCE_SOURCE_REVIEW.json](REFERENCE_SOURCE_REVIEW.json)，机器可读选择依据为 [DISTRIBUTION.json](../resources/reference-library/DISTRIBUTION.json)。

| 来源 | 涉及的独立条目 | 本次处理 |
| --- | --- | --- |
| DEST-01 · building1.accdb | 886 材料、37 构造、20 日计划、46 全年计划、7 房间配置 | 公用参考条目随包；源文件不提供 |
| DEST-02 · building2_aerogel loaded_H.accdb | 888 材料、42 构造、1 日计划、47 全年计划、7 房间配置 | 公用参考条目随包；源文件不提供 |
| DEST-03 · building2_aerogel loaded.accdb | 888 材料、42 构造、47 全年计划、7 房间配置 | 公用参考条目随包；源文件不提供 |
| DEST-04 · building2_aerogel_H.accdb | 888 材料、42 构造、47 全年计划、7 房间配置 | 公用参考条目随包；源文件不提供 |
| DEST-05 · building2.accdb | 887 材料、39 构造、47 全年计划、7 房间配置 | 公用参考条目随包；源文件不提供 |
| DEST-06 · TEST_current_baseline.accdb | 886 材料、37 构造、46 全年计划、7 房间配置 | 公用参考条目随包；源文件不提供 |
| EP-EXAMPLE · EnergyPlus 26.1.0 ExampleFiles/PurchAirTables.idf | 8 材料、3 构造 | 保留原许可全文；11 条已对照官方来源 |
| USER-EXCEL · 房间与作息输入参数_示例_修复版.xlsx | 10 日计划 | 公用参考条目随包；源文件不提供 |
| USER-LIBRARY · 公共配置库.xlsx | 2 材料 | 公用参考条目随包；源文件不提供 |

多份数据库可以指向同一个条目，来源行不能直接相加作为总数。所有保留条目的 ID、名称、数值、层序和出处不变。28 个日计划、48 个全年计划与 8 个房间配置完整保留。

## 不额外随包的资料

- building1、building2 系列及 TEST_current_baseline 共 6 份建筑源 ACCDB；它们的名称和哈希仅作为提取来源记录，不表示提供原数据库。
- 项目作息 Excel 和历史公共配置 Excel 原文件；只收录已整理的公用参考快照。
- 独立材料“用户研究材料_10mm”（MAT-9a980881db5c）。作者确认这是其自建材料，本次按“其他就算了”从候选中排除；它与既定 ECA 示例是不同对象，且没有被保留构造引用。

Drawing26 修补版与 ECA 固定模型模板均已获准公开分发。既有实际开发版、过渡版以及研究方案和结果未做删除或改写；仅在独立发行副本中筛选分发内容。

## 来源与许可记录

作者确认：DEST 系列建筑由其构建；公用作息与配置库最初由 AI 协助从 ACCDB 提取，后续按需添加和修改。AI 是整理工具，原始出处仍是数据库和用户维护记录。building2 的四份副本由作者确认具有相同建筑模型；本轮未重新核对建筑几何，仍分别保留其来源校验值和条目差异。

作者的整理、说明和自有修改适用既定 CC BY 4.0；软件原有数据的来源和第三方条件继续保留，不将全部 DeST 表中数值改称作者原创，也不把公用库授权延伸到源建筑项目。具体范围见 [版权与许可范围](LICENSE_SCOPE.md)及[第三方说明](../THIRD_PARTY_NOTICES.md)。

USER-LIBRARY 涉及“施压气凝胶”“绝热ECA”两项公用库维护记录，其 ID、物性及原来源保持。历史工作簿哈希 0483824f4f16cac1a4333336dec9ee561018023e402b48b5c0390495999813a7 对应旧版本，本机当前工作簿不是该旧文件；这是版本追溯说明，不能表述为作者或此次公用库授权仍不明确。

## EnergyPlus 示例

EP-EXAMPLE 的 8 个材料与 3 个构造已对照 [EnergyPlus 26.1.0 PurchAirTables.idf](https://github.com/NatLabRockies/EnergyPlus/blob/v26.1.0/testfiles/PurchAirTables.idf) 核对；[原许可全文](../LICENSES/EnergyPlus-26.1.0.txt)保持，具体版权、署名及再分发条件以原文为准，不改标为本项目 CC BY 4.0。旧来源 SHA-256 指向提取的 material-library.json，官方原 IDF 的身份另记，不混用。示例来源版本 26.1.0 与运行所需引擎 26.2.0 分开说明。

## 使用和验证

新工作区自带参考数据，无需提供这些源 ACCDB/Excel。参考条目只读，可复制并保存自己的版本；不自动覆盖已有方案引用。构造引用、日计划别名、全年序列与房间配置关联均在候选中重新核对。原数据版本不因本次分发筛选更换，避免让已有日计划快照产生不必要的新身份。

本清单记录 v0.73.11 的分发审阅。已比对两个发布标签，v0.73.14 的 `resources/reference-library/`、条目清单、来源摘要和分发验收记录均与 v0.73.11 一致。这次核对覆盖上列 1,028 项。后续新增或替换条目时，须另行核对其来源与分发条件。

[参考库分发验收记录](REFERENCE_DISTRIBUTION_VALIDATION.json) · [既有安装、升级与求解验收](LOCAL_INSTALL_ACCEPTANCE.md)
