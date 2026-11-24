# 地图数据来源与许可

本说明仅覆盖 `static/map` 的底图，不覆盖建筑、气象文件、材料数据或计算结果。

## 气候分类底色

`display-grid.json` 使用 Beck 等（2023）的 Köppen–Geiger 气候分类。作者网站列明该地图数据采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，要求保留来源署名；见[作者数据与许可页](https://www.gloh2o.org/koppen/)。

引用：Beck, H. E., McVicar, T. R., Vergopolan, N., Berg, A., Lutsko, N. J., Dufour, A., Zeng, Z., Jiang, X., van Dijk, A. I. J. M. & Miralles, D. G. (2023). High-resolution (1 km) Köppen–Geiger maps for 1901–2099 based on constrained CMIP6 projections. Scientific Data 10, 724. [论文](https://doi.org/10.1038/s41597-023-02549-6)；[数据](https://doi.org/10.6084/m9.figshare.21789074)。

本项目的修改：取 1991–2020 时段的 0.1° 栅格，以 5×5 单元众数缩减为 0.5° 显示网格，并转换为 JSON。仅供底色显示；站点归类使用来源记录中的更细网格，不能用显示图替代精细采样。局部小类别可能在缩减后消失。

## 陆地轮廓

`land.json` 来源为 [@d3-maps/atlas 1.0.0](https://registry.npmjs.org/@d3-maps/atlas/1.0.0) 的 `world/countries/countries-110m`，将全部国家几何合并为陆地轮廓。本地来源对象与该版本公开包对象一致，合并所得字节与现有文件一致。

该包基于 Natural Earth 数据。Natural Earth 将其地图数据置于[公有领域](https://www.naturalearthdata.com/about/terms-of-use/)；atlas 包的 MIT 许可和 Copyright © 2026 Georgii Bukharov 保留于 [atlas-LICENSE.txt](atlas-LICENSE.txt)。包来源：[d3-maps](https://github.com/souljorje/d3-maps)。

## 再次分发与导出

国家／地区图使用 Natural Earth 的 [1:50m Admin 0 – Map Units](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-map-units/)，数据属公有领域。`static/map/regions.json` 按 ISO 地图单元整理名称与别名，简化边界并将经纬度保留至 0.001°。具有单独地区码的地图单元分别着色。

随程序分发地图时一并保留本说明、atlas MIT 许可和 `static/map/manifest.json` 中的来源及修改信息。单独分享气候地图或论文图时，应在图注或随附说明中标明 Beck 等（2023）、CC BY 4.0、数据链接及本项目的显示缩减。项目自身代码许可证不会替换这些地图许可。
