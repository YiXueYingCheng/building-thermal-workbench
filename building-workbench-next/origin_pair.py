"""Build an editable two-layer Mollweide figure in an isolated Origin session."""
import csv
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
from plot_regional import climate_raster, scale, transform, METRICS

WIDTH, HEIGHT = 1080, 540
Y = np.sqrt(2)
X = 2 * Y
EXTENT = (-X+X/WIDTH, X-X/WIDTH, -Y+Y/HEIGHT, Y-Y/HEIGHT)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def geography(folder, division, data):
    if division == 'climate':
        assets = read(folder/'map.json')
        classes = sorted(data['classes'], key=lambda c:c['id'])
        keys = [c['climate'] for c in classes]
        labels = [c['name'] for c in classes]
        lut = np.zeros(256, dtype=int)
        for i, c in enumerate(classes, 1):
            lut[c['id']] = i
        grid = lut[climate_raster(assets, True)]
        borders = [transform(r, True) for poly in assets['land']['coordinates'] for r in poly]
    else:
        regions = read(folder/'map-regions.json')
        keys = sorted(regions)
        labels = [regions[k]['names'][-1] for k in keys]
        grid = np.zeros((HEIGHT, WIDTH), dtype=int)
        borders = []
        for i, code in enumerate(keys, 1):
            layer = Image.new('1',(WIDTH, HEIGHT))
            draw = ImageDraw.Draw(layer)
            for polygon in regions[code]['polygons']:
                for n, ring in enumerate(polygon):
                    pts = transform(ring, True)
                    borders.append(pts)
                    pixels = np.column_stack(((pts[:,0]/X+1)*WIDTH/2,
                                              (1-pts[:,1]/Y)*HEIGHT/2))
                    draw.polygon([tuple(p) for p in pixels], fill=int(n==0))
            grid[np.asarray(layer)] = i
    angle = np.linspace(0,2*np.pi,721)
    borders.append(np.column_stack((X*np.cos(angle),Y*np.sin(angle))))
    paths = np.concatenate([np.vstack((b, [np.nan,np.nan])) for b in borders])
    return keys, labels, np.flipud(grid).copy(), paths


def make_book(op, name, columns):
    sheet = op.new_sheet('w',lname=name)
    sheet.get_book().name = name
    for i,(label,values,units,axis) in enumerate(columns):
        sheet.from_list(i,list(values),lname=label,units=units,axis=axis)
    return sheet


def make_matrix(op, name, values):
    mat = op.new_sheet('m',lname=name)
    mat.get_book().name = name
    mat.from_np(values)
    mat.xymap = EXTENT
    return mat


def build(op, folder, target):
    data, receipt = read(folder/'dataset.json'), read(folder/'receipt.json')
    view = receipt['map_view']
    groups = {r['group']:r for r in rows(folder/'map-groups.csv')}
    sites = rows(folder/'map-sites.csv')
    keys, labels, grid, borders = geography(folder, view['division'], data)
    fields = [('percent','B','RateMap','降低率','%'),('kWh_m2','C','AreaMap','单位温控面积降低量','kWh/m²')]
    columns = [('分区',keys,'','N')]
    values = {}
    for field, _, _, title, units in fields:
        values[field] = [float(groups[k][field]) if groups.get(k,{}).get(field) else np.nan for k in keys]
        columns.append((title,values[field],units,'Y'))
    columns.extend([('分区名称',labels,'','N'),('配对地点数',[int(groups.get(k,{}).get('sites',0)) for k in keys],'','N'),
                    ('降低率有效地点数',[int(groups.get(k,{}).get('percent_sites',0)) for k in keys],'','N')])
    make_book(op,'RegionValues',columns)
    make_matrix(op,'RegionIDs',grid.astype(float))
    coast = make_book(op,'Boundaries',[('X',borders[:,0],'','X'),('Y',borders[:,1],'','Y')])
    coords = [s for s in sites if s['longitude'] and s['latitude'] and
              abs(float(s['longitude']))<=180 and abs(float(s['latitude']))<=90]
    stations = None
    if coords:
        xy = transform([[float(s['longitude']),float(s['latitude'])] for s in coords],True)
        stations = make_book(op,'Stations',[('X',xy[:,0],'','X'),('Y',xy[:,1],'','Y'),
            ('地点',[s['city'] for s in coords],'','N'),('分区',[s['group'] for s in coords],'','N'),
            ('地点降低率',[float(s['percent']) if s['percent'] else np.nan for s in coords],'%','Y'),
            ('地点降低量',[float(s['kWh_m2']) for s in coords],'kWh/m²','Y')])
    for field, letter, name, title, units in fields:
        mat = make_matrix(op,name,np.zeros(grid.shape))
        mat.activate()
        op.lt_exec(f'msetvalue im:=[{name}]1!1 formula:="ids[i,j]>0 ? vals[ids[i,j]] : -1E20" '
                   f'script:="range vals=[RegionValues]1!{letter};range ids=[RegionIDs]1!1;" recalculate:=auto;')
        expected = np.r_[-1e20, values[field]][grid]
        if not np.allclose(mat.to_np2d(),expected,equal_nan=True):
            raise ValueError('Origin 分区矩阵与导出数值不一致。')
        valid = [v for v in values[field] if np.isfinite(v)]
        cmap,norm = scale(valid,False)
        graph = op.new_graph(template='heatmap')
        graph.name = 'Graph'+letter
        layer = graph[0]
        plot = layer.add_plot(mat,colz=0)
        plot.zlevels = {'minors':3,'levels':list(np.linspace(norm.vmin,norm.vmax,6))}
        graph.lt_exec('layer.cmap.linkpal=0;')
        count = int(op.lt_float('layer.cmap.numColors'))
        def color(fraction):
            return 'color(%d,%d,%d)' % tuple(np.rint(np.asarray(cmap(float(fraction))[:3])*255).astype(int))
        for i in range(1,count+1):
            graph.lt_exec(f'layer.cmap.color{i}={color((i-.5)/count)};')
        graph.lt_exec(f'layer.cmap.colorBelow=color(255,255,255);layer.cmap.colorAbove={color(1)};'
                      'layer.cmap.colorMiss=color(217,222,221);layer.cmap.updateScale();')
        cl = layer.add_plot(coast,coly=1,colx=0,type='l')
        cl.color,cl.line_width = '#a6babb',0.35
        if stations is not None:
            marks = layer.add_plot(stations,coly=1,colx=0,type='s')
            marks.color,marks.symbol_size,marks.symbol_kind = '#243c47',2.4,2
        layer.set_xlim(-X,X); layer.set_ylim(-Y,Y)
        graph.lt_exec('page.width=10000;page.height=5900;layer.left=4;layer.top=18;layer.width=79;'
                      'layer.height=66.95;layer.x.showAxes=0;layer.y.showAxes=0;label -r legend;')
        graph.lt_exec(f'label -t {METRICS[view["metric"]]}显热需求 · {title};'
                      f'title.fsize=17;title.background=0;Spectrum1.title$="{units}";Spectrum1.labels.fsize=11;')
    op.lt_exec('merge_graph option:=specified graphs:="GraphB"+char(10)$+"GraphC" row:=1 col:=2 keep:=1 unit:=inch width:=16 height:=5.2;')
    pair = op.find_graph()
    if len(pair)!=2:
        raise ValueError('Origin 未生成双图图层。')
    pair.name = 'RegionalPair'
    pair.lname = ('气候分区' if view['division']=='climate' else '国家／地区')+' · '+METRICS[view['metric']]+'显热需求'
    aspect = op.lt_float('page.width')/op.lt_float('page.height')
    for index,(_,_,_,title,units) in enumerate(fields):
        pair.lt_exec(f'page.active={index+1};')
        pair.lt_exec(f'layer.unit=1;layer.left={3+50*index};layer.top=18;layer.width=39;'
                     f'layer.height={39*aspect/2};layer.showx=0;layer.showy=0;'
                     'layer.x.showLabels=0;layer.y.showLabels=0;'
                     'label -r xb;label -r yl;label -r title;')
        pair.lt_exec(f'label -n MapHeading "{METRICS[view["metric"]]}显热需求 · {title}";'
                     'MapHeading.attach=2;MapHeading.x=0;MapHeading.y=1.7;'
                     'MapHeading.font=font(Microsoft YaHei);MapHeading.fsize=18;MapHeading.background=0;')
    notes = op.new_notes('ReadMe')
    notes.text = ('编辑 RegionValues：B 列为左图降低率，C 列为右图单位面积降低量。保持分区行序。'
                  '按 Enter 提交后 RegionalPair 自动更新。色标范围在图层中可编辑。灰色区域为缺测。\n'
                  + (folder/'figure_caption.txt').read_text(encoding='utf-8-sig')+'\n'
                  + '对照：'+'  /  '.join(data['records'][side]['name'] for side in ('left','right'))+'\n'
                  + '数据快照 '+receipt['dataset_sha256']+'\n'
                  + (folder/'MAP_ATTRIBUTION.md').read_text(encoding='utf-8-sig'))
    pair.activate()
    if not op.save(str(target)):
        raise ValueError('Origin 工程保存失败。')


if __name__ == '__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent/'data/origin-python'))
    import originpro as op
    from origin_session import private_session
    with private_session(op):
        build(op,Path(sys.argv[1]),Path(sys.argv[2]).resolve())
