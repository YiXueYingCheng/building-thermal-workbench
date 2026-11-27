"""Read selected wall traces from registered spectral-material runs."""
import datetime as dt
import json
import math
import sqlite3
import time
from contextlib import closing, ExitStack
from hashlib import sha256
from pathlib import Path

from comparison_results import compatible, pair_reason, spectral_variant
from foundation import digest, owned, read_json, sha
from material_response import INSIDE, SOLAR, TEMP
from result_timeline import registered_source, require, source
from storage_management import safe_child

def registered_input(root, ref):
    require(isinstance(ref,dict) and set(ref)=={'batch','index','sha256'} and isinstance(ref.get('batch'),str) and type(ref.get('index')) is int,
            '请选择已登记的材料结果。')
    batch,index=ref['batch'],ref['index']
    job,raw,_,_,_,_,_,token=registered_source(root,batch,index,time.monotonic()+30)
    require(ref.get('sha256')==job['result_sha256'], '结果登记已更新，请重新读取批次。')
    queue=safe_child(root,Path(root)/'data/execution/queue.sqlite')
    with closing(sqlite3.connect(queue.as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT plan,checksum FROM batches WHERE id=?',(batch,)).fetchone()
    require(row, '找不到材料响应的计算批次。')
    plan=json.loads(row[0])
    folder=owned(Path(root)/'data/execution/reviews'/plan['id'],root)
    require(sha(folder/'plan.json')==row[1] and read_json(folder/'plan.json')==plan,'原计算清单校验不一致。')
    record=read_json(folder/'record.json')
    require(digest(record)==plan['record_sha256'],'原材料方案版本校验不一致。')
    case=next((c for c in plan['cases'] if c['index']==index),None)
    require(case and all(raw[k]==case[k] for k in ('identity','period','step_minutes','site_id','mode')),
            '结果与所选地点、时段或模型不一致。')
    return folder,case,record,plan,job,raw,token


def frozen_model(folder,case):
    model=owned(folder/case['model_file'],folder)
    payload=model.read_bytes()
    require(sha256(payload).hexdigest()==case['model_sha256'],'原算例的模型文件校验不一致。')
    return json.loads(payload)


def response_floor_plan(root,ref):
    from building_geometry import build
    folder,case,record,_,_,_,_=registered_input(root,ref)
    geometry=build(frozen_model(folder,case))
    return dict(geometry,model_sha256=case['model_sha256'],building=record['factors']['building']['name'])


def frozen_case(root, ref, general=False):
    folder,case,record,plan,job,raw,token=registered_input(root,ref)
    kind=spectral_variant(record)
    if general:
        from wall_observations import walls as model_walls
        walls=list(model_walls(frozen_model(folder,case)))
    else:
        require(kind and raw.get('output_contract')=='timeseries_timestep_v1',
                '该算例没有保存辐射材料逐步响应。')
        m=record['factors']['materials']
        walls=[w for a in m['applications'] if a['material_id']==m['definitions'][0]['id'] for w in a['target_ids']]
    return dict(ref=ref,record=record,case=case,raw=dict(raw,status=job['status'],weather_sha256=case['dependencies'][case['weather']]),
                token=token,version=plan['record_sha256'],walls=walls,variant=kind,folder=folder,bookmark=plan.get('observation_followup'))


def step_series(db,env,days,step,key,name,unit,frequency='Zone Timestep'):
    ids=db.execute("""SELECT ReportDataDictionaryIndex,Units FROM ReportDataDictionary
        WHERE ReportingFrequency=? AND KeyValue=? COLLATE NOCASE AND Name=? COLLATE NOCASE""",(frequency,key,name)).fetchall()
    require(len(ids)==1 and ids[0][1]==unit,key+' 的逐步变量缺失、重复或单位有误：'+name)
    by_date={(d.month,d.day):i for i,d in enumerate(days)}
    samples={}
    for m,d,h,minute,interval,value in db.execute("""SELECT t.Month,t.Day,t.Hour,t.Minute,t.Interval,r.Value
                FROM ReportData r JOIN Time t USING(TimeIndex)
                WHERE r.ReportDataDictionaryIndex=? AND t.EnvironmentPeriodIndex=? AND t.IntervalType=?
                AND coalesce(t.WarmupFlag,0)=0 AND t.Month*100+t.Day BETWEEN ? AND ?""",
                (ids[0][0],env,1 if frequency=='Hourly' else -1,days[0].month*100+days[0].day,days[-1].month*100+days[-1].day)):
        end=h*60+minute
        require((m,d) in by_date and interval==step and step<=end<=1440 and end%step==0,
                '材料响应输出的日期或区间不符。')
        slot=by_date[m,d]*1440+end-step
        require(slot not in samples and value is not None and math.isfinite(value),'逐步数据含有重复时刻或无效数值。')
        samples[slot]=value
    expected=range(0,1440*len(days),step)
    require(len(samples)==len(expected) and all(t in samples for t in expected),'材料响应时间轴有缺项：'+name)
    return [samples[t] for t in expected]


def read_values(db, env, wall, kind, days, step):
    fields={'surface':(wall,TEMP,'C'), 'sky':('EMS','WB Window Sky Loss '+wall,'W/m2'),
            'inward':(wall,INSIDE,'W/m2'), 'incident':(wall,SOLAR,'W/m2'),
            'boundary_solar':('EMS','WB Incident Solar '+wall,'W/m2')}
    if kind=='covered':
        fields['cover']=('EMS','WB Cover Temperature '+wall,'C')
        fields['residual']=('EMS','WB Cover Balance '+wall,'W/m2')
    values={metric:step_series(db,env,days,step,*args) for metric,args in fields.items()}
    solar=values.pop('incident')
    require(all(abs(a-b)<=1e-5 for a,b in zip(solar,values.pop('boundary_solar'))),
            wall+' 的辐射边界日照与该墙实际日照不符，请核对所选结果版本。')
    if kind=='covered':
        require(all(abs(v)<=.01 for v in values.pop('residual')),wall+' 的 PE 覆盖层热平衡未通过核对。')
    return values


def room_location(side,wall):
    from building_geometry import build
    try:
        model=frozen_model(side['folder'],side['case'])
        zone=model['BuildingSurface:Detailed'][wall]['zone_name']
        require(zone in model['Zone'],'墙面所属热区未在模型中登记。')
    except (KeyError,OSError,ValueError) as exc:
        return dict(zone=None,floor=None,note='无法从原模型核对墙面所属房间：'+str(exc)),{}
    location=dict(zone=zone,floor=None)
    try:
        floors={r['zone']:r['floor']+1 for r in build(model)['rooms']}
        location['floor']=floors[zone]
    except (KeyError,ValueError):
        location['note']='原模型未能按地面标高分层。'
    return location,model


def zone_ideal_systems(model,zone):
    lists={name.casefold():group for name,group in model.get('ZoneHVAC:EquipmentList',{}).items()}
    systems=set()
    for conn in model.get('ZoneHVAC:EquipmentConnections',{}).values():
        if conn.get('zone_name','').casefold()!=zone.casefold():continue
        group=lists.get(conn['zone_conditioning_equipment_list_name'].casefold(),{})
        for obj in group.get('equipment',[]):
            if obj.get('zone_equipment_object_type','').casefold()=='zonehvac:idealloadsairsystem':
                systems.add(obj['zone_equipment_name'].casefold())
    return sorted(systems)


def room_series(db,env,days,step,location,model,operation):
    zone=location['zone']
    values,notes={},[]
    if not zone:return values,[location['note']]
    def read(field,keys,name,unit):
        try:
            series=[step_series(db,env,days,step,key,name,unit) for key in keys]
            if field=='state':
                require(all(v in (0,1,2) for v in series[0]),'控制记录含无法识别的状态。')
                values[field]=[int(v) for v in series[0]]
            elif unit=='J':
                values[field]=[sum(interval)/(60*step*1000) for interval in zip(*series)]
            else:
                values[field]=series[0]
        except ValueError as exc:
            notes.append(str(exc))
    read('air',[zone],'Zone Mean Air Temperature','C')
    if operation=='natural':
        notes.append('自然室温算例。')
        return values,notes
    mode_name=zone+' Control Mode'
    if mode_name.casefold() in {n.casefold() for n in model.get('EnergyManagementSystem:OutputVariable',{})}:
        read('state',['EMS'],mode_name,'')
    else:
        notes.append('原模型未登记该房间的供暖、制冷及停机状态。')
    systems=zone_ideal_systems(model,zone)
    if systems:
        for k,field in [('Heating','heating'),('Cooling','cooling')]:
            read(field,systems,'Zone Ideal Loads Zone Sensible '+k+' Energy','J')
    else:
        notes.append('该房间未关联理想空调系统。')
    return values,notes


def response(root, body):
    refs=body.get('results')
    require(isinstance(refs,list) and len(refs) in (1,2),'请选择一个结果或一组同墙对照。')
    general=body.get('general') is True
    sides=[frozen_case(root,r,general) for r in refs]
    first=sides[0]
    if len(sides)==2:
        second=sides[1]
        require(first['case']['identity']!=second['case']['identity'],'请选择两个不同的结果。')
        a,b=first['record'],second['record']
        require(a['factors']['building']==b['factors']['building'] and a['provenance'].get('snapshot_id')==b['provenance'].get('snapshot_id'),
                '同墙对照需要相同的建筑定义与几何来源。')
        mode=first['case']['mode']
        issues=compatible(a,b,mode,'temperature' if mode=='natural' else 'total')
        require(not issues,'；'.join(issues))
        require(first['case']['site_id']==second['case']['site_id'],'同墙对照需要相同地点。')
        reason=pair_reason(first['raw'],second['raw'])
        require(not reason,reason)
    walls=sorted(set.intersection(*(set(s['walls']) for s in sides)))
    require(walls,'所选结果没有共同可查看的外墙。')
    token=digest([[s['token'],s['version']] for s in sides])
    if 'known' in body and body['known']==token and 'wall' not in body:
        return dict(unchanged=True,view_token=token)
    period=first['case']['period']
    step=first['case']['step_minutes']
    out=dict(view_token=token,walls=walls,period=period,step_minutes=step,city=first['raw']['city'],
             sides=[dict(name=s['record']['name'],variant=s['variant'],status=s['raw']['status'],**s['ref']) for s in sides])
    if 'wall' not in body:
        if general:
            from wall_observations import METRICS
            from wall_switches import controlled_walls
            frequencies=set()
            for side,info in zip(sides,out['sides']):
                info.update(switch_walls=sorted(controlled_walls(side['record'])),source_token=side['token'])
                with source(root,side['ref']['batch'],side['ref']['index']) as (db,_,env,receipt):
                    require(receipt['view_token']==side['token'],'读取期间结果来源已更新。')
                    if len(sides)==1 and side['bookmark']:
                        from observation_followup import probes,verify_series
                        bookmark=side['bookmark']
                        specs=probes(frozen_model(side['folder'],side['case']),bookmark['wall'],bookmark['zone'],side['case']['mode'])
                        try:
                            require(side['raw']['status'] in ('passed','reused'),'补录批次仍待复核。')
                            require(verify_series(db,env,bookmark['fields'],specs,period,step),'所选补录测点缺少完整的逐步记录。')
                            out['bookmark']=bookmark
                        except ValueError as error:
                            out['bookmark_issue']=str(error)
                    frequencies.update(r[0] for r in db.execute(
                        "SELECT DISTINCT ReportingFrequency FROM ReportDataDictionary WHERE Name IN (?,?,?,?) AND ReportingFrequency IN ('Zone Timestep','Hourly')",
                        [name for name,_ in METRICS.values()]))
            out['frequencies']=[f for f in ('Zone Timestep','Hourly') if f in frequencies]
            out['selected_walls']=sorted({p['wall'] for s in sides for p in s['case'].get('wall_observations',{}).get('points',[]) if p['wall'] in walls})
        return out
    require(body.get('view_token')==token,'结果来源已变化，请重新打开材料响应。')
    wall=body['wall']
    require(wall in walls,'请选择两侧实际铺设范围内的墙。')
    start,end=dt.date(2025,*period[:2]),dt.date(2025,*period[2:])
    if body.get('date')!='all':
        try:
            date=dt.date.fromisoformat('2025-'+body['date'])
        except (TypeError,KeyError,ValueError) as exc:
            raise ValueError('请选择有效日期。') from exc
        require(start<=date<=end,'日期超出算例时段。')
        start=end=date
    count=(end-start).days+1
    require(1<=count<=7,'超过七天的逐墙响应请按日期读取。')
    days=[start+dt.timedelta(days=i) for i in range(count)]
    frequency=body.get('frequency','Zone Timestep')
    if general:
        require(frequency in ('Zone Timestep','Hourly'),'不支持此测点保存频率。')
        if frequency=='Hourly':step=60
        out['step_minutes']=step
    with ExitStack() as readers:
        for info,s in zip(out['sides'],sides):
            location,model=room_location(s,wall)
            info['room']=location
            db,_,env,receipt=readers.enter_context(source(root,s['ref']['batch'],s['ref']['index']))
            require(receipt['view_token']==s['token'],'读取期间结果来源已更新。')
            if general:
                from wall_observations import METRICS
                info['values']={}
                info['notes']=[]
                info['saved_frequencies']={}
                for field,(name,unit) in METRICS.items():
                    key=location['zone'] if field=='air' else wall
                    frequencies=[row[0] for row in db.execute(
                        'SELECT DISTINCT ReportingFrequency FROM ReportDataDictionary WHERE KeyValue=? COLLATE NOCASE AND Name=? COLLATE NOCASE',
                        (key,name))] if key else None
                    info['saved_frequencies'][field]=frequencies
                    if not frequencies or frequency not in frequencies:
                        continue
                    info['values'][field]=step_series(db,env,days,step,key,name,unit,frequency)
            elif body.get('room_controls') is True:
                info['values'],info['notes']=room_series(db,env,days,step,location,model,s['case']['mode'])
            else:
                info['values']=read_values(db,env,wall,s['variant'],days,step)
    out.update(wall=wall,dates=[d.strftime('%m-%d') for d in days],points=count*1440//step)
    return out
