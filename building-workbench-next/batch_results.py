"""Version-bound batch views and immutable exports; never dispatches jobs."""
from pathlib import Path
import math
import statistics
import uuid
import zipfile
import json
import re
from foundation import ROOT, read_json, write_json, sha, digest, owned, loads, now
from record_store import Store
from comparison_results import batch_rows, execution
from result_exports import csv_bytes
from research_input_notes import export_text

STATUS = dict(passed='核验通过',reused='已复用',review='待复核',pending='排队',running='计算中',
              failed='失败',interrupted='中断',cancelled='已取消')
NOTE = '负荷为所选时段的显热冷热需求，不是设备耗电量。气候汇总仅纳入通过核验的温控结果，类内代表地点等权，范围为地点最小/最大值；不表示置信区间或全球建筑总量。'


def aggregate(rows, classes, area):
    output=[]
    for c in classes:
        selected=[r for r in rows if r['climate']==c['climate'] and r['mode']=='controlled']
        valid=[r for r in selected if r['accepted'] and r.get('loads') is not None]
        row=dict(climate=c['climate'],name=c['name'],selected_sites=len(selected),valid_sites=len(valid),
                 status='no_data' if not valid else 'partial' if len(valid)<len(selected) else 'available')
        for metric in ('heating','cooling','total'):
            values=[r['loads'][metric+'_kWh'] for r in valid]
            for stat,fn in [('mean',statistics.fmean),('min',min),('max',max)]:
                row[metric+'_kWh_'+stat]=fn(values) if values else None
                row[metric+'_MJ_m2_'+stat]=row[metric+'_kWh_'+stat]*3.6/area if values and area else None
        output.append(row)
    return output


def build(ident, catalog, root=ROOT):
    from execution_queue import Queue
    q=Queue(root)
    def jobs():
        with q.db() as db:return [dict(j) for j in db.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx',(ident,))]
    for _ in range(3):
        before=jobs();result=_build(ident,catalog,root)
        if jobs()==before:return result
    raise ValueError('计算状态正在变化，请稍后刷新本批结果。')


def _build(ident, catalog, root=ROOT):
    batches=batch_rows(root,ident)
    if len(batches)!=1:raise ValueError('未找到批次。')
    b=batches[0];plan=loads(b['plan'])
    record=Store(catalog,root).get(plan['record_id'],plan['revision'])
    modes=sorted({c['mode'] for c in plan['cases']})
    sources={mode:execution(record,ident,mode,root) for mode in modes}
    area=plan['conditioned_area_m2']
    if area is not None and (isinstance(area,bool) or not isinstance(area,(int,float)) or not math.isfinite(area) or area<=0):
        raise ValueError('温控面积记录无效。')
    rows=[]
    for c in plan['cases']:
        r=sources[c['mode']]['cases'][c['site_id']];site=catalog['sites'][c['site_id']]
        review=r.get('evidence',{}).get('scientific_review')
        accepted=r['status'] in ('passed','reused')
        rows.append(dict(r,index=c['index'],site_id=c['site_id'],city=c['city'],
            climate=site.get('climate') or '',site_kind=site.get('site_kind') or '地点',
            country=site.get('country') or '',latitude=site.get('latitude'),longitude=site.get('longitude'),
            accepted=accepted,acceptance='reviewed' if review else 'passed' if accepted else r['status'],
            status_label='附说明接受' if review else STATUS.get(r['status'],r['status']),review_info=review,
            pending_warnings=r.get('pending_warnings',[]),error=None,
            loads_MJ_m2={k.replace('_kWh','_MJ_m2'):v*3.6/area for k,v in r['loads'].items()} if area and r.get('loads') else None))
    # Failure and interruption explanations are queue metadata, not zero loads.
    from execution_queue import Queue
    q=Queue(root)
    with q.db() as db:
        jobs={j['idx']:dict(j) for j in db.execute('SELECT * FROM jobs WHERE batch=?',(ident,))}
    from execution_failure_view import describe
    for r in rows:
        r['error']=jobs[r['index']]['error']
        if r['status']=='failed':r['failure_info']=describe(jobs[r['index']],root)
    counts=dict(total=len(rows),completed=sum(bool(r.get('artifacts')) for r in rows),
        accepted=sum(r['accepted'] for r in rows),reviewed=sum(r['acceptance']=='reviewed' for r in rows),
        routine_passed=sum(r['acceptance']=='passed' for r in rows),
        pending_review=sum(r['status']=='review' for r in rows),
        unfinished=sum(r['status'] in ('pending','running','interrupted') for r in rows),
        failed=sum(r['status']=='failed' for r in rows),cancelled=sum(r['status']=='cancelled' for r in rows))
    result=dict(id=ident,record_name=plan['record_name'],record_id=plan['record_id'],revision=plan['revision'],
        bundle_id=plan['bundle_id'],plan_sha256=b['checksum'],record_sha256=digest(record),
        period=record['factors']['scope']['period'],step_minutes=record['numerics']['step_minutes'],
        annual=record['factors']['scope']['period']==[1,1,12,31],conditioned_area_m2=area,
        counts=counts,modes=modes,results=rows,
        classes=aggregate(rows,(catalog['global_bundle'].get('historical') or {'dataset':{'classes':catalog['global_bundle']['classes']}})['dataset']['classes'],area),
        energy_basis='显热冷热需求 / kWh',note=NOTE)
    from research_input_notes import describe
    result['research_input_note']=describe(record,catalog)
    result['dataset_sha256']=digest(result)
    return result


def tables(data):
    from research_input_notes import export_text
    note=data.get('research_input_note')
    sites=[];monthly=[];temperatures=[];systems=[];reviews=[]
    for r in data['results']:
        common={k:r[k] for k in ('index','site_id','city','climate','site_kind','mode','status','acceptance','accepted')}
        common.update(research_input_status=note['status'] if note else '',research_input_note=export_text(note))
        sites.append(dict(common,period='-'.join(map(str,r['period'])),step_minutes=r['step_minutes'],days=r.get('days'),
            **{k:r.get('loads',{}).get(k) if r.get('loads') is not None else None for k in ('heating_kWh','cooling_kWh','total_kWh')},
            **{k:r.get('loads_MJ_m2',{}).get(k) if r.get('loads_MJ_m2') is not None else None for k in ('heating_MJ_m2','cooling_MJ_m2','total_MJ_m2')},
            pending_warnings='；'.join(r['pending_warnings']),excluded_reason='' if r['accepted'] else r['error'] or r['status_label']))
        for m in r.get('monthly',[]):monthly.append(dict(common,**m))
        for t in r.get('temperatures',[]):temperatures.append(dict(common,**t))
        for s in r.get('rooms',[]):systems.append(dict(common,**s))
        if r['review_info']:reviews.append(dict(common,**r['review_info']))
    return dict(sites=sites,monthly=monthly,room_temperatures=temperatures,system_loads=systems,climates=data['classes']),reviews


def load_export(ident, root=ROOT):
    if not re.fullmatch(r'batch_export_[a-f0-9]{32}',str(ident)):raise ValueError('批次导出编号不正确。')
    folder=owned(Path(root)/'data/batch-exports'/ident,root);receipt=read_json(folder/'receipt.json')
    for name,h in receipt['files'].items():
        if sha(owned(folder/name,folder))!=h:raise ValueError('批次导出文件内容发生变化。')
    return folder,receipt


def export(data, root=ROOT):
    if not data['counts']['completed']:raise ValueError('本批尚无已完成结果。')
    key=digest(dict(dataset=data['dataset_sha256'],exporter=sha(ROOT/'batch_results.py'),reviewer=sha(ROOT/'review_evidence.py'),csv_writer=sha(ROOT/'result_exports.py')))
    ident='batch_export_'+key[:32];folder=owned(Path(root)/'data/batch-exports'/ident,root)
    if folder.exists():return load_export(ident,root)[1]
    stage=folder.parent/('.preparing_'+uuid.uuid4().hex);stage.mkdir(parents=True)
    write_json(stage/'dataset.json',data,root)
    outputs,reviews=tables(data)
    for name,rows in outputs.items():
        if rows:(stage/(name+'.csv')).write_bytes(csv_bytes(rows))
    write_json(stage/'review-notes.json',reviews,root)
    # Small original/evidence documents travel with the export. Raw SQL and
    # weather remain linked by identity and hash rather than being duplicated.
    documents={}
    for r in data['results']:
        v=r['review_info']
        if not v:continue
        for key in ('original_result','evidence'):
            p=Path(v[key]);h=v[key+'_sha256']
            if sha(p)!=h:raise ValueError('导出期间复核依据发生变化，请重新读取。')
            name='review-evidence/'+h+'.json'
            if name not in documents:
                target=stage/name;target.parent.mkdir(exist_ok=True);target.write_bytes(p.read_bytes())
                if sha(target)!=h:raise ValueError('导出期间复核依据发生变化，请重新读取。')
                documents[name]=h
    write_json(stage/'review-evidence-index.json',documents,root)
    text=f'''批次：{data['record_name']}，版本 {data['revision']}
时段：{data['period']}；步长：{data['step_minutes']} min；核实温控面积：{data['conditioned_area_m2']} m²。
已接受 {data['counts']['accepted']}/{data['counts']['total']} 项，其中附说明接受 {data['counts']['reviewed']} 项；待复核 {data['counts']['pending_review']} 项。
{data['note']}
{export_text(data.get('research_input_note'))}

sites.csv 保留所有所选算例及其状态，包括待复核、失败和未完成项；空白是缺失，不能填零。
monthly.csv 为所选时段内的月度显热负荷，短时段并非完整月份；系统时间步不写入常规导出。
room_temperatures.csv 为各房间的时段均温与极值；没有跨房间或跨气候加权舒适指标。
system_loads.csv 保留各 IdealLoads 系统的显热供暖/制冷需求，不擅自把系统名称当作房间名称。
climates.csv 仅汇总 accepted=true 的温控算例；待复核、失败及未完成均不纳入。自然室温没有气候均温。
没有核实面积时，MJ/m² 留空。Csc 等无有效地点的类型保留无数据；零负荷与缺失有区别。

可在 Origin 导入上述 CSV，按列名识别指标与单位。类内 min/max 是地点范围，不是统计误差。
这是单方案的负荷结果，不是材料节能量；比较材料效果需使用共同建筑、运行设置、气象和求解设置的配对结果。

review-notes.json 保存已接受警告及适用范围；review-evidence/ 保存对应原汇总与接受依据的精确副本，文件名为校验值。
dataset.json 保存任务身份、来源路径及摘要；原始模型、气象和 SQL 保持原位置，未打包复制。
本包固定导出时的快照，后续计算或复核完成后需刷新并重新导出。筛选页面只影响显示，导出包含完整批次。
数据标识：{data['dataset_sha256']}
'''
    (stage/'阅读说明.txt').write_text(text,'utf-8-sig')
    files={str(p.relative_to(stage)).replace('\\','/'):sha(p) for p in stage.rglob('*') if p.is_file()}
    with zipfile.ZipFile(stage/'batch.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in files:z.write(stage/name,name)
        z.writestr('receipt.json',json.dumps(dict(dataset_sha256=data['dataset_sha256'],files=files,new_simulations=0),ensure_ascii=False,indent=2))
    files['batch.zip']=sha(stage/'batch.zip')
    receipt=dict(id=ident,created=now(),dataset_sha256=data['dataset_sha256'],batch_id=data['id'],counts=data['counts'],files=files,new_simulations=0)
    write_json(stage/'receipt.json',receipt,root)
    try:stage.rename(folder)
    except FileExistsError:return load_export(ident,root)[1]
    return receipt
