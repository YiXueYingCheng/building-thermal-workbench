"""Daily sensible-load output contract and read-only preparation.

Preparation never submits runs. The explicit daily output branch uses the same
queue and result checks as monthly_period_v1; data alone never accepts warnings.
"""
import calendar
import copy
import csv
import datetime as dt
import io
import math
from pathlib import Path
import sqlite3
from contextlib import closing
from foundation import ROOT, digest, now, sha
from execution_inputs import compact_model
from execution_results import HEAT, COOL
from reference_readiness import baseline, physical
from model_adapter import VerifiedReader, compile_case

CONTRACT = 'daily_sensible_reference_v1'
VARIABLES = {'heating_kWh': HEAT, 'cooling_kWh': COOL}
DATES = [dt.date(2025,1,1)+dt.timedelta(days=i) for i in range(365)]


def require(ok, message):
    if not ok: raise ValueError(message)


def record_key(record):
    # Browser JSON serializes 23.0 as 23; the saved execution snapshot stays raw.
    from calendar_library import stable_numbers
    return digest(stable_numbers(record))


def require_baseline(record):
    f=record['factors']
    require(record['provenance']['adapter'] in ('ordinary_building_v1','global_frozen_v011'),'该建筑来源尚未接通逐日参考计算。')
    require(f['scope']['period']==[1,1,12,31] and f['condition']['operation']['mode']=='controlled','逐日参考清单需要全年温控原构造方案。')
    require(not f['materials'].get('applications') and not f['materials'].get('legacy_construction_overrides') and not f['condition'].get('controls'),'请切换到原构造方案创建逐日参考清单；研究方案保持不变。')


def prepare_model(original):
    """Output-only extension of the current compact model; never mutate input."""
    require(bool(original.get('ZoneHVAC:IdealLoadsAirSystem')), '逐日冷热需求需要温控模型和理想负荷系统。')
    m = compact_model(original)
    for field, name in VARIABLES.items():
        m['Output:Variable']['NX_Daily_'+field] = dict(key_value='*',variable_name=name,reporting_frequency='Daily')
    require({k:v for k,v in m.items() if not k.startswith('Output')} ==
            {k:v for k,v in original.items() if not k.startswith('Output')}, '逐日准备改变了物理输入。')
    return m


def build(record, catalog, root=ROOT):
    """Compile only in memory, report exact output counts and source identities."""
    out = dict(checked_at=now(),contract=CONTRACT,record=dict(id=record['id'],revision=record['revision'],name=record['name'],sha256=record_key(record),identity_kind='canonical_numbers_v1'),
        period=record['factors']['scope']['period'],step_minutes=record['numerics']['step_minutes'],rows=[],issues=[],
        input_ready=False,execution_enabled=False,new_simulations=0,
        quantity='每日建筑显热供暖、制冷需求，单位 kWh；不是电耗。',
        preservation='沿用当前建筑基础构造、房间使用配置、温控启停、作息、气象、步长及原预热；参考副本移除研究材料和材料控制。',
        retention='保留现有月度/全年汇总，仅额外请求两项逐日冷热需求；核对后汇总为每地点 365 行。',
        storage_note='记录数量是新增输出规模，不是磁盘峰值估算；实际文件大小和运行峰值需首个样本实测。',
        can_freeze=False,freeze_issue='',next_step='可为已保存的全年温控原构造方案创建逐日参考清单，再到统一计算队列核对预算并明确提交。结果核验及警告复核通过后才列为可用参考；五层建筑翻面控制仍需独立适配。')
    try:require_baseline(record);out['can_freeze']=True
    except ValueError as exc:out['freeze_issue']=str(exc)
    try:
        require(out['period']==[1,1,12,31], '本轮只准备完整非闰参考年；当前局部时段保持，不自动扩大。')
        ref=baseline(record)
        require(not ref['factors']['materials'].get('legacy_construction_overrides'), '参考仍含旧研究构造覆盖，需明确原构造后再准备。')
    except ValueError as exc:
        out['issues'].append(str(exc));return out
    reader=VerifiedReader(catalog)
    for sid in ref['factors']['scope']['site_ids']:
        row=dict(site_id=sid,city=catalog['sites'][sid]['name'],ready=False,issues=[]);out['rows'].append(row)
        try:
            m,report=compile_case(ref,sid,catalog,reader,operation_mode='controlled')
            for path,h in ref['numerics']['engine_files'].items():reader.check(dict(path=path,sha256=h))
            weather=report['weather'];reader.check(weather)
            deps={x['path']:x['sha256'] for x in report['dependencies']}
            prepared=prepare_model(m);before=physical(m,deps,reader);after=physical(prepared,deps,reader)
            require(before==after,'准备前后的实际物理输入不同。')
            systems=len(m['ZoneHVAC:IdealLoadsAirSystem']);count=365*2*systems
            row.update(ready=True,conditioned_systems=systems,days=365,additional_daily_values=count,building_daily_rows=365,
                physical_sha256=before,prepared_model_sha256=digest(prepared),weather_sha256=weather.get('expected_sha256') or weather['sha256'],
                run_period=copy.deepcopy(next(iter(m['RunPeriod'].values()))),
                warmup=copy.deepcopy(m.get('Building',{})),physical_unchanged=True)
        except (ValueError,KeyError,TypeError,OSError) as exc:row['issues'].append(str(exc))
    try:reader.unchanged()
    except (ValueError,OSError) as exc:
        out['issues'].append(str(exc))
        for row in out['rows']:row['ready']=False;row['issues'].append('核对期间来源变化。')
    out['verified_sources']=list(reader.checked.values())
    out['engine_files']=ref['numerics'].get('engine_files',{})
    out['summary']=dict(sites=len(out['rows']),ready=sum(r['ready'] for r in out['rows']),
        additional_daily_values=sum(r.get('additional_daily_values',0) for r in out['rows'] if r['ready']),
        building_daily_rows=sum(r.get('building_daily_rows',0) for r in out['rows'] if r['ready']))
    out['input_ready']=bool(out['rows']) and all(r['ready'] for r in out['rows']) and not out['issues']
    return out


def verify_sql(path, model, step_minutes):
    """Independent SQL data checks only, not process/warning acceptance.

    Dates use the weather/model's local reporting day; no inferred UTC shift or
    monthly interpolation. Reject partial years, leap days, warmup and other envs.
    """
    require(step_minutes in (1,2,3,4,5,6,10,12,15,20,30,60),'求解步长不受支持。')
    require(len(model.get('RunPeriod',{}))==1,'参考运行时段不唯一。')
    period=next(iter(model['RunPeriod'].values()))
    require([period[k] for k in ('begin_month','begin_day_of_month','end_month','end_day_of_month')]==[1,1,12,31], '逐日参考需要完整年度。')
    require(len(model.get('Timestep',{}))==1 and next(iter(model['Timestep'].values()))['number_of_timesteps_per_hour']==60//step_minutes,'模型求解步长不符。')
    keys={k.upper() for k in model.get('ZoneHVAC:IdealLoadsAirSystem',{})}
    require(bool(keys),'缺少温控系统。')
    requests=[x for x in model.get('Output:Variable',{}).values() if x['reporting_frequency']=='Daily']
    require(len(requests)==2 and {x['variable_name'] for x in requests}==set(VARIABLES.values()) and
            all(x.get('key_value')=='*' and not x.get('schedule_name') for x in requests), '逐日输出请求不符合精简冷热需求协议。')
    path=Path(path).resolve();before=sha(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','结果数据库完整性检查失败。')
        def rows(sql):return [dict(r) for r in db.execute(sql)]
        sim=rows('SELECT * FROM Simulations');env=rows('SELECT * FROM EnvironmentPeriods')
        require(len(sim)==1 and sim[0]['NumTimestepsPerHour']==60//step_minutes,'结果求解步长不符。')
        require(len(env)==1 and env[0]['EnvironmentType']==3 and env[0]['SimulationIndex']==sim[0]['SimulationIndex'],'存在非预期计算环境。')
        times=rows('SELECT * FROM Time ORDER BY TimeIndex')
        # EnergyPlus summary Time rows use NULL rather than 0 for WarmupFlag.
        require(all(t['EnvironmentPeriodIndex']==env[0]['EnvironmentPeriodIndex'] and t['WarmupFlag'] in (None,0) for t in times),'混入预热或其他计算环境。')
        require(all(t['IntervalType'] in (2,3,4) for t in times),'混入非精简逐日/月度/年度输出。')
        daily=[t for t in times if t['IntervalType']==2];monthly=[t for t in times if t['IntervalType']==3];annual=[t for t in times if t['IntervalType']==4]
        require([(t['Month'],t['Day']) for t in daily]==[(d.month,d.day) for d in DATES],'逐日日期缺失、重复、乱序或包含闰日。')
        require(len({t['Year'] for t in daily})==1,'逐日结果跨多个年份。')
        require(all(t['Interval']==1440 and t['SimulationDays']==i+1 and t['Hour']==24 and t['Minute']==0 for i,t in enumerate(daily)),'逐日时段或日末时间不完整。')
        require([t['Month'] for t in monthly]==list(range(1,13)),'月度输出不完整。')
        require(all(t['Interval']==calendar.monthrange(2025,t['Month'])[1]*1440 and t['SimulationDays']==(dt.date(2025,t['Month'],calendar.monthrange(2025,t['Month'])[1])-DATES[0]).days+1 for t in monthly),'月度时段不完整。')
        require(len(annual)==1 and annual[0]['Interval']==365*1440 and annual[0]['SimulationDays']==365,'全年输出时段不完整。')
        dictionaries=rows('SELECT * FROM ReportDataDictionary');byid={d['ReportDataDictionaryIndex']:d for d in dictionaries}
        require(all(d['Name'] in VARIABLES.values() for d in dictionaries if d['ReportingFrequency']=='Daily'),'混入其他逐日变量。')
        selected=[d for d in dictionaries if d['Name'] in VARIABLES.values()]
        for name in VARIABLES.values():
            for freq in ('Daily','Monthly','Run Period'):
                rr=[d for d in selected if d['Name']==name and d['ReportingFrequency']==freq]
                require(len(rr)==len(keys) and {d['KeyValue'].upper() for d in rr}==keys,'冷热需求系统缺失或重复。')
        require(all(d['ReportingFrequency'] in ('Daily','Monthly','Run Period') and d['Units']=='J' and d['Type']=='Sum' and d['IsMeter']==0 and not d.get('ScheduleName') for d in selected),'冷热需求单位、类型、频率或作息筛选错误。')
        data=rows('SELECT ReportDataDictionaryIndex,TimeIndex,Value FROM ReportData')
        require(all(r['ReportDataDictionaryIndex'] in byid for r in data),'结果存在无字典记录。')
        tids={t['TimeIndex']:t for t in times};require(all(r['TimeIndex'] in tids for r in data),'结果存在无时间记录。')
        groups={d['ReportDataDictionaryIndex']:{} for d in selected}
        for r in data:
            idx=r['ReportDataDictionaryIndex']
            if idx not in groups:continue
            values=groups[idx];value=r['Value']
            require(r['TimeIndex'] not in values,'冷热需求存在重复结果记录。')
            require(isinstance(value,(int,float)) and math.isfinite(value) and value>=0,'冷热需求含空值、负数或非有限值。')
            values[r['TimeIndex']]=value/3.6e6
        series={};max_error=0.
        def same(a,b):
            nonlocal max_error
            max_error=max(max_error,abs(a-b))
            require(math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-6),'逐日、月度与全年冷热需求不能闭合。')
        for d in selected:
            group=groups[d['ReportDataDictionaryIndex']];timeline={'Daily':daily,'Monthly':monthly,'Run Period':annual}[d['ReportingFrequency']]
            require(set(group)=={t['TimeIndex'] for t in timeline},'冷热需求日期覆盖不全或混入其他频率。')
            series[(d['Name'],d['KeyValue'].upper(),d['ReportingFrequency'])]=[group[t['TimeIndex']] for t in timeline]
        result=[dict(month=d.month,day=d.day,day_of_year=i+1) for i,d in enumerate(DATES)];totals={};months=[dict(month=i) for i in range(1,13)]
        for field,name in VARIABLES.items():
            for key in keys:
                ds=series[(name,key,'Daily')];ms=series[(name,key,'Monthly')];ys=series[(name,key,'Run Period')]
                same(math.fsum(ds),ys[0]);same(math.fsum(ms),ys[0])
                for month in range(1,13):same(math.fsum(v for date,v in zip(DATES,ds) if date.month==month),ms[month-1])
            for i,row in enumerate(result):row[field]=math.fsum(series[(name,k,'Daily')][i] for k in keys)
            for i,row in enumerate(months):row[field]=math.fsum(series[(name,k,'Monthly')][i] for k in keys)
            totals[field]=math.fsum(series[(name,k,'Run Period')][0] for k in keys)
        flags={k:sim[0][k] for k in ('Completed','CompletedSuccessfully')}
    require(sha(path)==before,'读取期间结果文件变化。')
    return dict(contract=CONTRACT,data_checks_passed=True,scientifically_accepted=False,days=365,conditioned_systems=len(keys),
        daily=result,monthly=months,totals=totals,source_sql_sha256=before,model_sha256=digest(model),
        checks=dict(full_local_reporting_year=True,per_system_daily_monthly_annual_closure=True,max_closure_error_kWh=max_error,sqlite_completion_flags=flags),
        acceptance_note='仅核对数据；仍需绑定实际输入/气象/引擎，核对进程与日志、警告并登记接受依据。')


def daily_csv(report):
    require(report.get('contract')==CONTRACT and report.get('data_checks_passed') is True,'逐日数据尚未通过核对。')
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=['month','day','day_of_year',*VARIABLES]);writer.writeheader();writer.writerows(report['daily'])
    return stream.getvalue()
