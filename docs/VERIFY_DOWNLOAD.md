# 下载文件完整性校验（可选）

首次试用可按 [试用指南](FIRST_TRIAL.md) 安装。下面的检查用于确认下载和解压的文件完整；它不判断建筑模型是否合理，也不验证计算结论。

## 1. 检查下载的整个压缩包

从 [v0.73.11 下载页](https://github.com/YiXueYingCheng/building-thermal-workbench/releases/tag/v0.73.11) 下载 `building-workbench-v0.73.11.zip` 和同名 `.zip.sha256` 两份附件。将两者放在同一目录，在该目录打开 PowerShell：

```powershell
Get-FileHash -LiteralPath .\building-workbench-v0.73.11.zip -Algorithm SHA256
Get-Content -LiteralPath .\building-workbench-v0.73.11.zip.sha256 -Encoding UTF8
```

第一条命令的 Hash 应与第二条输出开头的 64 位校验值完全相同，字母大小写可以不同。若不一致，重新下载同一版本，暂不使用该压缩包。

这一份 `.zip.sha256` 只对应上面明确命名的版本附件，不适用于 GitHub 自动生成的 `Source code (zip)` 或 `Code → Download ZIP`；这些压缩包结构和字节不同。

## 2. 检查解压后的原始文件

已安装 Python 3.12 后，在新解压的包根目录运行：

```powershell
py -3.12 -B -X utf8 .\scripts\verify_manifest.py
```

脚本仅使用 Python 自带模块，无需先安装工作台依赖。它会按照 `MANIFEST.sha256` 逐文件读取并核对，正确处理中文和空格路径。成功时显示“校验通过”及文件数量；失败时列出缺失、内容不同或清单格式问题，并返回非零退出状态。脚本不会修复、删除或覆盖文件。

请在修改配置、源码或示例之前检查。若已经主动修改 `config.json` 等清单内文件，差异可能是预期结果；请使用另一份新解压的原始包检查下载完整性。不要用空配置覆盖已有研究工作区。

GitHub 源码下载和 Release 附件都可以使用各自随包的 `MANIFEST.sha256`。Release 附件多一份干净的默认 `config.json`，源码下载则由安装步骤创建；不要交叉使用两份清单。运行后新增的环境、计算数据等未列入清单，不属于原始分发文件校验范围。

旧平台升级后的配置会保留，不应要求整个旧工作区与原始发行包相同。升级助手会按实际更新清单自行校验，并保存 `UPGRADE_RECEIPT.json`；请同时按 [升级说明](UPGRADE_FROM_0_72_2.md) 核对旧方案和结果。
