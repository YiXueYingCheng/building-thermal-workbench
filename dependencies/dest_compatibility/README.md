# 数据库转换兼容模块

本目录保留当前 ACCDB/MDB 转换调用链所需的 9 个 Python 模块。

本平台开发转换流程时，参考并核对了 destep 的中面几何、构造层序、朝向、全年作息解码和窗口类型映射规则。实际转换由本目录中的 Python 代码完成，未执行 destep 的 R 包，也未调用其 R 转换函数。

`destep-source.zip` 保存参考源码快照；`convert_drawing26.py` 读取其字节并将 SHA-256 写入转换输出的 `source-manifest.json`，用于来源追溯。该哈希记录不代表两套转换器已经通过数值等价验证。

原作者署名：**Copyright (c) 2024 Hongyuan Jia**。原 MIT 许可保存在 [destep-LICENSE.md](destep-LICENSE.md)，并与源码归档内 `LICENSE.md` 完全一致。源码快照和许可均保持原字节。

具体参考范围、调用链和来源版本见 [destep 参考作用与实际使用方式](../../docs/DESTEP_REFERENCE.md)。当前目录不附带历史转换批次或独立研究脚本；专用公开示例通过既有模板登记，不现场调用通用转换器。
