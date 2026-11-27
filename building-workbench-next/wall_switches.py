"""Locate recorded material transitions and compare adjacent zone timesteps."""
import datetime as dt
import math

from result_timeline import require, source
from spectral_response import frozen_model, registered_input, zone_ideal_systems
from wall_observations import METRICS, walls


def controlled_walls(record):
    apps={a['id']:set(a['target_ids']) for a in record['factors']['materials']['applications']}
    by_wall={}
    for c in record['factors']['condition']['controls']:
        if (c['channel'],c['mode']) not in (('thermal','feedback'),('orientation','calendar')):
            continue
        for wall in apps.get(c['application_id'],set()).intersection(c['target_ids']):
            by_wall.setdefault(wall,set()).add(c['channel'])
    return by_wall


def control_names(model,wall,channels):
    outputs={k.casefold():k for k in model.get('EnergyManagementSystem:OutputVariable',{})}
    choices={'orientation':('Face','NX_SC_FaceOutput','NX_FiveStorey_Flip_FaceOutput'),
             'thermal':('State','NX_SC_StackStateOutput','NX_SC_StateOutput','NX_Fb_StateOutput')}
    names={}
    for channel in sorted(channels):
        tag,*shared=choices[channel]
        local=outputs.get(('NX '+wall+' '+tag).casefold())
        matched=[outputs[n.casefold()] for n in shared if n.casefold() in outputs]
        require(local or len(matched)<=1,'存在多项控制输出，无法唯一对应所选墙。')
        names[channel]=local or next(iter(matched),None)
    return names


def outputs(db,key,name,unit,aggregation):
    found={}
    for idx,freq,u,kind in db.execute('''SELECT ReportDataDictionaryIndex,ReportingFrequency,Units,Type
          FROM ReportDataDictionary WHERE KeyValue=? COLLATE NOCASE AND Name=? COLLATE NOCASE AND IsMeter=0''',(key,name)):
        require(freq not in found and (u or '')==unit and kind==aggregation,'输出登记重复或单位、统计方式有误：'+name)
        found[freq]=idx
    return found


def scan(db,env,start,days,step,signals):
    events={}
    summaries={}
    for channel,ids in signals.items():
        if 'Zone Timestep' not in ids:
            freq=next((f for f in ('Daily','Monthly','Run Period') if f in ids),None)
            values={}
            if freq:
                for m,d,v in db.execute('''SELECT t.Month,t.Day,r.Value FROM ReportData r JOIN Time t USING(TimeIndex)
                    WHERE r.ReportDataDictionaryIndex=? AND t.EnvironmentPeriodIndex=? AND coalesce(t.WarmupFlag,0)=0''',(ids[freq],env)):
                    key=f'{m:02d}-{d:02d}' if freq=='Daily' else f'{m:02d}' if freq=='Monthly' else 'period'
                    require(key not in values and v is not None and 0<=v<=1,'控制占比记录重复或数值无效。')
                    values[key]=v
            summaries[channel]=dict(frequency=freq,values=values)
            continue
        previous=None
        offset=0
        dates=[start+dt.timedelta(days=i) for i in range(days)]
        for day,m,d,h,minute,interval,value in db.execute('''SELECT t.SimulationDays,t.Month,t.Day,t.Hour,t.Minute,t.Interval,r.Value
            FROM ReportData r JOIN Time t USING(TimeIndex) WHERE r.ReportDataDictionaryIndex=? AND t.EnvironmentPeriodIndex=?
            AND t.IntervalType IN (-1,0) AND coalesce(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex''',(ids['Zone Timestep'],env)):
            i=offset//1440
            require(i<days and day==i+1 and (m,d)==(dates[i].month,dates[i].day) and interval==step
                    and h*60+minute==offset%1440+step and value in (0,1),'逐步控制记录缺失、重复或含非离散状态，无法定位切换。')
            if previous is not None and value!=previous:
                events.setdefault(offset,{})[channel]=[int(previous),int(value)]
            previous=value
            offset+=step
        require(offset==days*1440,'逐步控制记录没有覆盖完整计算时段。')
    return sorted(events.items()),summaries


def neighboring_times(db,env,offset,step,start):
    times=[]
    for minute in (offset-step,offset):
        days,end=divmod(minute,1440)
        date=start+dt.timedelta(days=days)
        matches=list(db.execute('''SELECT TimeIndex FROM Time WHERE EnvironmentPeriodIndex=? AND coalesce(WarmupFlag,0)=0
            AND IntervalType IN (-1,0) AND SimulationDays=? AND Month=? AND Day=? AND Hour*60+Minute=? AND Interval=?''',
            (env,days+1,date.month,date.day,end+step,step)))
        # Some output files carry more than one time record at a boundary. Match via each variable.
        require(matches,'切换前后的原始时间记录缺失。')
        times.append([r[0] for r in matches])
    return times


def pair(db,idx,times):
    result=[]
    for ticks in times:
        slots=','.join('?' for _ in ticks)
        rows=list(db.execute(f'SELECT Value FROM ReportData WHERE ReportDataDictionaryIndex=? AND TimeIndex IN ({slots})',(idx,*ticks)))
        require(len(rows)==1 and rows[0][0] is not None and math.isfinite(rows[0][0]),'切换前后的逐步读数缺失、重复或无效。')
        result.append(rows[0][0])
    return result


def observations(db,times,model,wall,zone,case,step,layer):
    rows=[]
    def add(label,unit,name,keys,quantity='Avg',scale=1,unavailable=None,field=None):
        entries=[outputs(db,key,name,unit,quantity) for key in keys]
        row=dict(label=label,unit='kW' if unit=='J' else {'C':'°C','W/m2':'W/m²'}.get(unit,unit))
        if field:
            row.update(field=field,requestable=bool(keys))
        if entries and all('Zone Timestep' in e for e in entries):
            readings=[pair(db,e['Zone Timestep'],times) for e in entries]
            row['values']=[sum(v)*scale for v in zip(*readings)]
        else:
            row['note']=unavailable if not entries else ('仅有汇总' if all(e and set(e)<= {'Monthly','Daily','Run Period'} for e in entries) else '未保存对应逐步值')
        rows.append(row)
    for s in case.get('stack_response',[]):
        if s['wall']==wall and (layer is None or s['layer']==layer):
            for key,label in [('outside','外侧'),('inside','内侧')]:
                add(s['name']+' · 层'+label+'温度','C','CondFD Surface Temperature Node '+str(s[key]),[wall])
    add('墙内表面导热','W/m2',METRICS['inward'][0],[wall],field='inward')
    add('所属房间室温','C',METRICS['air'][0],[zone],field='air')
    systems=zone_ideal_systems(model,zone) if case['mode']!='natural' else []
    for mode,label in [('Heating','房间供暖'),('Cooling','房间制冷')]:
        add(label,'J','Zone Ideal Loads Zone Sensible '+mode+' Energy',systems,'Sum',1/(step*60000),
            '自然室温工况' if case['mode']=='natural' else '房间未关联理想空调系统',field=mode.lower())
    return rows


def read(root,body):
    ref=body['result']; wall=body['wall']
    folder,case,record,_,_,_,token=registered_input(root,ref)
    require(body.get('source_token')==token,'结果来源已变化，请重新打开测点。')
    model=frozen_model(folder,case)
    zone=walls(model).get(wall)
    channels=controlled_walls(record).get(wall)
    require(zone and channels,'所选外墙没有绑定光学切换或热阻反馈控制。')
    names=control_names(model,wall,channels)
    start=dt.date(2025,*case['period'][:2]);days=(dt.date(2025,*case['period'][2:])-start).days+1
    step=case['step_minutes']
    with source(root,ref['batch'],ref['index']) as (db,_,env,receipt):
        require(receipt['view_token']==token,'读取期间结果来源已更新。')
        signals={ch:outputs(db,'EMS',name,'','Avg') if name else {} for ch,name in names.items()}
        out=dict(source_token=token,wall=wall,zone=zone,step=step,period=case['period'])
        if 'offset' not in body:
            out['events'],out['summaries']=scan(db,env,start,days,step,signals)
            out['exact']=[ch for ch,ids in signals.items() if 'Zone Timestep' in ids]
        else:
            minute=body['offset']
            require(type(minute) is int and step<=minute<days*1440 and minute%step==0,'请选择实际切换时刻。')
            times=neighboring_times(db,env,minute,step,start)
            states={ch:pair(db,ids['Zone Timestep'],times) for ch,ids in signals.items() if 'Zone Timestep' in ids}
            require(all(v in (0,1) for vs in states.values() for v in vs) and any(a!=b for a,b in states.values()),'所选时刻没有已记录的状态切换。')
            out.update(offset=minute,states=states,rows=observations(db,times,model,wall,zone,case,step,body.get('layer')))
    return out
