# 在 Origin 编辑和重画地区对照图

## 1　打开对应工程

在工作台读取配对结果，选择总冷热、供暖或制冷，再选择地图分区和样式。点击「导出可编辑 Origin 工程」，生成后可下载单个 OPJU，或下载「工程、数据和教程 ZIP」。解压整个 ZIP 后，在 Windows 版 Origin 中选择 **File → Open** 打开 OPJU。普通「导出图表与 Origin 数据包」也包含完整绘图表和重建脚本，适合把数据带到装有 Origin 的另一台电脑。

在 Project Explorer（项目管理器）找到以下窗口。窗口可能显示中文长名称，可通过窗口属性查看短名称。

| 样式 | 图页短名称 | RegionValues 中要编辑的列 | 对应矩阵 |
| --- | --- | --- | --- |
| 标准图 | RegionalStd | B 为所选指标的单位面积降低量，MJ/m² | DemandMap |
| 等积双图 | RegionalPair | B 为降低率（%），C 为单位面积降低量（kWh/m²） | 左 RateMap，右 AreaMap |

先用 **File → Save Project As** 另存一份。工程打开后就可以编辑，不需要安装 Python。图层、站点、边界、矩阵和数据表均在工程内。

## 2　改一个值，确认图表联动

1. 打开 RegionValues。A 列给出省代码、国家/地区代码或气候代码。按“分区名称”找到一个配对地点数大于零的区域，记下原值。
2. 在该行的 B 列输入一个与原值明显不同、仍在当前色标范围内的数，按 Enter。打开图页，检查相应区域颜色。双图只应改变左侧；要改右图，请编辑 C 列。在矩阵窗口的数据显示模式也能检查具体像元值。
3. 空白或 Origin 缺失值表示该项无有效结果。数值 0 表示测得的差值为零。不要移动或排序 RegionValues 的行，RegionIDs 中的整数按行号查值。地图背景 ID 为 0。工作台中的原计算记录与工程编辑互相独立。
4. 双击色标或热图，进入 Plot Details 的 Colormap/Contours 设置，调整 Levels 的上下限和填色。双图左右使用不同单位，应分别设定。双击标题和色标标签可改文字；在 Object Manager 或 Plot Details 可分别选中边界线及站点散点修改线宽、点径或颜色。
5. 激活目标图页，使用 **File → Export Graphs**，按用途选 PDF 或 PNG，设置尺寸和分辨率。保存 OPJU 以保留改数能力。比较不同方案时，先统一指标、时段、单位和色标范围。

## 3　从数据包重新生成工程

需要已安装并激活的 Windows 桌面版 Origin，及可运行 originpro 的 64 位 Python。可使用工作台已配置的绘图 Python。以下命令在**解压后的数据包目录**打开 PowerShell 执行；若电脑使用 python 命令，把 py -3.12 换成 python。首次设置时先单独启动一次 Origin，完成激活和初次启动提示，再关闭该窗口。

```powershell
py -3.12 -m pip install numpy "originpro==1.1.15" "OriginExt==1.2.6"
py -3.12 -X utf8 .\origin_pair.py . .\我的地区图.opju
```

目标文件请选择新的名称。脚本读取当前目录的绘图表，在独立的后台 Origin 实例建工作簿、矩阵和图层，核对矩阵与分区值后保存。标准图与双图由 origin-map.json 中的 style 决定。生成后按第 1、2 节打开、修改并核验结果。

工作台中可点「检查 Origin 环境」，查看它实际使用的绘图 Python 及已加载的接口版本。若提示找不到 originpro 或 OriginExt，请将 config.json 的 plot_python 指向已具备绘图依赖和这两个接口的解释器，或使用报错中显示的解释器安装。独立运行上面的重建命令时，则使用执行该命令的 Python 安装。若接口已加载、生成工程时连接失败，请确认桌面版能正常打开、许可有效，再重试。[OriginLab 外部 Python 说明](https://docs.originlab.com/externalpython/)

## 4　核对绘图数据与图层

| 文件 | 含义和核对方法 |
| --- | --- |
| map-sites.csv | 每个有效配对地点一行。核对经纬度、group、降低率和单位面积降低量。空 group 表示地点没有匹配到选定分区。中国图按气象站坐标及 2022 年省级边界确定归属。核对边界附近的站点时，请使用同一年份的边界；境外或没有坐标的地点不计入省均值。 |
| map-groups.csv | 分区等权平均。sites 是单位面积降低量的样本数，percent_sites 是降低率的有效样本数。参考需求为零的地点仍参与绝对量统计。正值表示参考需求高于研究需求。1 kWh/m² 等于 3.6 MJ/m²。 |
| origin-values.csv | 按地图 ID 排列的完整分区表，包含无数据区域。重建图页时按所选单位使用其中一列或两列。CSV 的 percent 如 12.5 表示 12.5%。 |
| origin-grid.csv | 无表头整数矩阵，首行对应地图下方。每个正整数对应 origin-values.csv 的 id。中国图采用源边界的全部范围。已经投影的双图矩阵无需再投影或翻转。 |
| origin-borders.csv、origin-stations.csv | 已在当前图的坐标系中。边界以 X、Y 折线叠加，空行断开不同环；站点以 X、Y 散点叠加。站点是位置标记，分区底色来自 RegionValues。 |
| origin-map.json | centres 为首末列、首末行像元中心的 X、Y；extent 为图层外缘。fields 含单位所对应的色标范围及 RGB 色带。 |
| figure_caption.txt、MAP_ATTRIBUTION.md、dataset.json、receipt.json | 依次核对图注与单位、边界来源、方案和配对口径、快照与文件校验值。主图 figure.png 可与 Origin 图并排核对。若另有 climate-overview，则为全球气候多指标附图。 |

若要手工重建一个图层，可在空工作簿导入 origin-values.csv。新建矩阵，按 origin-map.json 的 height、width 设置行列，导入无表头的 origin-grid.csv；用 centres 依次设置 X 从/至、Y 从/至。在另一个同尺寸矩阵中，按 ID 查工作簿的值列（脚本中的 RegionIDs、RegionValues 和 msetvalue 给出了实际公式）。ID 为 0 的背景用独立色阶，缺测用灰色。选值矩阵绘制 Heat Map，把 origin-borders.csv 以 XY 线、origin-stations.csv 以 XY 散点加到同一图层。两个轴范围分别使用 extent 的前两项、后两项，保持 X、Y 等比例。双图为两个并排图层，共用 ID 和边界，分别绑定百分比列和 kWh/m² 列。自动重建脚本逐项执行这套操作，可用于核对手工设置。
