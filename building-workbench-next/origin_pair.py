"""Build an editable regional map in an isolated Origin session."""
import csv
import json
from pathlib import Path
import sys

import numpy as np

METRICS = {'total':'冷热合计','heating':'供暖','cooling':'制冷'}

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def make_book(op, name, columns):
    sheet = op.new_sheet('w',lname=name)
    sheet.get_book().name = name
    for i,(label,values,units,axis) in enumerate(columns):
        sheet.from_list(i,list(values),lname=label,units=units,axis=axis)
    return sheet


def make_matrix(op, name, values, centres):
    mat = op.new_sheet('m',lname=name)
    mat.get_book().name = name
    mat.from_np(values)
    mat.xymap = tuple(centres)
    return mat


def build(op, folder, target):
    view = read(folder/'origin-map.json')
    curved = view['style']=='pair'
    data = read(folder/'dataset.json')
    if view['dataset_sha256']!=data['dataset_sha256']:
        raise ValueError('地图与对照数据标识不一致。')
    groups = rows(folder/'origin-values.csv')
    keys = [g['group'] for g in groups]
    grid = np.loadtxt(folder/'origin-grid.csv',delimiter=',',dtype=int)
    if grid.shape!=(view['height'],view['width']) or grid.min()<0 or grid.max()>len(keys):
        raise ValueError('地图矩阵与分区表不一致。')
    if [int(g['id']) for g in groups]!=list(range(1,len(groups)+1)):
        raise ValueError('请保留分区行序。')
    fields = ([('percent','B','RateMap','降低率','%'),('kWh_m2','C','AreaMap','单位温控面积降低量','kWh/m²')]
              if curved else [('MJ_m2','B','DemandMap','单位温控面积降低量','MJ/m²')])
    columns = [('分区',keys,'','N')]
    values = {}
    for field, _, _, title, units in fields:
        values[field] = [float(g[field]) if g[field] else np.nan for g in groups]
        columns.append((title,values[field],units,'Y'))
    columns.extend([('分区名称',[g['name'] for g in groups],'','N'),
                    ('配对地点数',[int(g['sites']) for g in groups],'','N'),
                    ('降低率有效地点数',[int(g['percent_sites']) for g in groups],'','N')])
    make_book(op,'RegionValues',columns)
    make_matrix(op,'RegionIDs',grid.astype(float),view['centres'])
    bounds = np.genfromtxt(folder/'origin-borders.csv',delimiter=',',skip_header=1,encoding='utf-8-sig')
    coast = make_book(op,'Boundaries',[('X',bounds[:,0],'','X'),('Y',bounds[:,1],'','Y')])
    coords = rows(folder/'origin-stations.csv')
    stations = None
    if coords:
        stations = make_book(op,'Stations',[('X',[float(s['X']) for s in coords],'','X'),
            ('Y',[float(s['Y']) for s in coords],'','Y'),('地点',[s['city'] for s in coords],'','N'),
            ('分区',[s['group'] for s in coords],'','N'),('地点降低率',[float(s['percent']) if s['percent'] else np.nan for s in coords],'%','Y'),
            ('地点降低量',[float(s['kWh_m2']) for s in coords],'kWh/m²','Y')])
    xmin,xmax,ymin,ymax=view['extent']
    ratio=(ymax-ymin)/(xmax-xmin)
    for field, letter, name, title, units in fields:
        mat = make_matrix(op,name,np.zeros(grid.shape),view['centres'])
        mat.activate()
        op.lt_exec(f'msetvalue im:=[{name}]1!1 formula:="ids[i,j]>0 ? vals[ids[i,j]] : -1E20" '
                   f'script:="range vals=[RegionValues]1!{letter};range ids=[RegionIDs]1!1;" recalculate:=auto;')
        expected = np.r_[-1e20, values[field]][grid]
        if not np.allclose(mat.to_np2d(),expected,equal_nan=True):
            raise ValueError('Origin 分区矩阵与导出数值不一致。')
        style = view['fields'][field]
        graph = op.new_graph(template='heatmap')
        graph.name = 'Graph'+letter
        layer = graph[0]
        plot = layer.add_plot(mat,colz=0)
        plot.zlevels = {'minors':3,'levels':list(np.linspace(*style["limits"],6))}
        graph.lt_exec('layer.cmap.linkpal=0;')
        count = int(op.lt_float('layer.cmap.numColors'))
        def color(fraction):
            return 'color(%d,%d,%d)' % tuple(style["palette"][round(fraction*255)])
        for i in range(1,count+1):
            graph.lt_exec(f'layer.cmap.color{i}={color((i-.5)/count)};')
        graph.lt_exec(f'layer.cmap.colorBelow=color(255,255,255);layer.cmap.colorAbove={color(1)};'
                      'layer.cmap.colorMiss=color(217,222,221);layer.cmap.updateScale();')
        cl = layer.add_plot(coast,coly=1,colx=0,type='l')
        cl.color,cl.line_width = '#a6babb',0.35
        if stations is not None:
            marks = layer.add_plot(stations,coly=1,colx=0,type='s')
            marks.color,marks.symbol_size,marks.symbol_kind = '#243c47',2.4,2
        layer.set_xlim(xmin,xmax); layer.set_ylim(ymin,ymax)
        graph.lt_exec('page.width=10000;page.height=5900;layer.left=4;layer.top=18;layer.width=79;'
                      'layer.height=66.95;layer.x.showAxes=0;layer.y.showAxes=0;label -r legend;')
        graph.lt_exec(f'label -t {METRICS[view["metric"]]}显热需求 · {title};'
                      f'title.fsize=17;title.background=0;Spectrum1.title$="{units}";Spectrum1.labels.fsize=11;')
    if curved:
        op.lt_exec('merge_graph option:=specified graphs:="GraphB"+char(10)$+"GraphC" row:=1 col:=2 keep:=1 unit:=inch width:=16 height:=5.2;')
    pair = op.find_graph()
    if len(pair)!=len(fields):
        raise ValueError('Origin 未生成双图图层。')
    pair.name = 'RegionalPair' if curved else 'RegionalStd'
    pair.lname = {'climate':'气候分区','country':'国家／地区','china':'中国省级行政区'}[view['division']]+' · '+METRICS[view['metric']]+'显热需求'
    page_ratio=(1.85 if curved else .95)/ratio
    pair.lt_exec(f'page.width=10000;page.height={round(10000/page_ratio)};')
    aspect = op.lt_float('page.width')/op.lt_float('page.height')
    for index,(_,_,_,title,units) in enumerate(fields):
        pair.lt_exec(f'page.active={index+1};')
        width=38 if curved else 72
        pair.lt_exec(f'layer.unit=1;layer.left={3+50*index};layer.top=17;layer.width={width};'
                     f'layer.height={width*aspect*ratio};layer.showx=0;layer.showy=0;'
                     'layer.x.showLabels=0;layer.y.showLabels=0;'
                     'label -r xb;label -r yl;label -r title;')
        pair.lt_exec(f'label -n MapHeading "{METRICS[view["metric"]]}显热需求 · {title}";'
                     f"MapHeading.attach=2;MapHeading.x={(xmin+xmax)/2};MapHeading.y={ymax+(ymax-ymin)*.08};"
                     'MapHeading.font=font(Microsoft YaHei);MapHeading.fsize=18;MapHeading.background=0;')
    notes = op.new_notes('ReadMe')
    notes.text = (('RegionValues：B 列为左图降低率，C 列为右图单位面积降低量。' if curved else 'RegionValues：B 列为标准图单位面积降低量（MJ/m²）。')+'保持分区行序。'
                  '按 Enter 提交后对应图页自动更新。色标范围在图层中可编辑。灰色区域为缺测。\n'
                  + (folder/'figure_caption.txt').read_text(encoding='utf-8-sig')+'\n'
                  + '对照：'+'  /  '.join(data['records'][side]['name'] for side in ('left','right'))+'\n'
                  + '数据快照 '+view['dataset_sha256']+'\n'
                  + (folder/'MAP_ATTRIBUTION.md').read_text(encoding='utf-8-sig'))
    pair.activate()
    if not op.save(str(target)):
        raise ValueError('Origin 工程保存失败。')


if __name__ == '__main__':
    if len(sys.argv) not in (3,4):
        raise SystemExit('用法：python origin_pair.py 解压后的数据包目录 新工程.opju')
    target=Path(sys.argv[2]).resolve()
    if target.exists() or target.suffix.lower()!='.opju':
        raise SystemExit('请选择尚不存在的 .opju 工程文件。')
    module_dir=Path(sys.argv[3]) if len(sys.argv)==4 else Path(__file__).resolve().parent/'data/origin-python'
    sys.path.insert(0,str(module_dir))
    import originpro as op
    from origin_session import private_session
    with private_session(op):
        build(op,Path(sys.argv[1]),target)
