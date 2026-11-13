# destep 的参考作用与实际使用方式

本说明对应公开包 v0.72.0，核对日期 2026-11-13。

## 来源与署名

- 项目：[hongyuanjia/destep](https://github.com/hongyuanjia/destep)，用于 DeST 到 EnergyPlus 的模型转换。
- 原作者版权声明：**Copyright (c) 2024 Hongyuan Jia**。
- 原许可：MIT，完整文本见 [destep-LICENSE.md](../dependencies/dest_compatibility/destep-LICENSE.md)。
- 随包源码：[destep-source.zip](../dependencies/dest_compatibility/destep-source.zip)。归档注释记录提交 `1d93a51c5dd6a48e0a108d9646f00a496f23d1ec`。
- 源码归档 SHA-256：`df3a4b67fb9f36258d07f45f6b655a061f3632cc144f8075450c5e4c79da6b41`。

源码归档和原许可完整保留，未修改其字节。单独保存的许可与归档内 `LICENSE.md` 相同。本项目自身的版权署名和许可不替换原作者声明。

## 开发阶段的参考作用

[convert_drawing26.py](../dependencies/dest_compatibility/convert_drawing26.py) 的文件头和映射说明记录了对 destep 的参考与核对。当前可明确归属的参考范围如下：

| 参考内容 | 在本平台 Python 转换中的体现 |
| --- | --- |
| 建筑中面几何 | 读取 `MIDDLE_PLANE` 及点、环、平面关系，生成围护结构和门窗的几何对象 |
| 构造层序 | 按围护两侧关系处理层顺序，生成 EnergyPlus 由外到内的构造层 |
| 朝向规则 | 结合源方位角、倾角和建筑方向，核对法向与顶点顺序 |
| 全年作息解码 | 读取源全年计划，形成转换模型需要的时序输入 |
| 窗口类型对应 | 通过 `WINDOW.TYPE` 关联 `WINDOW_TYPE_DATA`，读取对应窗参数；本平台所用简化玻璃参数及近似在转换记录中说明 |

这些描述说明已记录的参考范围，不代表逐项复现 destep 的全部功能。当前程序是独立、受支持范围约束的 Python 实现；其适用条件与近似仍需按本平台的实际校验判断。

## 运行阶段实际做了什么

通用建筑导入按以下流程工作：

1. 本平台通过 Access ODBC 与 [提取脚本](../building-workbench-next/extract_database.ps1)读取数据库副本。
2. [accdb_conversion.py](../building-workbench-next/accdb_conversion.py) 调用本平台的 `convert_drawing26.py`，并显式传入数据库表、参考表和 `--destep-source` 归档路径。
3. `convert_drawing26.py` 执行 Python 映射，生成中间模型及来源记录。它读取 destep 归档的字节、计算 SHA-256，并在输出 `source-manifest.json` 中写入 `destep_source_sha256` 和 `converter_basis`。
4. 门窗边界等检查通过后，继续由 `build_drawing26_models.py` 及平台适配代码组装、核对最终模型；计算由 EnergyPlus 执行。

运行期间没有执行 `destep-source.zip` 中的 R 代码，没有调用 destep 的 R 转换函数，也不要求安装 R 或 destep。归档哈希用于追溯具体参考快照；单凭这一哈希记录，不能认定运行过 destep 或完成了两套转换器的数值等价验证。

## 与公开示例及研究功能的关系

当前 Drawing26 公开示例通过 [setup_drawing26.py](../examples/setup_drawing26.py) 登记已准备并固定校验值的模型模板。示例登记和后续计算不会现场重跑通用数据库转换，也不会运行 destep。

ECA 固定热阻和反馈控制、逐日翻面日历、方案版本、计算队列、结果核验、比较及导出由本平台代码实现。建筑热环境数值求解由 EnergyPlus 执行。

Drawing26 源库的一扇门在通用导入中触发房间侧墙面边界检查；专用模板的计算复现不表示该源几何问题已修正，详见 [已知限制](KNOWN_ISSUES.md)。destep 的参考作用不改变这些适用范围与校验结论。
