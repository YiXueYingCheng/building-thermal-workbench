"""Discover and export recorded case series at their native reporting intervals."""
import csv
import datetime as dt
import math
from collections import Counter

from foundation import digest
from manage import current
from record_store import Store
from result_timeline import HEAT, COOL, control_metric, dictionary, require, source
from schedule_sharing import aliases_by_source


FREQUENCIES = {'Zone Timestep': -1, 'Hourly': 1, 'Daily': 2, 'Monthly': 3, 'Run Period': 4}
GROUPS = {'loads': '系统显热冷热需求', 'temperatures': '房间温度',
          'thermal': '热阻调节状态', 'optical': '表面光学切换状态', 'schedules': '作息数值'}
MEANINGS = {'compressed': '压缩 C 占比，0=蓬松 R，1=压缩 C',
            'face_a': 'A 面朝外占比，0=B 面，1=A 面', 'switches': '区间内热阻切换次数'}


def selected_pairs(selection):
    require(isinstance(selection, list) and len(selection) <= len(GROUPS)*len(FREQUENCIES),
            '请选择有效的导出指标和时间尺度。')
    pairs = set()
    for item in selection:
        require(isinstance(item, list) and len(item) == 2 and all(isinstance(s,str) for s in item)
                and item[0] in GROUPS and item[1] in FREQUENCIES, '导出选项无效。')
        pairs.add(tuple(item))
    return sorted(pairs)


def channel_targets(record):
    targets = {}
    for control in record['factors']['condition']['controls']:
        group = {('thermal','feedback'): 'thermal', ('orientation','calendar'): 'optical'}.get(
            (control['channel'],control['mode']))
        if group:
            targets.setdefault(group,set()).update(control['target_ids'])
    return targets


def series_group(row, targets):
    name = row['Name']
    if row['IsMeter'] or row['ReportingFrequency'] not in FREQUENCIES:
        return None
    if name == 'Schedule Value':
        return 'schedules'
    if name in (HEAT, COOL) and row['Type']=='Sum' and row['Units']=='J':
        return 'loads'
    if name in ('Zone Mean Air Temperature','Zone Operative Temperature') and row['Type']=='Avg' and row['Units']=='C':
        return 'temperatures'
    metric = control_metric(name)
    if not metric or row['KeyValue']!='EMS' or row['Units'] or row['Type']!=('Sum' if metric=='switches' else 'Avg'):
        return None
    group = 'optical' if metric=='face_a' else 'thermal'
    if group in targets and (not name.startswith('NX ') or name.split()[1] in targets[group]):
        return group
    return None


def csv_text(value):
    return "'"+value if isinstance(value,str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value


def write_series(db, env, raw, variables, case, path):
    """Stream and check each dictionary item's entire non-warmup calendar."""
    origin, finish = dt.date(2025,*raw['period'][:2]), dt.date(2025,*raw['period'][2:])
    days = (finish-origin).days+1
    step = raw['step_minutes']
    minutes = {'Daily':1440, 'Hourly':60, 'Zone Timestep':step}
    months = finish.month-origin.month+1
    counts = Counter()
    evidence = case['evidence']
    prefix = [case['index']+1,csv_text(case['city']),case['mode'],case['status_label'],step,evidence['batch_id'],evidence['index']]
    ids = ','.join(str(int(i)) for i in variables)
    query = f'''SELECT r.ReportDataDictionaryIndex, r.Value, t.SimulationDays,t.IntervalType,
        t.Month,t.Day,t.Hour,t.Minute,t.Interval FROM ReportData r JOIN Time t USING(TimeIndex)
        WHERE r.ReportDataDictionaryIndex IN ({ids}) AND t.EnvironmentPeriodIndex=?
        AND COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex'''
    with path.open('w',newline='',encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['算例','地点','模式','核验状态','求解步长_min','结果来源批次','来源索引_从0起',
                         '数据类别','保存频率','区间开始日期','区间结束日期','区间结束时刻','原变量','对象','统计方式',
                         '原单位','原始数值','数值含义','状态占比_%'])
        for ident,value,simday,interval,month,day,hour,minute,length in db.execute(query,(env,)):
            group, row = variables[ident]
            freq = row['ReportingFrequency']
            n = counts[ident]
            require(interval==FREQUENCIES[freq] and isinstance(value,(float,int)) and math.isfinite(value),
                    '时序明细的报告间隔或数值异常。')
            if freq in minutes:
                width = minutes[freq]
                day_index, slot = divmod(n,1440//width)
                end = start = origin+dt.timedelta(days=day_index)
                ending = (slot+1)*width
                require((month,day,length)==(end.month,end.day,width) and
                        (freq=='Daily' or hour*60+minute==ending), '时序明细的日期缺失、重复或错位。')
                clock = f'{ending//60:02}:{ending%60:02}'
            else:
                if freq=='Monthly':
                    require(n < months and month==origin.month+n,'月度明细缺失或重复。')
                    start = max(origin,dt.date(2025,month,1))
                    end = finish if month==finish.month else dt.date(2025,month+1,1)-dt.timedelta(days=1)
                else:
                    start,end = origin,finish
                clock = '24:00'
            require(simday==(end-origin).days+1 and end<=finish, '时序明细与算例时段不符。')
            metric = control_metric(row['Name'])
            percent = ''
            if metric in ('compressed','face_a'):
                require(0<=value<=1,'材料状态占比超出范围。')
                percent = value*100
            if metric=='switches':
                require(value>=0 and value==int(value),'材料切换次数无效。')
            writer.writerow(prefix+[GROUPS[group],freq,start.isoformat()[5:],end.isoformat()[5:],clock,
                                    csv_text(row['Name']),csv_text(row['KeyValue']),row['Type'],row['Units'] or '无量纲',
                                    value,MEANINGS.get(metric,''),percent])
            counts[ident]+=1
        for ident, (_, row) in variables.items():
            freq = row['ReportingFrequency']
            expected = days*1440//minutes[freq] if freq in minutes else months if freq=='Monthly' else 1
            require(counts[ident]==expected,'所选时序有缺失或重复，无法导出完整明细。')
    return sum(counts.values())


def write_schedule_names(raw, variables, path):
    sources = {row['KeyValue'].upper() for group,row in variables.values() if group == 'schedules'}
    aliases = aliases_by_source(raw)
    shared = sorted(sources.intersection(aliases))
    if shared:
        with path.open('w',newline='',encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(['原作息对象','时序 CSV 中的对象'])
            for source in shared:
                writer.writerows((csv_text(name),csv_text(source)) for name in aliases[source])


def inspect(data, root, selection=(), stage=None):
    record = Store(current(root),root).get(data['record_id'],data['revision'])
    require(digest(record)==data['record_sha256'],'方案版本与批次登记不一致，请刷新。')
    targets = channel_targets(record)
    totals = Counter()
    cases = []
    for case in data['results']:
        evidence = case['evidence']
        entry = dict(index=case['index'],city=case['city'],source_batch=evidence['batch_id'],
                     source_index=evidence['index'],available=[])
        cases.append(entry)
        if case['status'] not in ('passed','reused','review'):
            entry['note'] = case['status_label']
            continue
        writing_details = False
        try:
            with source(root,evidence['batch_id'],evidence['index'],budget=600) as (db,raw,env,proof):
                require(proof['summary_sha256']==evidence['result_sha256'] and proof['identity']==evidence['identity'],
                        '明细来源与当前批次快照不一致。')
                # Consult dictionary items actually present in the formal simulation.
                present = {r[0] for r in db.execute('''SELECT DISTINCT r.ReportDataDictionaryIndex FROM
                    ReportData r JOIN Time t USING(TimeIndex) WHERE t.EnvironmentPeriodIndex=?
                    AND COALESCE(t.WarmupFlag,0)=0''',(env,))}
                variables = {}
                options = set()
                for row in dictionary(db):
                    ident = row['ReportDataDictionaryIndex']
                    group = series_group(row,targets)
                    if not group or ident not in present:
                        continue
                    pair = group,row['ReportingFrequency']
                    options.add(pair)
                    if pair in selection:
                        variables[ident] = group,row
                entry.update(available=sorted(options),sql_sha256=proof['sql_sha256'])
                if stage is not None and variables:
                    writing_details = True
                    name = f"case-{case['index']+1:03d}.csv"
                    entry.update(file=name,rows=write_series(db,env,raw,variables,case,stage/name))
                    write_schedule_names(raw,variables,stage/name.replace('.csv','-schedule-names.csv'))
            totals.update(options)
        except (OSError, ValueError) as error:
            if writing_details:
                raise ValueError(f"{case['city']} 的明细导出未完成。{error}") from error
            entry.update(available=[],note=str(error))
    return dict(groups={k:v for k,v in GROUPS.items() if k in ('loads','temperatures') or k in targets or any(g==k for g,f in totals)},
                frequencies=list(FREQUENCIES), total_cases=len(cases),
                choices=[dict(group=g,frequency=f,cases=n) for (g,f),n in sorted(totals.items())],
                cases=cases, inventory_sha256=digest([{k:v for k,v in c.items() if k not in ('file','rows')} for c in cases]))
