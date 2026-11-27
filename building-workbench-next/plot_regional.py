"""Render a paired comparison by climate or map unit from its pinned site results."""
import base64
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
import textwrap

import matplotlib
matplotlib.use('Agg')
from matplotlib import colors, font_manager, pyplot as plt
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import Ellipse, PathPatch
from matplotlib.path import Path as MapPath
from matplotlib.projections.geo import MollweideAxes
import numpy as np


INK = '#162e39'
MUTED = '#465d65'
MISSING = '#d9dedd'
TEAL = ['#daf2ef','#98dace','#46b6a5','#177f80','#115969','#12364c']
METRICS = {'total':'冷热合计','heating':'供暖','cooling':'制冷'}
PROJECTION = MollweideAxes.MollweideTransform(1)


def geography(codebook):
    aliases = defaultdict(set)
    for code, unit in codebook.items():
        for label in unit['names']:
            aliases[label.casefold()].add(code)
    return aliases


def region_for(site, aliases):
    # Prefer the registered geographic identity. Some catalogues only encode ISO3 in the EPW id.
    for key in ('country_code','country'):
        codes = aliases.get(str(site.get(key) or '').strip().casefold(), set())
        if len(codes) == 1:
            return next(iter(codes))
    prefix = str(site['site_id']).partition('_')[0]
    if len(prefix) == 3 and prefix.isascii() and prefix.isupper():
        codes = aliases.get(prefix.casefold(), set())
        if len(codes) == 1:
            return next(iter(codes))
    return None


def province_groups(sites, boundaries):
    valid = [s for s in sites if s.get('longitude') is not None and s.get('latitude') is not None
             and -180 <= s['longitude'] <= 180 and -90 <= s['latitude'] <= 90]
    if not valid:
        return {}
    points = np.array([(s['longitude'],s['latitude']) for s in valid])
    matches = [set() for _ in valid]
    for code, polys in boundaries.items():
        for exterior, *holes in polys:
            path = MapPath(exterior)
            lo, hi = path.get_extents().get_points()
            candidates = np.flatnonzero(((points >= lo) & (points <= hi)).all(axis=1))
            if not len(candidates):
                continue
            inside = path.contains_points(points[candidates])
            for hole in holes:
                inside &= ~MapPath(hole).contains_points(points[candidates])
            for i in candidates[inside]:
                matches[i].add(code)
    return {s['site_id']:next(iter(m)) for s,m in zip(valid,matches) if len(m)==1}


def aggregate(data, division, metric, regions, provinces=None):
    aliases = geography(regions)
    climate_ids = {c['climate'] for c in data['classes']}
    groups = defaultdict(list)
    points = []
    for s in data['sites']:
        if s['status'] != 'paired':
            continue
        group = region_for(s, aliases) if division == 'country' else s.get('climate')
        if division=='china':
            group=provinces.get(s['site_id'])
        if division == 'climate' and group not in climate_ids:
            group = None
        saved = s[metric+'_saved_kWh']
        row = dict(site_id=s['site_id'],city=s['city'],group=group,latitude=s.get('latitude'),
                   longitude=s.get('longitude'),percent=s[metric+'_saved_percent'],
                   kWh_m2=saved/data['conditioned_area_m2'])
        points.append(row)
        if group:
            groups[group].append(row)
    summary = {}
    for group, rows in sorted(groups.items()):
        rates = [r['percent'] for r in rows if r['percent'] is not None]
        intensity = mean(r['kWh_m2'] for r in rows)
        summary[group] = dict(group=group,sites=len(rows),percent_sites=len(rates),
                              percent=mean(rates) if rates else None,kWh_m2=intensity,MJ_m2=intensity*3.6)
    return summary, points


def transform(coords, curved, division=None):
    points = np.asarray(coords,dtype=float)
    if curved and division=='china':
        points=points-[105,0]
    return PROJECTION.transform(np.deg2rad(points)) if curved else points


def map_extent(division,curved,regions):
    if division!='china':
        x,y=(2*np.sqrt(2),np.sqrt(2)) if curved else (180,90)
        return (-x,x,-y,y)
    points=np.concatenate([transform(p[0],curved,division) for unit in regions.values() for p in unit['polygons']])
    lo,hi=points.min(axis=0),points.max(axis=0)
    pad=(hi-lo)*.03
    return (lo[0]-pad[0],hi[0]+pad[0],lo[1]-pad[1],hi[1]+pad[1])


def polygons(regions, curved, division):
    shapes, ids = [], []
    for code, unit in regions.items():
        for poly in unit['polygons']:
            rings = []
            for ring in poly:
                coords = transform(ring, curved, division)
                commands = np.full(len(coords),MapPath.LINETO,dtype=np.uint8)
                commands[0], commands[-1] = MapPath.MOVETO, MapPath.CLOSEPOLY
                rings.append(MapPath(coords,commands))
            shapes.append(PathPatch(MapPath.make_compound_path(*rings)))
            ids.append(code)
    return shapes, ids


def climate_raster(assets,curved):
    grid = assets['grid']
    source = np.frombuffer(base64.b64decode(grid['data']),np.uint8).reshape(grid['height'],grid['width'])
    if not curved:
        return source
    # Sample destination pixel centres in geographical coordinates, keeping sea transparent.
    w, h = 1080, 540
    x = (2*(np.arange(w)+.5)/w-1)*2*np.sqrt(2)
    y = (1-2*(np.arange(h)+.5)/h)*np.sqrt(2)
    xx, yy = np.meshgrid(x,y)
    theta = np.arcsin(yy/np.sqrt(2))
    lon = np.pi*xx/(2*np.sqrt(2)*np.cos(theta))
    lat = np.arcsin((2*theta+np.sin(2*theta))/np.pi)
    columns = np.clip(((lon/np.pi+1)*grid['width']/2).astype(int),0,grid['width']-1)
    rows = np.clip(((.5-lat/np.pi)*grid['height']).astype(int),0,grid['height']-1)
    return np.where(np.abs(lon)<=np.pi,source[rows,columns],0)


def scale(values, standard):
    valid = [v for v in values if v is not None]
    extreme = max((abs(v) for v in valid),default=0)
    step = 10**np.floor(np.log10(extreme)) if extreme else 1
    limit = np.ceil(extreme/(step/2))*(step/2) if extreme else 1
    signed = standard or any(v<0 for v in valid)
    palette = ['#2166ac','#f7f7f7','#b2182b'] if standard else (
        ['#ac4e2e','#faeee4','#f5f8f7','#49ad9f','#12364c'] if signed else TEAL)
    cmap = colors.LinearSegmentedColormap.from_list('paired-demand',palette)
    cmap.set_bad(MISSING)
    return cmap, colors.Normalize(-limit if signed else 0,limit)


def station_marks(ax, stations, field, cmap, norm, curved, division):
    labels = len(stations)<=12
    renderer = ax.figure.canvas.get_renderer()
    occupied = []
    for s in stations:
        lon,lat = s['longitude'],s['latitude']
        if lon is None or lat is None or not (-180<=lon<=180 and -90<=lat<=90):
            continue
        xy = transform([[lon,lat]],curved,division)[0]
        val = s[field] if field!='MJ_m2' else s['kWh_m2']*3.6
        if val is None:
            continue
        ax.scatter(*xy,s=22 if labels else 7,facecolor=cmap(norm(val)),edgecolor=INK,linewidth=.6,zorder=5)
        if labels:
            label = f"{s['city']}  {val:.1f}"+('%' if field=='percent' else '')
            for dx,dy in [(9,12),(-9,12),(9,-14),(-9,-14),(10,28),(-10,-28)]:
                text = ax.annotate(label,xy,xytext=(dx,dy),textcoords='offset points',ha='left' if dx>0 else 'right',
                    va='center',fontsize=8.4,color=INK,zorder=6,
                    bbox=dict(boxstyle='round,pad=.14',fc='white',ec='none',alpha=.9),
                    arrowprops=dict(arrowstyle='-',lw=.6,color=MUTED))
                text.update_positions(renderer)
                box = text.get_bbox_patch()
                text.update_bbox_position_size(renderer)
                bounds = box.get_window_extent(renderer).expanded(1.02,1.1)
                if ax.bbox.contains(*bounds.min) and ax.bbox.contains(*bounds.max) and not any(bounds.overlaps(b) for b in occupied):
                    occupied.append(bounds)
                    break
                text.remove()


def plot(folder, division, style, metric, font, *, preview=False):
    folder = Path(folder)
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    data = read(folder/'dataset.json')
    regions = read(folder/'map-regions.json') if division!='climate' else {}
    provinces={}
    if division=='china':
        with gzip.open(Path(__file__).parent/'static/map/china-membership.json.gz','rt',encoding='utf8') as f:
            provinces=province_groups(data['sites'],json.load(f))
    summary, sites = aggregate(data,division,metric,regions,provinces)
    if not summary:
        if division=='china' and all(s['latitude'] is None or s['longitude'] is None for s in sites):
            raise ValueError('已配对地点缺少经核实的气象站经纬度。请检查原算例的 EPW 气象文件及其 LOCATION 表头。')
        raise ValueError('配对地点的经纬度均未匹配到中国省级边界。' if division=='china' else
                         '此批配对地点缺少可识别的'+('国家／地区' if division=='country' else '气候类型')+'。')
    if not preview:
        for name, rows in [('map-groups',list(summary.values())),('map-sites',sites)]:
            with (folder/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=font).get_name(),'axes.unicode_minus':False,
                         'pdf.fonttype':42,'svg.fonttype':'none','text.parse_math':False})
    curved = style=='pair'
    period = '全年' if data['annual'] else '%d月%d日—%d月%d日'%tuple(data['period'])
    geography_label = {'country':'国家／地区','china':'中国省级行政区','climate':'气候类型'}[division]
    area = data['conditioned_area_m2']
    title = f'{period}建筑{METRICS[metric]}显热需求变化'
    paired = sum(r['sites'] for r in summary.values())
    names = '   对比   '.join(data['records'][side]['name'] for side in ('left','right'))
    fig = plt.figure(figsize=(16,7.2) if curved else (10.5,7.2),facecolor='white')
    fig.text(.04,.92,title,fontsize=24,color=INK,weight='bold')
    fig.text(.04,.846,'\n'.join(textwrap.wrap(names,86 if curved else 57,max_lines=2,placeholder='…')),fontsize=11.5,color=MUTED)
    left_edges = [.036,.52] if curved else [.05]
    fields = ['percent','kWh_m2'] if curved else ['MJ_m2']
    extent=map_extent(division,curved,regions)
    if division!='climate':
        shapes, codes = polygons(regions,curved,division)
    else:
        assets = read(folder/'map.json'); raster=climate_raster(assets,curved)
        coasts = [transform(ring,curved) for poly in assets['land']['coordinates'] for ring in poly]
    for x,field in zip(left_edges,fields):
        width = .448 if curved else .90
        ax=fig.add_axes([x,.256,width,.47])
        hdr={'percent':'显热需求降低率','kWh_m2':'单位温控面积的需求降低量','MJ_m2':'单位温控面积的需求降低量'}[field]
        fig.text(x+.005,.758,hdr,fontsize=16,color=INK,weight='bold')
        xmax,ymax=(2*np.sqrt(2),np.sqrt(2)) if curved else (180,90)
        ax.set(xlim=extent[:2],ylim=extent[2:],aspect='equal');ax.set_axis_off()
        if curved and division!='china':
            ax.add_patch(Ellipse((0,0),2*xmax,2*ymax,fc='#f8fafb',ec='#c8d2d4',lw=.6))
            for lon in [-120,-60,0,60,120]:
                ax.plot(*transform(np.column_stack((np.full(91,lon),np.linspace(-89.9,89.9,91))),True).T,color='#dfe8e9',lw=.4)
            for lat in [-60,-30,0,30,60]:
                ax.plot(*transform([[-180,lat],[180,lat]],True).T,color='#dfe8e9',lw=.4)
        cmap,norm = scale([r[field] for r in summary.values()],not curved)
        if not curved and division=='climate':
            from result_exports import color_limit
            norm.vmin,norm.vmax=-color_limit(data),color_limit(data)
        if division!='climate':
            values=np.array([summary.get(c,{}).get(field) for c in codes],dtype=float)
            ax.add_collection(PatchCollection(shapes,facecolors=cmap(norm(values)),edgecolors='#a6babb',linewidths=.25,zorder=2))
        else:
            lut=np.full(31,np.nan)
            for c in data['classes']:
                lut[c['id']]=summary.get(c['climate'],{}).get(field,np.nan)
            rgba=cmap(norm(lut[raster]));rgba[raster==0,3]=0
            ax.imshow(rgba,extent=(-xmax,xmax,-ymax,ymax),interpolation='nearest',origin='upper',zorder=2)
            ax.add_collection(LineCollection(coasts,colors='#9aadae',linewidths=.22,zorder=3))
        ax.apply_aspect()
        station_marks(ax,[s for s in sites if s['group']],field,cmap,norm,curved,division)
        cbax=fig.add_axes([x+width*.13,.232,width*.74,.019])
        cb=fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm,cmap=cmap),cax=cbax,orientation='horizontal')
        cb.outline.set_visible(False);cb.ax.tick_params(labelsize=9,colors=MUTED)
        cb.set_label({'percent':'%','kWh_m2':'kWh/(m²·年)' if data['annual'] else 'kWh/m²（所选时段）','MJ_m2':'MJ/m²'}[field],color=MUTED)
    fig.add_artist(plt.Line2D([.04,.96],[.132,.132],transform=fig.transFigure,lw=.8,color='#d6dfdf'))
    fig.text(.041,.09,f'按{geography_label}着色 · {paired}/{len(sites)} 个配对地点入图 · 分区内各站等权 · 灰色为缺少有效值 · 温控面积 {area:g} m²',fontsize=10,color=INK)
    warnings=[]
    if any(s.get('pairing_basis')=='跨步长豁免' for s in data['sites']):warnings.append('含跨步长豁免')
    if __import__('summary_retention').notices(data):warnings.append('含保留摘要')
    if (folder/'user-review-notes.json').exists():warnings.append('含已复核警告')
    source='Natural Earth（公有领域）· 1:5000 万地图单元' if division=='country' else 'Beck et al. (2023), CC BY 4.0 · 1991–2020 · Natural Earth / @d3-maps/atlas (MIT)'
    if division=='china':
        source='省级边界与站点归属按 2022 年划分 · sheng2022 · 34 个省级行政区'
    fig.text(.041,.053,'参考减研究，正值表示需求降低。'+('降低率取参考需求非零站点的百分比均值。' if curved else '')+'   '+' · '.join(warnings),fontsize=9,color=MUTED)
    fig.text(.041,.018,f'{source}   |   数据 {data["dataset_sha256"][:16]}',fontsize=7.7,color=MUTED)
    if preview:
        fig.savefig(folder/'preview.png',dpi=105,facecolor='white')
        plt.close(fig)
        return
    from origin_map_inputs import write as write_origin_inputs
    write_origin_inputs(folder,data,division,curved,metric,regions,extent,summary,sites)
    for ext in ('svg','pdf','png'):
        fig.savefig(folder/('figure.'+ext),dpi=200,facecolor='white')
    plt.close(fig)
    (folder/'figure_caption.txt').write_text(f'{title}。参考与研究：{names}。按{geography_label}取地点等权均值。'
        f'共 {paired}/{len(sites)} 个配对地点匹配分区，见 map-sites.csv 与 map-groups.csv。温控面积 {area:g} m²。'
        f'降低率只统计参考需求非零的站点。底图：{source}。数据：{data["dataset_sha256"]}。',encoding='utf-8')


if __name__=='__main__':
    import sys
    plot(*sys.argv[1:],preview=True)
