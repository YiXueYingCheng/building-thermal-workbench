"""On-demand output inventory and bounded daily loads. No solver or source writes.

First slice: show actual output frequencies, then read one original system and
at most 31 days. Hourly/state linkage requires separately validated outputs.
"""
from contextlib import contextmanager, closing
from pathlib import Path
import datetime as dt
import calendar
import json, math, sqlite3, time
from foundation import now
from schedule_sharing import display_dictionary
from execution_results import HEAT, COOL
from result_availability import jobs, check_file, path_checked, stamp
from review_evidence import reviewed
from review_annotations import summary as review_summary

MAX_DAYS = 31
MAX_DICTIONARY = 10000
FREQUENCIES = {-1:'区域步', 0:'HVAC 系统步', 1:'逐小时', 2:'逐日', 3:'月度', 4:'整个计算时段'}


def require(ok, message):
    if not ok: raise ValueError(message)


@contextmanager
def source(root, batch, index, budget=30):
    """Verify the registered summary and its exact SQL; guard concurrent changes."""
    require(type(index) is int and index >= 0, '算例序号无效。')
    started=time.monotonic();deadline=started+budget
    job=next((j for j in jobs(root,batch) if j['idx']==index),None)
    require(job is not None and job.get('result'), '此算例尚无已登记结果。')
    summary,sw=check_file(root,job['result'],job.get('result_sha256'),deadline)
    require(summary['status']=='verified', '汇总未通过核对：'+summary.get('reason',''))
    require(summary['bytes']<=8*1024**2, '汇总超过本次读取范围。')
    raw=json.loads(sw[0].read_text('utf8'))
    review_info=reviewed(raw,root)
    require(raw.get('identity')==job['identity'], '结果身份与任务登记不一致。')
    require((job['status'] in ('passed','reused') and raw.get('status')=='passed') or
            (job['status']=='review' and raw.get('status')=='review'), '结果接受状态需要核对。')
    artifacts=raw.get('artifacts',{})
    require(isinstance(artifacts,dict), '原始资料清单无效。')
    paths=[p for p in artifacts if Path(p).name.lower()=='eplusout.sql']
    require(len(paths)==1, '结果未登记唯一的 SQL 明细；不能从汇总还原逐日或逐时数据。')
    sql,watch=check_file(root,paths[0],artifacts[paths[0]],deadline)
    require(sql['status']=='verified', '原始 SQL 明细不可用（缺失、已清理或未通过核对）。'+sql.get('reason','')+' 汇总不能还原明细。')
    p=path_checked(root,paths[0])
    def no_journal():
        require(not any(Path(str(p)+s).exists() for s in ('-wal','-journal')), '原始结果存在写入日志，暂不读取明细。')
    no_journal()
    verified=time.monotonic()
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
        db.execute('BEGIN')
        try:
            env=list(db.execute('SELECT EnvironmentPeriodIndex,EnvironmentType FROM EnvironmentPeriods'))
            require(len(env)==1 and env[0]['EnvironmentType']==3, '仅支持单一正式天气计算环境，不能混入设计日。')
            out=dict(batch=batch,index=index,identity=job['identity'],summary_sha256=job['result_sha256'],
                     sql_sha256=artifacts[paths[0]],city=raw.get('city'),period=raw.get('period'),
                     step_minutes=raw.get('step_minutes'),registered_status=job['status'],checked_at=now(),
                     acceptance_note=(review_summary(review_info) or review_info['label']+'；'+review_info['display_scope']) if review_info else ('警告待复核' if job['status']=='review' else '原结果自动校验通过'),
                     review_info=review_info,
                     note='只读已登记输出；不改变接受结论，不提交计算。日期按原模拟日历，未换算为当前年份或浏览器时区。')
            yield db,raw,env[0]['EnvironmentPeriodIndex'],out
            no_journal()
            require(all(stamp(path)==before for path,before in (sw,watch)), '读取期间结果资料发生变化，请重新读取。')
            require(next((j for j in jobs(root,batch) if j['idx']==index),None)==job, '读取期间任务登记变化，请重新读取。')
            out['timing']=dict(verification_seconds=round(verified-started,6),query_seconds=round(time.monotonic()-verified,6),
                               total_seconds=round(time.monotonic()-started,6))
        except sqlite3.Error as e:
            raise ValueError('结果数据库读取未完成；可能超出本次时间限制或结构不受支持。') from e


def dictionary(db):
    rows=[dict(r) for r in db.execute('SELECT * FROM ReportDataDictionary ORDER BY ReportDataDictionaryIndex LIMIT ?', (MAX_DICTIONARY+1,))]
    require(len(rows)<=MAX_DICTIONARY, '输出项超过首批查看范围。')
    return rows


def systems(rows):
    """Use exact output keys, never infer zone names from system name strings."""
    found={}
    for r in rows:
        if r['Name'] in (HEAT,COOL) and r['ReportingFrequency']=='Daily' and not r['IsMeter']:
            require(r['Units']=='J' and r['Type']=='Sum', '逐日冷热需求的单位或累加类型不符。')
            item=found.setdefault(r['KeyValue'],{})
            require(r['Name'] not in item, '同一系统的逐日输出项重复。')
            item[r['Name']]=r['ReportDataDictionaryIndex']
    return {k:v for k,v in found.items() if set(v)=={HEAT,COOL}}


def signal(name):
    if control_metric(name): return '材料控制状态'
    if name in (HEAT,COOL): return '显热需求'
    if name in ('Zone Mean Air Temperature','Zone Operative Temperature'): return '房间温度'
    if name=='Site Outdoor Air Drybulb Temperature': return '室外温度'
    if name.endswith((' State',' Face',' Factor')) or name=='Schedule Value': return '状态／作息原始输出'
    return '其他输出'


# Output names and binary conventions defined by the material adapters.
CONTROL_OUTPUTS = {
    'NX_SC_StateOutput': ('compressed', 'Avg'),
    'NX_SC_FaceOutput': ('face_a', 'Avg'),
    'NX_FiveStorey_Flip_FaceOutput': ('face_a', 'Avg'),
    'NX_Fb_StateOutput': ('compressed', 'Avg'),
    'NX_Fb_ChangedOutput': ('switches', 'Sum'),
}


def control_metric(name):
    if name in CONTROL_OUTPUTS:
        return CONTROL_OUTPUTS[name][0]
    parts = name.split()
    if len(parts) == 3 and parts[0] == 'NX':
        return {'State': 'compressed', 'Face': 'face_a'}.get(parts[2])
    return None


def period_points(db, env, raw, variable, start, end):
    period = raw['period']
    origin = dt.date(2025, *period[:2])
    finish = dt.date(2025, *period[2:])
    first = origin + dt.timedelta(days=day_number(start, period)-1)
    last = origin + dt.timedelta(days=day_number(end, period)-1)
    annual = variable['ReportingFrequency'] == 'Run Period'
    ends = [finish] if annual else [
        min(finish, dt.date(2025, m, calendar.monthrange(2025, m)[1]))
        for m in range(first.month, last.month+1)]
    expected_start = origin if annual else max(origin, first.replace(day=1))
    require(ends and first == expected_start and last == ends[-1],
            '请选择完整的已保存统计时段。')
    rows = [dict(r) for r in db.execute('''SELECT t.TimeIndex,t.Year,t.Month,t.Day,t.Hour,t.Minute,t.Interval,
        t.SimulationDays,r.Value FROM ReportData r JOIN Time t USING(TimeIndex)
        WHERE r.ReportDataDictionaryIndex=? AND t.EnvironmentPeriodIndex=? AND t.IntervalType=?
        AND COALESCE(t.WarmupFlag,0)=0 AND t.SimulationDays BETWEEN ? AND ? ORDER BY t.SimulationDays LIMIT 13''',
        (variable['ReportDataDictionaryIndex'], env, 4 if annual else 3,
         (first-origin).days+1, (last-origin).days+1))]
    require(len(rows) == len(ends), '所选时段的统计值缺失或重复。')
    for row, stop in zip(rows, ends):
        require(row['SimulationDays'] == (stop-origin).days+1 and
                (annual or row['Month'] == stop.month) and isinstance(row['Value'], (int,float)) and
                math.isfinite(row['Value']), '统计时段或读数与登记不符。')
        begin = origin if annual else max(origin, stop.replace(day=1))
        row['label'] = f'{begin:%m-%d} 至 {stop:%m-%d}'
    return rows


def monthly_controls(db, env, raw, dictionary_rows):
    result = {}
    for name, (key, statistic) in CONTROL_OUTPUTS.items():
        matches = [r for r in dictionary_rows if r['Name'] == name and r['KeyValue'] == 'EMS'
                   and r['ReportingFrequency'] == 'Monthly' and not r['IsMeter']]
        if not matches:
            continue
        try:
            require(len(matches) == 1 and matches[0]['Type'] == statistic and not matches[0]['Units'],
                    '控制输出的单位、统计方式或登记数量不符。')
            period = raw['period']
            rows = period_points(db, env, raw, matches[0], '%02d-%02d' % tuple(period[:2]),
                                 '%02d-%02d' % tuple(period[2:]))
            values = {}
            for row in rows:
                value = row['Value']
                if key == 'switches':
                    require(value >= 0 and value == round(value), '切换次数不符合非负整数。')
                else:
                    require(0 <= value <= 1, '状态占比超出有效范围。')
                values[row['Month']] = value
            result[key] = {'months': values}
        except ValueError as exc:
            result[key] = {'error': str(exc)}
    return result


def inventory(root,batch,index):
    with source(root,batch,index) as (db,raw,env,out):
        rows=display_dictionary(dictionary(db),raw)
        times=[dict(t) for t in db.execute('''SELECT IntervalType,MIN(Interval) AS min_minutes,MAX(Interval) AS max_minutes,
            COUNT(*) AS records,MIN(SimulationDays) AS first_day,MAX(SimulationDays) AS last_day
            FROM Time WHERE EnvironmentPeriodIndex=? AND (WarmupFlag=0 OR WarmupFlag IS NULL)
            GROUP BY IntervalType ORDER BY IntervalType''',(env,))]
        require(all(t['IntervalType'] in FREQUENCIES for t in times), '存在未知时间频率。')
        for t in times:t['label']=FREQUENCIES[t['IntervalType']]
        groups={}
        for r in rows:
            key=(signal(r['Name']),r['ReportingFrequency'])
            groups[key]=groups.get(key,0)+1
        coverage=[dict(signal=k[0],frequency=k[1],items=v) for k,v in sorted(groups.items())]
        detailed=any(t['IntervalType'] in (-1,0,1) for t in times)
        daily=systems(rows) if any(t['IntervalType']==2 for t in times) else {}
        out['monthly_loads'] = raw.get('monthly') or []
        out['monthly_controls'] = monthly_controls(db, env, raw, rows)
        out.update(frequencies=times,coverage=coverage,dictionary=rows,systems=sorted(daily),
                   has_subdaily_time_records=detailed,max_days=MAX_DAYS,
                   hourly_note='发现小时／步级时间记录，可按原变量和对象读取有限日期范围；房间与表面位置不从对象名称自动推断。' if detailed else '本结果没有逐小时／逐步时间记录。求解步长不等于输出频率；月均室温和平均状态不能还原变化过程。',
                   state_note='状态／作息按原变量名称列出。平均状态值不代表瞬时状态，也不能据此推断精确切换时刻。')
    return out


def series(root,batch,index,variable,start,end):
    """One saved variable. Detailed series are bounded to 31 days / 12,000 points."""
    with source(root,batch,index) as (db,raw,env,out):
        row=next((r for r in display_dictionary(dictionary(db),raw) if r['ReportDataDictionaryIndex']==variable),None)
        require(row is not None,'输出项不存在。')
        source_id=row.get('SourceDictionaryIndex',variable)
        if row['ReportingFrequency'] in ('Monthly','Run Period'):
            points = period_points(db, env, raw, dict(row, ReportDataDictionaryIndex=source_id), start, end)
            out.update(variable=row,start=start,end=end,rows=points,
                       note='读数对应所示模拟时段。Sum 为累积量，Avg 为均值。')
            return out
        first=day_number(start,raw['period']);last=day_number(end,raw['period'])
        require(1<=last-first+1<=31,'每次请选择连续 1—31 天。')
        types={'Daily':(2,1440),'Hourly':(1,60),'Zone Timestep':(-1,raw['step_minutes'])}
        require(row['ReportingFrequency'] in types,'请选择逐日、逐时或区域步输出。')
        it,minutes=types[row['ReportingFrequency']];expected=(last-first+1)*1440//minutes
        require(expected<=12000,'本次范围超过 12,000 个时间点，请缩短日期范围。')
        points=[dict(r) for r in db.execute('''SELECT t.TimeIndex,t.Year,t.Month,t.Day,t.Hour,t.Minute,t.Interval,t.SimulationDays,r.Value
            FROM ReportData r JOIN Time t USING(TimeIndex)
            WHERE r.ReportDataDictionaryIndex=? AND t.EnvironmentPeriodIndex=? AND t.IntervalType=?
            AND COALESCE(t.WarmupFlag,0)=0 AND t.SimulationDays BETWEEN ? AND ? ORDER BY t.TimeIndex LIMIT 12001''',
            (source_id,env,it,first,last))]
        require(len(points)==expected and len({p['TimeIndex'] for p in points})==expected,'所选范围的数据缺失或重复；未插值或补零。')
        origin=dt.date(2025,*raw['period'][:2]);slots=set()
        for p in points:
            date=origin+dt.timedelta(days=p['SimulationDays']-1)
            require((p['Month'],p['Day'])==(date.month,date.day) and p['Interval']==minutes and
                    isinstance(p['Value'],(int,float)) and math.isfinite(p['Value']),'时间或数值未通过核对。')
            ending=1440 if it==2 else p['Hour']*60+p['Minute']
            require(minutes<=ending<=1440 and ending%minutes==0,'明细时刻与统计间隔不一致。')
            slots.add((p['SimulationDays'],ending))
            p['label']=f"{p['Month']:02}-{p['Day']:02} {ending//60:02}:{ending%60:02}"
        require(len(slots)==expected,'明细时刻重复。')
        out.update(variable=row,start=start,end=end,rows=points,
                   note='时间为原模拟当地时间的区间结束时刻。Sum 是区间累积量，Avg 是区间均值；原单位保留，不自动换算为耗电量。')
    return out


def day_number(text,period):
    try:
        # Accepted contracts use a single non-leap simulation year, not local time.
        month,day=map(int,text.split('-'));date=dt.date(2025,month,day)
        first=dt.date(2025,*period[:2]);last=dt.date(2025,*period[2:])
    except (ValueError,TypeError,AttributeError): raise ValueError('日期请使用月-日，例如 01-01。')
    require(first<=date<=last, '所选日期超出该结果的计算时段。')
    return (date-first).days+1


def daily(root,batch,index,system,start,end):
    with source(root,batch,index) as (db,raw,env,out):
        first=day_number(start,raw['period']);last=day_number(end,raw['period'])
        require(1<=last-first+1<=MAX_DAYS, '每次请选择连续 1—31 天；不会自动截断或抽样。')
        items=systems(dictionary(db));require(system in items, '没有该系统成对的逐日供暖／制冷输出。')
        ids=items[system];data=[dict(r) for r in db.execute('''SELECT t.TimeIndex,t.Year,t.Month,t.Day,t.Hour,t.Minute,t.Dst,t.Interval,
            t.SimulationDays,r.ReportDataDictionaryIndex,r.Value FROM Time t JOIN ReportData r USING(TimeIndex)
            WHERE t.EnvironmentPeriodIndex=? AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) AND t.IntervalType=2
            AND t.SimulationDays BETWEEN ? AND ? AND r.ReportDataDictionaryIndex IN (?,?)
            ORDER BY t.SimulationDays,t.TimeIndex,r.ReportDataDictionaryIndex LIMIT ?''',
            (env,first,last,ids[HEAT],ids[COOL],MAX_DAYS*2+1))]
        require(len(data)==2*(last-first+1), '逐日记录缺失或重复；未补零，也未插值。')
        points={};origin=dt.date(2025,*raw['period'][:2])
        for r in data:
            day=r['SimulationDays'];expected=origin+dt.timedelta(days=day-1)
            require((r['Month'],r['Day'])==(expected.month,expected.day) and r['Interval']==1440,
                    '日期或逐日统计间隔不符。')
            require(type(r['Value']) in (int,float) and math.isfinite(r['Value']) and r['Value']>=0, '逐日需求包含无效数值。')
            key='heating_kWh' if r['ReportDataDictionaryIndex']==ids[HEAT] else 'cooling_kWh'
            stamp_fields={k:r[k] for k in ('TimeIndex','Year','Month','Day','Hour','Minute','Dst','Interval','SimulationDays')}
            point=points.setdefault(day,dict(date=f"{r['Month']:02}-{r['Day']:02}",time=stamp_fields))
            require(point['time']==stamp_fields and key not in point, '冷热数据的时间基准不一致或重复。')
            point[key]=r['Value']/3.6e6
        require(set(points)==set(range(first,last+1)) and all({'heating_kWh','cooling_kWh'}<=p.keys() for p in points.values()), '逐日成对数据不完整。')
        for p in points.values():p['total_kWh']=p['heating_kWh']+p['cooling_kWh']
        out.update(system=system,start=start,end=end,rows=list(points.values()),
                   units='kWh',source_units='J',frequency='Daily',aggregation='Sum',
                   meaning='每日显热需求累积量，不是用电量、瞬时功率或小时曲线。系统名称沿用原输出，不自动推断其房间归属。',
                   sums={k:sum(p[k] for p in points.values()) for k in ('heating_kWh','cooling_kWh','total_kWh')})
    return out
