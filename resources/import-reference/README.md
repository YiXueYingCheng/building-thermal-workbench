# 导入校验参考记录

这些记录用于保留已有导入规则的逐字段检查：`SYS_DOOR.json` 包含 `DOOR_ID` 为 1、2、4 的记录，`SYS_MATERIAL.json` 包含 `MATERIAL_ID` 为 62 的记录。

它们与用户于 2026-11-13 授权作为公开示例的 [Drawing26 修补版数据库](../../examples/drawing26-repaired/Drawing26_import_repaired.accdb)中的对应记录逐字段一致。本轮从包内 ACCDB 实际读取后重新核对，未修改参考值或放宽校验。

来源数据库 SHA-256：`e8635e619eb353ec66d148e42781bc0f26227d8b2fa898845f487d9ab2995611`。

这 4 条记录只作为现有转换规则的校验基准，不代表任意新建筑的门、材料或构造默认设置。公开示例的文件信息见 [示例清单](../../examples/sample-manifest.json)。
