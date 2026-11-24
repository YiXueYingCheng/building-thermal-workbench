# 仓库目录与模块地图

从用户看到的页面出发，先找到发请求的 JavaScript 文件，再到 [server.py](server.py) 搜索同一条 `/api/` 路径，就能找到对应的 Python 处理函数。只想查操作步骤时，可直接打开[使用文档](../docs/README.md)。

## 顶层目录放什么

| 位置 | 内容 |
| --- | --- |
| [building-workbench-next](.) | 工作台程序和测试。页面脚本、样式、地图在 [static](static/)，第三方地图声明在 [third_party](third_party/)。 |
| [docs](../docs/README.md) | 安装、建模、结果复核、升级、许可和验收说明。 |
| [examples](../examples/README.md) | 可登记的示例建筑、材料和气象来源。 |
| [resources](../resources/) | 随包的参考材料、作息、导入参考表和工作区起始库。 |
| [dependencies](../dependencies/) | DeST 兼容转换所用的随包依赖。[来源与用途](../docs/DESTEP_REFERENCE.md) |
| [scripts](../scripts/) | 打包、校验、升级及相应测试。[打包脚本](../scripts/build_release.py) · [升级助手](../scripts/upgrade_workbench.py) |
| [验收结果](../验收结果/) | 随仓库公开的验收记录。[验收范围](../docs/VALIDATION.md) |

## 按功能找页面、实现和测试

| 要查的问题 | 页面入口 | 处理逻辑 | 相关测试 |
| --- | --- | --- | --- |
| 启动检查与工作区初始化 | [工作区设置](static/workspace-setup.js) | [启动入口](launch.py) · [运行依赖诊断](runtime_check.py) · [工作区设置](workspace_setup.py) | [首次使用与接口](test_workspace_setup.py) |
| 导入 ACCDB，给房间选配置来源 | [建筑导入](static/accdb-import.js) | [导入检查与登记](accdb_import.py) · [数据库转换](accdb_conversion.py) · [起始配置库](starter_library.py) | [导入用的起始配置](test_starter_library.py) |
| EPW 仅引用原文件、查看已导入地点 | [气象导入与管理](static/weather-import.js) | [登记与文件核对](weather_import.py) | [跨工作区引用与副本](test_weather_reference.py) |
| 重开批次或两两比较时重复读取 | [浏览器缓存](static/recent-views.js) | [最近核验结果及失效检查](recent_batch_views.py) | [批次](test_site_recalculation.py) · [对照](test_comparison_steps.py) |
| 预设气象下载失败、切换来源 | [气象下载](static/weather-downloads.js) | [下载批次](weather_downloads.py) · [取回与校验文件](weather_fetch.py) | [下载](test_weather_downloads.py) · [备用来源](test_weather_fallbacks.py) |
| 登记材料，选择铺设墙与热阻反馈范围 | [材料登记](static/material-registration.js) · [逐墙选择](static/drawing-wall-scope.js) | [材料登记](material_registration.py) · [墙段范围](drawing_wall_scope.py) · [表面控制](surface_controls.py) | [材料登记](test_material_registration.py) · [表面控制与选墙](test_surface_controls.py) |
| 准备输入，减少重复作息带来的内存占用 | [输入准备](static/input-workflow.js) | [输入准备流程](input_pipeline.py) · [计算清单](execution_inputs.py) · [合并等价只读作息](schedule_sharing.py) | [作息共享及独立控制例外](test_schedule_sharing.py) |
| 队列不派发，查看内存、CPU 或独占启动 | [队列与设备投入](static/execution.js) | [派发队列](execution_queue.py) · [后台执行](execution_worker.py) · [资源预算](resources.py) · [CPU 预算](cpu_budget.py) | [CPU 预算](test_cpu_budget.py) · [独占派发](test_single_dispatch.py) · [后台状态](test_worker_runtime.py) |
| 预热趋势里某个房间隔天重复 | [算例预热记录](static/batch-results.js) | [引擎内逐日观测](wb_warmup.py) · [趋势判读](warmup_trends.py) · [失败诊断展示](execution_failure_view.py) | [预热趋势](test_warmup_trends.py) |
| 失败地点按短步长补算，手动并入原批 | [本批结果与确认并入](static/batch-results.js) | [补算与确认采用](site_recalculation.py) · [原批汇总](batch_results.py) | [单地点补算](test_site_recalculation.py) |
| 对照两侧步长不同，或需要核对扩铺效果 | [地点对照明细](static/comparison-details.js) | [步长配对与豁免](comparison_steps.py) · [对照汇总](comparison_results.py) · [铺设范围对照](coverage_results.py) | [步长口径](test_comparison_steps.py) · [铺设范围](test_coverage_results.py) |
| 查看原始输出频率、导出作息或控制状态 | [时序明细](static/result-timeline.js) · [批次导出选项](static/batch-results.js) | [时序读取](result_timeline.py) · [批次时序导出](batch_timeseries.py) | [时序与导出](test_result_timeline.py) |

**以单地点补算为例。** 在“本批结果”提交补算后，可在 [batch-results.js](static/batch-results.js) 找到 `/api/site-recalculation/submit`。[server.py](server.py) 把请求交给 [site_recalculation.py](site_recalculation.py) 的 `submit`。用户点“确认并入”时才调用同一模块的 `adopt`。如果问题出在已并入地点的对照口径，接着查 [comparison_steps.py](comparison_steps.py)。
