"""Independent result checks for controlled and natural short/annual runs."""
import calendar
import datetime as dt
import math
from pathlib import Path
import re
import sqlite3
from contextlib import closing
from foundation import read_json,sha,now

HEAT='Zone Ideal Loads Zone Sensible Heating Energy'
COOL='Zone Ideal Loads Zone Sensible Cooling Energy'

def require(condition,message):
    if not condition:raise ValueError(message)

def close(a,b):
    require(math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-7),f'汇总不能闭合：{a} / {b}')

def verify(folder,case,returncode,elapsed):
    folder=Path(folder);out=folder/'run';model=read_json(folder/'model.epJSON')
    contract=case.get('output_contract','monthly_period_v1')
    require(contract in ('monthly_period_v1','daily_sensible_reference_v1'),'结果输出类型未知。')
    daily=None
    if contract=='daily_sensible_reference_v1':
        require(case['mode']=='controlled' and case['period']==[1,1,12,31] and not case.get('validation_trace'),'逐日参考仅支持全年温控精简输出。')
    require(returncode==0,'计算引擎未正常退出。')
    logs=[(out/n).read_text(encoding='utf-8',errors='replace') for n in ('eplusout.err','eplusout.end')]
    require(all('EnergyPlus Completed Successfully' in s for s in logs),'缺少正常结束记录。')
    require(not re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',logs[0]),'引擎报告严重错误。')
    warnings=re.findall(r'\*\* Warning \*\* (.*)',logs[0])
    pending=[s for s in warnings if not any(x in s for x in ('CheckUsedConstructions:','autocalculated deep ground depth'))]
    start=dt.date(2025,*case['period'][:2]);end=dt.date(2025,*case['period'][2:]);days=(end-start).days+1
    expected={}
    for i in range(days):
        date=start+dt.timedelta(days=i);expected[date.month]=expected.get(date.month,0)+1440
    with closing(sqlite3.connect((out/'eplusout.sql').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        def rows(sql,args=()):return [dict(x) for x in db.execute(sql,args)]
        require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','结果数据库完整性检查失败。')
        sim=rows('select * from Simulations');require(len(sim)==1 and sim[0]['NumTimestepsPerHour']==60//case['step_minutes'],'求解步长不符。')
        env=rows('select * from EnvironmentPeriods');require(len(env)==1 and env[0]['EnvironmentType']==3,'存在非预期的计算环境。')
        ts=rows('select * from Time order by TimeIndex');period=[t for t in ts if t['IntervalType']==4];months=[t for t in ts if t['IntervalType']==3]
        require(len(period)==1 and period[0]['Interval']==days*1440 and period[0]['SimulationDays']==days,'计算时段未完整覆盖。')
        # EnergyPlus writes the FULL calendar-month Interval even for partial months.
        # SimulationDays records actual elapsed days; RunPeriod gives actual minutes.
        require(len(months)==len(expected) and {t['Month'] for t in months}==set(expected),'分月输出时段不符。')
        cumulative=0
        for t in months:
            cumulative+=expected[t['Month']]//1440
            require(t['SimulationDays']==cumulative and t['Interval']==calendar.monthrange(2025,t['Month'])[1]*1440,'分月累计模拟天数不符。')
        trace=[t for t in ts if t['IntervalType'] not in ((2,3,4) if contract=='daily_sensible_reference_v1' else (3,4))]
        if case.get('validation_trace'):
            require(len(trace)==days*24*60//case['step_minutes'] and all(t['Interval']==case['step_minutes'] for t in trace),'验证轨迹的求解步数不符。')
        else:require(not trace,'存在非预期的详细时序输出。')
        data=rows('select d.*,r.Value,t.Month,t.Interval,e.MinValue,e.MaxValue from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex) left join ReportExtendedData e using(ReportDataIndex)')
        require(all(math.isfinite(x['Value']) for x in data),'结果包含非有限数值。')
        def variable(name,freq):return [x for x in data if x['Name']==name and x['ReportingFrequency']==freq]
        def unique(rr,keys,label):require(len(rr)==len(keys) and {x['KeyValue'].upper() for x in rr}==keys,label+'缺失或重复。')
        zonekeys={k.upper() for k in model['Zone']}
        temps=variable('Zone Mean Air Temperature','Run Period');unique(temps,zonekeys,'房间室温')
        require(all(x['Units']=='C' and x['MinValue'] is not None and x['MaxValue'] is not None and math.isfinite(x['MinValue']) and math.isfinite(x['MaxValue']) for x in temps),'室温极值或单位缺失。')
        monthly=[];loads=None;rooms=[]
        if case['mode']=='controlled':
            keys={k.upper() for k in model.get('ZoneHVAC:IdealLoadsAirSystem',{})};require(bool(keys),'温控模型缺少理想负荷系统。')
            loads={}
            for kind,var in [('heating',HEAT),('cooling',COOL)]:
                rr=variable(var,'Run Period');unique(rr,keys,var)
                require(all(x['Units']=='J' and x['Type']=='Sum' and x['Value']>=0 for x in rr),'负荷单位、类型或符号不符。')
                loads[kind+'_kWh']=sum(x['Value'] for x in rr)/3.6e6
                mm=variable(var,'Monthly')
                for month in expected:
                    values=[x for x in mm if x['Month']==month];unique(values,keys,var+'分月')
                    require(all(x['Value']>=0 and x['Units']=='J' for x in values),'分月负荷不符。')
                for x in rr:
                    parts=[y['Value'] for y in mm if y['KeyValue']==x['KeyValue']];close(x['Value'],sum(parts))
                    rooms.append(dict(system=x['KeyValue'],kind=kind,kWh=x['Value']/3.6e6))
            loads['total_kWh']=loads['heating_kWh']+loads['cooling_kWh']
            for month in expected:
                v={kind+'_kWh':sum(x['Value'] for x in variable(var,'Monthly') if x['Month']==month)/3.6e6 for kind,var in [('heating',HEAT),('cooling',COOL)]}
                monthly.append(dict(month=month,**v,total_kWh=sum(v.values())))
        for x in temps:
            parts=[y for y in variable('Zone Mean Air Temperature','Monthly') if y['KeyValue']==x['KeyValue']]
            require(len(parts)==len(expected),'分月室温不完整。')
            close(x['Value'],sum(y['Value']*expected[y['Month']] for y in parts)/(days*1440))
        extrema=dict(min_C=min(x['MinValue'] for x in temps),max_C=max(x['MaxValue'] for x in temps))
        if extrema['min_C'] < -80 or extrema['max_C']>70:pending.append('室温超出常见范围，需要复核。')
        # Keep original SQL flags. This engine build has known false flags despite complete output.
        flags={k:sim[0][k] for k in ('Completed','CompletedSuccessfully')}
    if contract=='daily_sensible_reference_v1':
        from daily_reference import verify_sql,daily_csv
        daily=verify_sql(out/'eplusout.sql',model,case['step_minutes'])
        for key,value in daily['totals'].items():close(value,loads[key])
        (folder/'daily-loads.csv').write_text(daily_csv(daily),encoding='utf-8-sig',newline='')
    artifacts={str(folder/'model.epJSON'):sha(folder/'model.epJSON')}
    artifacts.update({str(out/n):sha(out/n) for n in ('eplusout.sql','eplusout.err','eplusout.end')})
    if daily:artifacts[str(folder/'daily-loads.csv')]=sha(folder/'daily-loads.csv')
    result=dict(created=now(),status='review' if pending else 'passed',site_id=case['site_id'],city=case['city'],mode=case['mode'],period=case['period'],days=days,step_minutes=case['step_minutes'],
        loads=loads,monthly=monthly,rooms=rooms,temperatures=[dict(zone=x['KeyValue'],mean_C=x['Value'],min_C=x['MinValue'],max_C=x['MaxValue']) for x in temps],temperature_extrema=extrema,
        warnings=warnings,pending_warnings=pending,elapsed_seconds=elapsed,output_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
        checks=dict(process_exit_zero=True,err_end_success=True,sqlite_quick_check='ok',full_period=True,monthly_reconciliation=True,sqlite_completion_flags=flags,
            completion_basis='Process + end/err + independent full-period coverage + monthly reconciliation; SQL flags retained unmodified.'),artifacts=artifacts)
    if daily:result.update(output_contract=contract,daily_reference=daily)
    return result

def verify_artifacts(result):
    for path,checksum in result['artifacts'].items():
        if sha(path)!=checksum:raise ValueError('已完成结果文件变化，不能复用：'+path)
    return result
