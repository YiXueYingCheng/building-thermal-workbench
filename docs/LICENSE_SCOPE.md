# 版权与许可范围

Copyright (c) 2026 Zhao Bencheng。

作者于 2026-11-13 确认：自有程序代码采用 **MIT**；自有示例数据、结果及文档采用 **Creative Commons Attribution 4.0 International（CC BY 4.0）**。本包据此授权，按下表区分文件范围。

| 内容 | 适用许可 |
| --- | --- |
| 自有 Python、JavaScript、CSS、HTML、PowerShell、CMD 脚本及测试，包括 examples 内的下载、登记脚本 | [MIT](../LICENSE) |
| 程序配置、依赖清单、版本文件、Git 忽略规则 | MIT |
| 根目录及 docs、examples、resources 中的自有说明，作者和引用元数据 | [CC BY 4.0](../LICENSES/CC-BY-4.0.txt) |
| examples/drawing26-repaired 中的 Drawing26 独立修补副本及修改说明；examples/drawing26 中的固定模型模板、作息、记录与控制参数；examples/materials/ECA.json | CC BY 4.0 |
| resources/starter-library 中由本项目原创的演示人数、得热与作息配置 | CC BY 4.0；演示值不代表规范推荐值 |
| resources/import-reference 中来自 Drawing26 的门与材料参考记录 | CC BY 4.0 |
| examples/weather 中由本项目整理的来源目录和说明 | CC BY 4.0，仅覆盖本项目整理内容；其中链接指向的天气原数据继续适用提供方条件 |
| 验收结果目录中的自有报告、结果表、图片与结果压缩包 | CC BY 4.0；压缩包内另附署名和许可，便于单独分享 |
| 自有分发清单、校验值、验收元数据及许可范围说明 | CC BY 4.0 |

不同文件使用不同许可，不表示每个文件均可任选 MIT 或 CC BY 4.0。未另行标注的自有程序资产按 MIT，自有说明和样例数据按 CC BY 4.0。

## 公用参考库范围说明

`resources/reference-library` 已按作者 2026-11-15 的授权收录作息与公用配置库，具体范围见 [随包清单](REFERENCE_DISTRIBUTION_REVIEW.md)。作者的整理、说明及自有修改按 CC BY 4.0；条目保留原来源，软件原有数据及 EnergyPlus 示例不改授本项目许可。源项目数据库、Excel 原文件和独立“用户研究材料_10mm”未新增收录。v0.73.15 收录的公用参考库与 v0.73.11 的已审阅清单一致。各条目的来源与分发范围见上方清单。

## 第三方例外

- `dependencies/dest_compatibility/destep-source.zip` 与其许可文件：完整保留 Copyright (c) 2024 Hongyuan Jia 及原 MIT 许可；其他自有兼容 Python 模块采用本项目 MIT。destep 的开发参考作用及运行时归档使用方式见 [详细说明](DESTEP_REFERENCE.md)。
- `building-workbench-next/static/map`、`third_party`：按 [地图声明](../building-workbench-next/third_party/THIRD_PARTY_MAPS.md)分别保留 Beck 等的 CC BY 4.0、atlas 的 MIT 和 Natural Earth 的公有领域来源。本项目不覆盖原作者的权利。
- `LICENSES` 中的标准许可文本保持原条款；第三方通知不改变原许可。
- 气象 EPW 原文件、EnergyPlus、Access Runtime、Python 依赖环境和系统字体不随包提供，本项目许可证不授权这些外部内容。

## 署名与引用

引用时填写实际使用的版本号。使用 v0.73.16 时，可写作 **Zhao Bencheng (2026), 建筑热环境工作台 / Building Thermal Environment Workbench, v0.73.16**。数据或文档分享时标注 CC BY 4.0、附 [许可链接](https://creativecommons.org/licenses/by/4.0/)，并注明是否修改。对具体示例可补充 Drawing26、ECA 或结果文件名。项目公开网址为 [GitHub 仓库](https://github.com/YiXueYingCheng/building-thermal-workbench)；DOI 尚未注册。

作者信息见[项目作者页](../AUTHORS.md)。

研究引用见 [CITATION.cff](../CITATION.cff)，属于推荐学术引用，不向标准 MIT 额外添加论文引用义务。第三方数据仍需按其自身声明署名。

标准许可中的无担保及责任限制按各许可原文适用。示例用于既定模型与流程复现，模型与安装限制见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)。

## C18 与 PE 研究材料示例

自 v0.73.15 起，作者授权随程序公开 C18 相变层与 PE 光谱层两套示例的具体参数。材料库显示数值及建模假设，其中 PE 示例的太阳透射率为假设值。使用者可复制材料、填写自己的参数并保存版本。
