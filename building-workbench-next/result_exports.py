"""Small immutable comparison exports, with an explicit plotting subprocess."""
import csv
import io
import json
import math
from pathlib import Path
import re
import subprocess
import uuid
import zipfile
from foundation import ROOT, read_json, write_json, sha, digest, owned, now


def map_assets(root=ROOT):
    folder=Path(root)/'static/map'; manifest=read_json(folder/'manifest.json')
    for ref in manifest['files']:
        if sha(owned(folder/ref['file'],folder))!=ref['sha256']:raise ValueError('地图底图校验不一致。')
    return dict(manifest=manifest,grid=read_json(folder/'display-grid.json'),land=read_json(folder/'land.json'))


def color_limit(data):
    values=[abs(c[k+'_saved_MJ_m2_mean']) for c in data['classes'] for k in ('heating','cooling','total') if c[k+'_saved_MJ_m2_mean'] is not None]
    return max(1,math.ceil(max(values,default=1)/5)*5)


def figure_kind(data):
    if data['metric']=='temperature' or data['blocked'] or not data['paired_sites']:return None
    if data['selected_sites']==1 and len(data['sites'])==1 and data['sites'][0]['status']=='paired':return 'site'
    if data.get('normalized') and any(c['valid_sites'] for c in data['classes']):return 'climate'
    return None


def annual_site_rows(data):
    site=data['sites'][0]
    return [dict(site_id=site['site_id'],city=site['city'],demand=kind,
        data_retention='contains_retained_summary' if __import__('summary_retention').notices(data) else 'full_evidence',
        reference_kWh=site[f'left_{kind}_kWh'],study_kWh=site[f'right_{kind}_kWh'],
        saved_kWh=site[f'{kind}_saved_kWh'],saved_percent=site[f'{kind}_saved_percent'])
        for kind in ('heating','cooling','total')]


def csv_bytes(rows):
    if not rows:return b''
    fields=list(rows[0]); out=io.StringIO(newline=''); w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
    for row in rows:
        clean={}
        for k,v in row.items():
            if isinstance(v,(dict,list)):v=str(v)
            if isinstance(v,str) and v[:1] in ('=','+','-','@','\t','\r'):v="'"+v
            clean[k]=v
        w.writerow(clean)
    return out.getvalue().encode('utf-8-sig')


def load_export(ident,root=ROOT):
    if not re.fullmatch(r'comparison_export_[a-f0-9]{32}',str(ident)):raise ValueError('导出编号不正确。')
    folder=owned(Path(root)/'data/comparison-exports'/ident,root); receipt=read_json(folder/'receipt.json')
    for name, checksum in receipt['files'].items():
        if sha(owned(folder/name,folder))!=checksum:raise ValueError('导出文件校验不一致。')
    return folder,receipt


def export(data, root=ROOT):
    root=Path(root).resolve()
    if data['blocked'] or not data['paired_sites']:raise ValueError('当前没有可导出的有效配对，请先检查结果来源和排除原因。')
    kind=figure_kind(data);assets=map_assets(root) if kind=='climate' else None
    notices={'MAP_ATTRIBUTION.md':ROOT/'third_party/THIRD_PARTY_MAPS.md','atlas-LICENSE.txt':ROOT/'third_party/atlas-LICENSE.txt'} if assets else {}
    key=digest(dict(annotations=sha(ROOT/'review_annotations.py'),dataset=data['dataset_sha256'],map=assets['manifest'] if assets else None,notices={k:sha(v) for k,v in notices.items()},figure=kind,exporter=sha(ROOT/'result_exports.py'),plotter=sha(ROOT/'plot_comparison.py')))
    ident='comparison_export_'+key[:32];folder=owned(root/'data/comparison-exports'/ident,root)
    if folder.exists():return load_export(ident,root)[1]
    stage=folder.parent/('.preparing_'+uuid.uuid4().hex);stage.mkdir(parents=True)
    write_json(stage/'dataset.json',data,root)
    if assets:write_json(stage/'map.json',assets,root)
    for name,source in notices.items():
        (stage/name).write_bytes(source.read_bytes())
    from review_annotations import annotate,export_notes
    export_notes(stage,data,root)
    if kind=='site':(stage/'period-loads.csv').write_bytes(csv_bytes(annotate(annual_site_rows(data),data)))
    for name,rows in [('sites',data['sites']),('climates',data['classes']),('monthly',data['monthly']),('rooms',data['rooms'])]:
        if rows:
            table=[{k:v for k,v in r.items() if not k.endswith('_evidence') and not k.endswith('_pending_warnings')} for r in rows]
            from summary_retention import notices
            if notices(data):
                for row in table:row['data_retention']='contains_retained_summary'
            if name=='sites':
                from research_input_notes import export_text
                for row in table:
                    for side,note in data.get('research_input_notes',{}).items():
                        row[side+'_research_input_note']=export_text(note)
            (stage/(name+'.csv')).write_bytes(csv_bytes(annotate(table,data)))
    readme=f'''比较名称：{data['comparison']['name']}
参考：{data['records']['left']['name']}，版本 {data['records']['left']['revision']}，来源 {data['left']['id']}
研究：{data['records']['right']['name']}，版本 {data['records']['right']['revision']}，来源 {data['right']['id']}
数据标识：{data['dataset_sha256']}
计算时段：{data['period']}；步长：{data['step_minutes']} min；有效地点：{data['paired_sites']}/{data['selected_sites']}。
{data['note']}
{data['difference']}。{data['energy_basis']}。归一化面积：{data['conditioned_area_m2']} m²。

Origin 编辑：
1. 导入 climates.csv 或 sites.csv；空白保留为缺失，不能填零。表头记录指标与单位。
2. 气候图用 climate 为分类 X，*_saved_MJ_m2_mean 为 Y。
   上下范围分别由 max-mean、mean-min 计算，是地点范围而不是统计误差。
3. map_heating/cooling/total.csv 是 360 行 × 720 列矩阵，无表头。
   行从北到南，中心纬度 89.75 至 -89.75，列从西到东，中心经度 -179.75 至 179.75；间隔 0.5°。
   转换为 Origin 矩阵时先上下翻转，使首行对应 -89.75，再设置 XY 范围并绘制图像图。
   matrix_climate.csv 保留气候类型 ID，0 表示无分类区域，用于区分海洋与无结果气候类型。
4. 三张地图统一使用对称色标 ±{color_limit(data)} MJ/m²；蓝色为负、白色为零、红色为正；缺失陆地为灰色。
5. figure.svg/PDF 为可编辑矢量文字与图形（地图网格为栅格嵌入）；PNG 为 300 dpi。
   需要修改数据时重新导出，不要把图上的文字修改当作计算数据更新。

地图为既有 1991–2020 Köppen–Geiger 气候分区的 0.5°展示网格，等距圆柱投影。
小面积气候可能在展示网格消失，30 类表格始终保留全部类型。
此包固定导出时已通过的结果。后续计算完成后需重新读取比较结果并导出新包。
dataset.json 包含逐地点排除原因、来源证据及原警告。receipt.json 保存文件校验值。
'''
    if data['metric']=='temperature':
        readme=readme.split('Origin 编辑：')[0]+'''Origin 编辑：
导入 rooms.csv，以 site_id 和 zone 共同确定房间。left 为参考、right 为研究。
right_minus_left_mean_C 是时段平均温度之差，单位 °C。
min/max 的差是各自时段极值之差，并非同一时刻的温差。
当前没有约定房间权重或舒适度评价指标，因此不导出气候类型温度地图。
sites.csv 保留未纳入地点及原因。dataset.json 保存来源和全部配对证据。
'''
    elif not data.get('normalized'):
        readme=readme.split('Origin 编辑：')[0]+'''Origin 编辑：
导入 sites.csv、monthly.csv 或 climates.csv。left 为参考、right 为研究。
*_saved_kWh 是参考减研究，正值表示显热需求降低。空白保留为缺失。
尚无核实温控面积，因此保留 kWh 数据，不生成 MJ/m² 地图或图形文件。
气候类型范围由有效代表点最小值和最大值构成，并非置信区间。
dataset.json 保存来源和全部配对证据。
'''
    if kind=='site':
        prefix=readme.split('Origin 编辑：')[0].replace(data['note'],'本图只比较所选地点；未将它外推到同类气候区域。')
        readme=prefix+'''Origin 编辑：
1. 导入 period-loads.csv：demand 为分类 X（heating、cooling、total），reference_kWh 与 study_kWh 为两组 Y，绘制分组柱状图。
2. 导入 monthly.csv：month 为 X，heating_saved_kWh、cooling_saved_kWh 为两组 Y；总变化另见 total_saved_kWh。
3. saved 是参考减研究，正值为需求降低，负值为需求增加。saved_percent 的分母为对应参考需求；空白表示比例不适用，不能填零。
4. figure.svg 和 figure.pdf 为可编辑矢量图，figure.png 为 300 dpi。图中使用 kWh，不依赖温控面积归一化；CSV 同时保留已核实的面积归一化指标（若有）。
5. 短时段只统计实际选择的日期；月度行也仅包含所选日期覆盖的部分，不自动解释为完整月份。图题和图注记录统计时段。

图表表示建筑显热需求，不是设备电耗。不生成气候地图或空地图矩阵。
本包不自动创建 Origin 工程；图表与数据表可在 Origin 导入后编辑。
dataset.json 保留原始数据标识、方案版本、来源批次及复核证据；此包不改写计算结果。
'''
    elif data['metric']!='temperature' and kind is None and data.get('normalized'):
        readme=readme.split('Origin 编辑：')[0].replace(data['note'],'本次没有已分类且可配对的气候代表结果，按地点保留数据。')+'''Origin 编辑：
导入 sites.csv 与 monthly.csv，按 site_id 分组查看；不能将不同地点直接平均成气候类型结果。
left 为参考、right 为研究；saved 为参考减研究。空白保留为缺失。
本包保留逐地点数据与来源，不生成全灰地图或地图矩阵。
'''
    from research_input_notes import export_text
    notes=[('参考' if side=='left' else '研究')+'：'+export_text(note) for side,note in data.get('research_input_notes',{}).items() if note]
    if notes:readme='研究输入适用性\n'+'\n'.join(notes)+'\n数值警告接受与研究输入是否符合约定分别核对。\n\n'+readme
    if assets:readme+='\n地图署名与许可见 MAP_ATTRIBUTION.md 和 atlas-LICENSE.txt。单独分享或修改地图时应保留来源、许可链接与修改说明。\n'
    (stage/'编辑说明.txt').write_text(readme,encoding='utf-8-sig')
    if kind:
        from runtime_settings import plotting_python
        python=plotting_python(root)
        run=subprocess.run([str(python),'-X','utf8',str(ROOT/'plot_comparison.py'),str(stage)],capture_output=True,text=True,encoding='utf-8',
            timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode:raise ValueError('论文图导出失败：'+run.stderr[-600:])
    from summary_retention import export_notice
    export_notice(stage,data)
    with zipfile.ZipFile(stage/'comparison.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(stage.iterdir()):
            if p.name!='comparison.zip':archive.write(p,p.name)
        archive.writestr('receipt.json',json.dumps(dict(dataset_sha256=data['dataset_sha256'],files={p.name:sha(p) for p in stage.iterdir() if p.name!='comparison.zip'},new_simulations=0),ensure_ascii=False,indent=2))
    receipt=dict(id=ident,created=now(),dataset_sha256=data['dataset_sha256'],paired_sites=data['paired_sites'],figure_kind=kind,
        files={p.name:sha(p) for p in stage.iterdir()},new_simulations=0,source_results_modified=False)
    write_json(stage/'receipt.json',receipt,root)
    # Same snapshot exported concurrently may already have been atomically published.
    try:stage.rename(folder)
    except FileExistsError:return load_export(ident,root)[1]
    return receipt
