"""Optional outputs bound to physical walls and zones in the generated model."""
from datetime import date

METRICS = {
    'outside': ('Surface Outside Face Temperature', 'C'),
    'inside': ('Surface Inside Face Temperature', 'C'),
    'inward': ('Surface Inside Face Conduction Heat Transfer Rate per Area', 'W/m2'),
    'air': ('Zone Mean Air Temperature', 'C'),
}
FREQUENCIES = {'Hourly': ('Hourly', 1), 'Timestep': ('Zone Timestep', -1)}


def walls(model):
    return {name: row['zone_name'] for name,row in model.get('BuildingSurface:Detailed',{}).items()
            if row.get('surface_type','').casefold()=='wall' and row.get('outside_boundary_condition','').casefold()=='outdoors'}


def attach(model,record,contract):
    config=record.get('execution',{}).get('wall_observations')
    if not config or not config.get('points'):return None
    if config.get('building_id')!=record['factors']['building']['id']:
        raise ValueError('测点属于另一栋建筑，请移除旧测点并在当前建筑上重新选择。')
    frequency=config.get('frequency')
    if frequency not in FREQUENCIES or contract=='daily_sensible_reference_v1':
        raise ValueError('墙面测点需要逐时或逐步输出；逐日参考另用原墙方案。')
    period=record['factors']['scope']['period']
    if frequency=='Timestep' and (date(2025,*period[2:])-date(2025,*period[:2])).days>=31:
        raise ValueError('逐步测点适用于连续 31 天以内，较长时段请选择逐时。')
    zones=walls(model)
    points=[]
    requested=set()
    for point in config['points']:
        wall=point['wall']
        fields=point['fields']
        if wall not in zones or not isinstance(fields,list) or not fields or any(f not in METRICS for f in fields):
            raise ValueError('测点的墙面或观测量与当前建筑不符，请在计算安排里重新选择。')
        if any(p['wall']==wall for p in points) or len(set(fields))!=len(fields):
            raise ValueError('同一墙面或观测量已重复登记。')
        zone=zones[wall]
        if point.get('zone') and point['zone']!=zone:
            raise ValueError(wall+' 的所属房间已变化，请重新选择测点。')
        points.append(dict(wall=wall,zone=zone,fields=fields))
        for field in fields:
            requested.add((zone if field=='air' else wall,METRICS[field][0]))
    outputs=model.setdefault('Output:Variable',{})
    existing={(r.get('key_value','*').upper(),r['variable_name'].upper(),r['reporting_frequency'].upper())
              for r in outputs.values()}
    for key,name in sorted(requested):
        for freq in [frequency,'Monthly','RunPeriod']:
            tail=(name.upper(),freq.upper())
            if (key.upper(),*tail) in existing or ('*',*tail) in existing:continue
            output='WB_Observation_'+str(len(outputs))
            while output in outputs:output+='_'
            outputs[output]=dict(key_value=key,variable_name=name,reporting_frequency=freq)
            existing.add((key.upper(),*tail))
    return dict(frequency=frequency,points=points)


def verify(db,config,step,days):
    freq,interval_type=FREQUENCIES[config['frequency']]
    minutes=step if interval_type==-1 else 60
    expected=days*1440//minutes
    seen=set()
    for point in config['points']:
        for field in point['fields']:
            key=point['zone'] if field=='air' else point['wall']
            if (key,field) in seen:continue
            seen.add((key,field))
            name,unit=METRICS[field]
            matches=db.execute('SELECT ReportDataDictionaryIndex,Units,Type FROM ReportDataDictionary WHERE KeyValue=? COLLATE NOCASE AND Name=? COLLATE NOCASE AND ReportingFrequency=?',(key,name,freq)).fetchall()
            if len(matches)!=1 or tuple(matches[0])[1:]!=(unit,'Avg'):
                raise ValueError('测点缺少对应输出或单位不符：'+key+' '+name)
            row=db.execute('''SELECT COUNT(*),COUNT(DISTINCT t.TimeIndex),COUNT(DISTINCT t.SimulationDays*1440+t.Hour*60+t.Minute),
                MIN(t.SimulationDays),MAX(t.SimulationDays),MIN(t.Interval),MAX(t.Interval),
                SUM(CASE WHEN r.Value IS NULL OR ABS(r.Value)>1e300 OR (t.Hour*60+t.Minute)%? <> 0
                OR t.Hour*60+t.Minute NOT BETWEEN ? AND 1440 THEN 1 ELSE 0 END)
                FROM ReportData r JOIN Time t USING(TimeIndex) WHERE r.ReportDataDictionaryIndex=? AND t.IntervalType=?
                AND COALESCE(t.WarmupFlag,0)=0''',(minutes,minutes,matches[0][0],interval_type)).fetchone()
            if tuple(row)!=(expected,expected,expected,1,days,minutes,minutes,0):
                raise ValueError('测点读数或时间轴不完整：'+key+' '+name)
