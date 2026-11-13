# 第三方许可与外部依赖

核对日期：2026-11-13。第三方各自的许可继续有效。作者已确认自有代码 MIT，自有文档、Drawing26 与 ECA 示例及结果 CC BY 4.0，版权署名为 Zhao Bencheng，详见 [许可范围](LICENSE_SCOPE.md)。气象采用原站下载并保留提供方条件。GitHub 的[仓库许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)解释了公开仓库与授权他人使用代码的区别。

## 随包文件

| 内容 | 来源及许可 | 当前处理 |
| --- | --- | --- |
| destep 转换规则参考与源码归档 | [hongyuanjia/destep](https://github.com/hongyuanjia/destep)，MIT，Copyright (c) 2024 Hongyuan Jia | 开发时参考并核对部分转换规则；运行时由本平台 Python 实现转换，归档仅读取并记录哈希，不执行 R。见[详细说明](DESTEP_REFERENCE.md) |
| 气候分类显示栅格 | [Beck 等的作者许可页](https://www.gloh2o.org/koppen/)，CC BY 4.0 | 已注明论文、数据链接和显示缩减操作 |
| 陆地轮廓 | [@d3-maps/atlas 1.0.0](https://registry.npmjs.org/@d3-maps/atlas/1.0.0)，MIT；其 Natural Earth 底层数据为[公有领域](https://www.naturalearthdata.com/about/terms-of-use/) | 已保留该版本 MIT 原文及变换说明 |
| 导入参考表 | 3 条 SYS_DOOR 与 1 条 SYS_MATERIAL 记录，现已从获准公开的 Drawing26 实际读库核对一致 | 保留 Drawing26 来源依据；数据与逐字段规则不变 |
| Drawing26 与 ECA 示例 | 用户于 2026-11-13 明确允许作为公开示例 | 文件及说明位于 `examples`；该授权不替第三方另行许可 |
| 历史运行缓存、私人样例、历史结果 | 来源或公开范围未确定 | 不纳入公开包 |

destep ZIP 校验值为 `df3a4b67fb9f36258d07f45f6b655a061f3632cc144f8075450c5e4c79da6b41`，归档注释记录提交 `1d93a51c5dd6a48e0a108d9646f00a496f23d1ec`。归档内 `LICENSE.md` 与现有随包许可逐字节一致。

上述“归档读取并记录哈希”描述运行时行为；开发阶段的参考作用包括中面几何、构造层序、朝向、全年作息解码和窗口类型对应。它不表示本平台集成了 destep 的全部能力，也不表示已经通过与 destep 的数值等价验证。当前公开示例使用既有模板，复现时无需安装 R 或 destep。

地图署名、许可链接、精确来源及修改方式见[地图数据来源与许可](../building-workbench-next/third_party/THIRD_PARTY_MAPS.md)。地图的许可不授权公开其上叠加的站点研究结果。

## Python 安装依赖

以下版本来自已验证的 Windows、CPython 3.12.7 环境，13 项全部与 `requirements-lock.txt` 一致。许可名称来自安装包元数据及随包许可文件；Python 环境不装入项目分发包，由使用者安装依赖。

| 包 | 锁定版本 | 安装包声明的主许可 |
| --- | --- | --- |
| contourpy | 1.3.3 | BSD-3-Clause |
| cycler | 0.12.1 | BSD |
| et_xmlfile | 2.0.0 | MIT |
| fonttools | 4.68.0 | MIT |
| kiwisolver | 1.5.1 | Modified BSD |
| matplotlib | 3.8.1 | PSF 类许可；附带组件另有许可 |
| numpy | 1.26.1 | BSD；二进制附带组件另有许可 |
| openpyxl | 3.1.2 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pillow | 13.0.0 | MIT-CMU |
| pyparsing | 3.3.3 | MIT |
| python-dateutil | 4.0.0 | BSD-3-Clause |
| tzdata | 2026.6 | Apache-2.0；时区数据另有说明 |

主许可不能替代安装包内其他组件的声明。若以后改为离线安装包或捆绑运行环境，应按实际带入的文件保留对应许可和第三方通知，重新核对二进制依赖。

## 使用者另行安装或提供

| 组件 | 获取方式 | 范围 |
| --- | --- | --- |
| EnergyPlus | [官方 26.2.0 发布页](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0) | 当前转换器检查 `26.2.0-4bd7a1f26f`；程序包不附带引擎 |
| Access 数据库驱动 | [Microsoft 365 Access Runtime 官方说明](https://support.microsoft.com/en-gb/access/download-and-install-microsoft-365-access-runtime) | 用于 ACCDB/MDB 读取；本平台读取进程要求可用的 64 位驱动 |
| 中文字体 | 使用者系统已有字体，或填写 `plot_font` | 不随项目复制 Windows 字体；换字体后检查图表中文字形 |
| 气象文件 | 已登记 107 份历史文件的来源，由原站下载 | 保留各文件的数据集及出处；不自动沿用项目代码许可 |

微软说明 Access Runtime 提供 Access Database Engine，并列明现有 Office 安装方式与位数的兼容条件。安装应依据该页核对；不强行更换用户现有 Office。旧 Access Database Engine 2016 的[官方生命周期](https://learn.microsoft.com/lifecycle/products/access-database-engine-2016-redistributable)显示支持于 2025-10-14 结束，因此新的安装说明采用 Microsoft 365 Access Runtime 入口。本机读取测试使用的是既有驱动，不能据此宣称已验证所有 Runtime 与 Office 安装组合。
