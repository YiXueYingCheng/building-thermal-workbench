# 导入校验参考记录

这些记录用于保留已有导入规则的逐字段检查：`SYS_DOOR.json` 包含 `DOOR_ID` 为 1、2、4 的记录，`SYS_MATERIAL.json` 包含 `MATERIAL_ID` 为 62 的记录。

它们与用户于 2026-11-13 授权作为公开示例的 [Drawing26 数据库](../../examples/drawing26/Drawing26.accdb)中的对应记录逐字段一致。本轮从包内 ACCDB 实际读取后重新核对，未修改参考值或放宽校验。

来源数据库 SHA-256：`911ccc300f1af61f6a5fee686c2577ae8c1aff145aaf6249e4b5366eaa8d29fa`。

这 4 条记录只作为现有转换规则的校验基准，不代表任意新建筑的门、材料或构造默认设置。公开示例的文件信息见 [source.json](../../examples/drawing26/source.json)。
