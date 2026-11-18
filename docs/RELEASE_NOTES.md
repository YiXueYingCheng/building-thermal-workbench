# v0.73.13 公开预览版 · 2026-11-18

整合 v0.73.12 之后的异地反馈修复与 localfix.1–6 验证结果。保留旧版下载、原方案和结果；不自动采用待复核结果。

- **作息未保存提示更明确**：卡片、窗口底部和页面提示条显著展示；切换受阻时弹窗列出原因与返回处理入口。保存配置后仍提示保存方案版本，撤销需确认。
- **可选 CPU 派发控制**：设备投入显示整机负载、近期平均和任务观测。开关默认关闭，开启后在内存、磁盘与并行上限基础上控制新增任务；运行中的计算保持。目标不是硬性限速，老设备长任务的实际改善仍需试用。
- **导入与配置**：补充基础围护结构准备提醒，修正非木门材料转换和过长核对路径；公用配置参考补齐名称/用途，同类型房间可快捷勾选，没有原比例作息也能创建；W00 同构造外墙可预览并批量推广光学参数。
- **气象与范围**：文件夹批量导入 EPW；下载失败分类提示与重试，部分 TMYx 地点提供需明确确认的 JRC 备用；修复公开包中国 34 地区预设缺失和城市勾选跳顶。备用数据与原 TMYx 不视为同一数据版本。
- **结果与输出**：已完成且完整性通过的待复核项可批量确认采用，保留原警告和用户决定；失败项提供诊断。新增逐天、逐时和不超过 31 天的逐步保存及明细/CSV，月度仍为默认。更细输出会增加空间，旧月度结果不能补出细时间数据。
- **后台恢复与升级可靠性**：启动后验证进程及新心跳，失败显著显示原始诊断；后台先完成中断恢复再继续指定批次，其他暂停保持。升级写入遇短暂 Windows 文件锁有限重试，减少进度重写并保留原始错误；结果写检查复用批次检查，不再每算例重复。
- **升级**：支持官方 v0.72.2、v0.73.11、v0.73.12 的备份与原路径升级；旧结果读取/复核兼容与新计算提交分开，旧计算清单需重新准备。

下载附件 `building-workbench-v0.73.13.zip` 和 `.zip.sha256`。新用户看 [首次使用](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.13/docs/FIRST_TRIAL.md)，旧用户看 [升级与备份恢复](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.13/docs/UPGRADE_TO_0_73_13.md)，不要直接覆盖旧目录。

[详细更新说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.13/docs/REMOTE_FEEDBACK_LOCALFIX.md) · [批量复核与时间尺度](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.13/docs/BULK_REVIEW_AND_OUTPUT.md) · [验收范围](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.13/docs/RELEASE_VALIDATION_0_73_13.json)

Windows、64 位 Python 3.12；实际计算仍需完整 EnergyPlus 26.2.0-4bd7a1f26f，普通 ACCDB/MDB 导入另需 Access ODBC。代码 MIT、自有示例和文档 CC BY 4.0；原作者署名、第三方许可及公开数据范围保持。引擎、天气原文件、私人反馈资料和本地研究数据不随包分发。

[普通 Windows 启动与恢复说明](https://github.com/YiXueYingCheng/building-thermal-workbench/blob/v0.73.13/docs/START_AND_RECOVER.md)
