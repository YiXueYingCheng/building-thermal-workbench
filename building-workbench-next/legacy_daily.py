"""Inspect registered legacy W00 daily evidence without copying or running models.

Daily integrity and current-input compatibility are separate from acceptance and
calendar adoption. No legacy module is imported (some have write side effects).
"""
import copy
import csv
import datetime as dt
import io
import math
from pathlib import Path
from foundation import ROOT, config, digest, now, read_json, sha
from model_adapter import VerifiedReader, compile_case
from reference_readiness import baseline

DAILY='建筑逐日结果.csv'
HOURLY='建筑逐时结果.csv'
FIELDS=('heating_kWh','cooling_kWh')
H_FIELDS=('供暖显热需求_kWh','制冷显热需求_kWh')
DATES=[dt.date(2007,1,1)+dt.timedelta(days=i) for i in range(365)]


def discover(catalog, root=ROOT):
    """Only sources already bound by the frozen registry and its batch index."""
    rows=[];issues=[];reader=VerifiedReader(catalog);registry=catalog.get('dynamic_registry',{}).get('records',{})
    batch_refs={}
    profiles={p['path']:p for p in catalog.get('legacy_daily_site_profiles',[])}
    for ident,binding in registry.items():
        ref=binding['reference']['reference']
        if ref.get('kind')=='legacy_W00_reference':batch_refs[ref['source_ref']['path']]=ref['source_ref']
        original=catalog['records'].get(ident,{}).get('provenance',{}).get('original',{})
        p=original.get('dynamic_site')
        if p:profiles[p['path']]=p
    for ref in batch_refs.values():
        try:
            batch=reader.json(ref)
            for city in batch['cities']:
                rows.append(dict(id='china34_'+city['region_id'],city=city['city'],kind='china34',
                    folder=city['source_folder'],daily_path=str(Path(city['source_folder'])/DAILY),daily_sha256=city['source_daily_sha256'],
                    weather_path=city['climate']['path'],weather_sha256=city['climate']['weather']['sha256'],
                    weather_location=city['climate']['weather']['location'],anchor=ref,
                    engine=dict(path=batch['engine'],sha256=batch['engine_sha256']),region_id=city['region_id']))
        except (OSError,ValueError,KeyError,TypeError) as exc:issues.append('34 城来源索引未能读取：'+str(exc))
    for ref in profiles.values():
        try:
            profile=reader.json(ref);daily=str(Path(ref['path']).parent/DAILY)
            # Profiles which reused an original China34 series are not new runs.
            if any(Path(r['folder']).resolve()==Path(profile['reference']['path']).resolve() for r in rows):continue
            rows.append(dict(id=profile['id'],city=profile['city']['city'],kind='dynamic_site',
                folder=profile['reference']['path'],daily_path=daily,daily_sha256=profile['protected'][daily],
                weather_path=profile['weather_path'],weather_sha256=profile['city']['climate']['weather']['sha256'],
                weather_location=profile['city']['climate']['weather']['location'],anchor=ref,
                protected=profile['protected'],template=profile['template']))
        except (OSError,ValueError,KeyError,TypeError) as exc:issues.append('动态地点来源索引未能读取：'+str(exc))
    reader.unchanged()
    return rows,issues


def csv_rows(path):
    data=Path(path).read_bytes()
    if len(data)>20*1024*1024:raise ValueError('逐日/逐时汇总文件超过本入口上限。')
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def finite_nonnegative(value):
    x=float(value)
    if not math.isfinite(x) or x<0:raise ValueError('冷热需求包含负数或非有限值。')
    return x


def reconcile(daily,hourly,summary):
    dates=[(d.month,d.day) for d in DATES]
    if [(int(x['month']),int(x['day'])) for x in daily]!=dates:raise ValueError('逐日日期不是完整、唯一且有序的 365 天。')
    hours=[(m,d,h) for m,d in dates for h in range(1,25)]
    if [(int(x['月']),int(x['日']),int(x['小时终点_1至24'])) for x in hourly]!=hours:raise ValueError('逐时日期不是完整、唯一且有序的 8760 小时。')
    monthly=summary['monthly']
    if [x['month'] for x in monthly]!=list(range(1,13)):raise ValueError('月度汇总不完整或重复。')
    totals={};max_error=0.
    def same(a,b):
        nonlocal max_error
        if not math.isfinite(b):raise ValueError('汇总值非有限。')
        max_error=max(max_error,abs(a-b))
        # Floating point serialization tolerance, not a research accuracy goal.
        if not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-6):raise ValueError('逐时、逐日、月度或年度冷热需求不能闭合。')
    for key,hkey in zip(FIELDS,H_FIELDS):
        ds=[finite_nonnegative(r[key]) for r in daily];hs=[finite_nonnegative(r[hkey]) for r in hourly]
        for i,d in enumerate(ds):same(math.fsum(hs[i*24:(i+1)*24]),d)
        total=math.fsum(ds);same(total,float(summary[key]));totals[key]=total
        for month in monthly:same(math.fsum(v for day,v in zip(DATES,ds) if day.month==month['month']),float(month[key]))
    return dict(days=365,hours=8760,totals=totals,max_closure_error_kWh=max_error,
        metric='建筑显热供热需求与制冷需求，kWh；逐小时累加，不是电耗。',date_basis='非闰参考年，1 月 1 日至 12 月 31 日；小时终点 1–24 归属该日。')


def model_value(model,folder,reader):
    value=copy.deepcopy({k:v for k,v in model.items() if not k.startswith('Output')})
    loc=value.get('Site:Location',{})
    if len(loc)!=1:raise ValueError('模型地点不唯一。')
    # Site:Location names are display labels, not referenced surface/zone names.
    value['Site:Location']={'location':next(iter(loc.values()))}
    for s in value.get('Schedule:File',{}).values():
        path=Path(s['file_name']);path=path if path.is_absolute() else Path(folder)/path
        checksum=sha(path);reader.check(dict(path=str(path),sha256=checksum))
        s['file_name']='sha256:'+checksum
    return value


def inspect(source,catalog,reader=None):
    reader=reader or VerifiedReader(catalog);folder=Path(source['folder'])
    out=dict(id=source['id'],city=source['city'],kind=source['kind'],folder=str(folder),
        daily_checks_passed=False,can_adopt=False,weather_sha256=source['weather_sha256'],evidence=[],issues=[])
    observed={}
    def file(path,expected=None):
        h=expected or sha(path);p=reader.check(dict(path=str(path),sha256=h));observed[str(p)]=h
        return p
    try:
        file(source['anchor']['path'],source['anchor']['sha256'])
        daily=file(source['daily_path'],source['daily_sha256'])
        original=file(folder/DAILY,source['daily_sha256'])
        hourly=file(folder/HOURLY)
        summary=read_json(file(folder/('city-result.json' if source['kind']=='china34' else 'reference-check.json')))
        if summary['checks'].get('passed') is not True:raise ValueError('原参考核查记录未通过。')
        if summary['weather']['sha256']!=source['weather_sha256']:raise ValueError('参考汇总与登记气象内容不符。')
        file(source['weather_path'],source['weather_sha256'])
        counts=reconcile(csv_rows(daily),csv_rows(hourly),summary)
        path=file(folder/'controlled/model.epJSON');model=read_json(path)
        normalized=model_value(model,path.parent,reader)
        timestep=next(iter(model['Timestep'].values()))['number_of_timesteps_per_hour']
        period=next(iter(model['RunPeriod'].values()))
        actual=[period[k] for k in ('begin_month','begin_day_of_month','end_month','end_day_of_month')]
        if actual!=[1,1,12,31] or timestep!=12:raise ValueError('原参考模型不是登记的全年 5 min 输入。')
        location=next(iter(model['Site:Location'].values()))
        if any(not math.isclose(location[k],v,abs_tol=1e-9) for k,v in source['weather_location'].items()):raise ValueError('原模型地点与登记气象不符。')
        model_binding='observed'
        if source['kind']=='china34':
            audit=read_json(file(folder/'climate-and-model-audit.json'))
            if sha(path)!=audit['model_sha256']:raise ValueError('原模型与原地点核查记录不符。')
            file(source['engine']['path'],source['engine']['sha256']);model_binding='original_audit'
        else:
            for p,h in source['protected'].items():file(p,h)
            template=Path(source['template'])/'W00/controlled/model.epJSON'
            expected=model_value(read_json(template),template.parent,reader)
            expected['Site:Location']=normalized['Site:Location']
            if expected!=normalized:raise ValueError('原参考模型不符合已冻结模板及登记地点。')
            model_binding='frozen_template_with_location'
        end=file(folder/'controlled/run/eplusout.end').read_text('utf-8',errors='replace')
        err=file(folder/'controlled/run/eplusout.err').read_text('utf-8',errors='replace')
        import re
        if 'Completed Successfully' not in end or re.search(r'\*\*\s+(Severe|Fatal)\s+\*\*',err):raise ValueError('原运行缺少成功结束或含严重错误。')
        warnings=re.findall(r'^\s*\*\* Warning \*\* (.+)',err,re.M)
        if warnings!=summary.get('warnings',[]):raise ValueError('日志警告与原汇总不一致。')
        out.update(daily_checks_passed=True,coverage=counts,model_binding=model_binding,model_sha256=sha(path),
            physical_sha256=digest(normalized),step_minutes=5,period=actual,start_weekday=period.get('day_of_week_for_start_day'),
            warnings=warnings,review_needed=True,acceptance='旧数据完整性已核对；未替代当前科研接受或采用决定。',
            raw_sql_rechecked=False)
    except (OSError,ValueError,KeyError,TypeError,StopIteration,OverflowError) as exc:
        out['issues'].append(str(exc))
    out['evidence']=[dict(path=p,sha256=h) for p,h in observed.items()]
    return out


def build(record,catalog,root=ROOT):
    sources,issues=discover(catalog,root);reader=VerifiedReader(catalog);f=record['factors']
    out=dict(checked_at=now(),record=dict(id=record['id'],revision=record['revision'],name=record['name'],sha256=digest(record)),
        registered_sources=len(sources),rows=[],issues=issues,can_generate_calendar=False,
        note='按登记气象内容查找旧 Drawing26 W00 逐日来源。文件完整、输入匹配与科研接受分别核对；本入口不采用旧日历，也不启动计算。',
        limits=['只查已登记的 34 城批次及动态地点，未搜索全盘或无登记文件。',
            '核对逐日文件原校验值、逐时/日/月/年闭合、模型、作息、天气及日志；不解压原 SQL 或重新执行求解。',
            '旧引擎记录未完整绑定当前所有运行库，原警告及数据来源仍需接受决定；因此完整且匹配也不自动授权新日历。'])
    try:ref=baseline(record)
    except ValueError as exc:ref=None;out['issues'].append(str(exc))
    checked={}
    for position,sid in enumerate(f['scope']['site_ids']):
        from inspection_io import progress
        progress('核对逐日参考',position,len(f['scope']['site_ids']),catalog['sites'][sid]['name'])
        site=catalog['sites'][sid];w=(site.get('weather') or {}).get('sha256')
        row=dict(site_id=sid,city=site['name'],sources=[],status='no_registered_source');out['rows'].append(row)
        found=[s for s in sources if s['weather_sha256']==w]
        current=None
        frozen_building=catalog.get('global_bundle',{}).get('building_source',{}).get('building',{}).get('id')
        if found and ref and f['building']['id']==frozen_building:
            try:
                m,report=compile_case(ref,sid,catalog,reader,operation_mode='controlled')
                reader.check(report['weather']);current=model_value(m,ROOT,reader)
            except (OSError,ValueError,KeyError,TypeError) as exc:row['issue']='当前参考输入未能核对：'+str(exc)
        for source in found:
            if source['id'] not in checked:checked[source['id']]=inspect(source,catalog,reader)
            item=copy.deepcopy(checked[source['id']]);item['input_match']=False
            if f['building']['id']!=frozen_building:
                item['compatibility']='旧资料属于 Drawing26，不能替代当前建筑的原构造参考。'
            elif not current:item['compatibility']='当前独立参考模型尚未核对。'
            elif item['daily_checks_passed']:
                item['input_match']=digest(current)==item['physical_sha256']
                item['compatibility']='非输出模型及作息、气象内容匹配；旧执行证据及警告仍需确认。' if item['input_match'] else '旧模型与当前原构造参考不同，不能直接作为本方案参考。'
                if not item['input_match']:
                    old=model_value(read_json(Path(source['folder'])/'controlled/model.epJSON'),Path(source['folder'])/'controlled',reader)
                    item['different_object_types']=[k for k in sorted(set(old)|set(current)) if old.get(k)!=current.get(k)]
            row['sources'].append(item)
        if found:row['status']='matched_pending_review' if any(s['input_match'] for s in row['sources']) else 'found_needs_review'
    try:reader.unchanged()
    except (OSError,ValueError) as exc:
        out['issues'].append(str(exc))
        for row in out['rows']:
            if row['sources']:row['status']='blocked'
            for item in row['sources']:item.update(daily_checks_passed=False,input_match=False,issues=item['issues']+['检查期间来源改变。'])
    out['summary']=dict(sites=len(out['rows']),found_sites=sum(bool(r['sources']) for r in out['rows']),
        complete_sites=sum(any(s['daily_checks_passed'] for s in r['sources']) for r in out['rows']),
        input_matched_sites=sum(any(s['input_match'] for s in r['sources']) for r in out['rows']),adopted=0)
    return out
