"""Read-only inventory for the existing W00 daily-load calendar pathway.

No queue writes, input bundles, calendar generation or reference adoption here.
Physical matching ignores output requests and replaces verified schedule paths
with content hashes. It never infers daily values from monthly/annual totals.
"""
import copy
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from foundation import ROOT, digest, loads, now, owned, read_json, sha
import output_storage
from model_adapter import VerifiedReader, compile_case
from execution_results import verify_artifacts
from review_evidence import reviewed


def baseline(record):
    r = copy.deepcopy(record)
    r.get('execution',{}).pop('stack_response',None)
    r.get('execution',{}).pop('wall_observations',None)
    from surface_materials import restore_reference_step
    restore_reference_step(r)
    if any(d.get('model')=='layer_stack_v1' for d in r['factors']['materials'].get('definitions',[])):
        optical=next((c for c in r['factors']['condition']['controls'] if c['channel']=='orientation'),{})
        if 'calendar_step_minutes' in optical:
            from composite_materials import calendar_step
            r['numerics']['step_minutes']=calendar_step(optical)
    if r['provenance']['adapter'] not in ('global_frozen_v011', 'ordinary_building_v1'):
        raise ValueError('该旧动态来源尚未接通独立原构造参考转换；保留原绑定，不能直接移植到新地点。')
    m = r['factors']['materials']
    for key in ('definition_reference',):
        m.pop(key, None)
    m.update(definitions=[], applications=[])
    r['factors']['condition'].update(controls=[], reference_runs=[])
    mode = r['factors']['condition']['operation']['mode']
    if mode not in ('controlled', 'both'):
        raise ValueError('当前没有温控运行模式；逐日冷热需求需要另行确认参考温控，未替您更改。')
    # The controlled branch is already explicitly selected when mode is both.
    r['factors']['condition']['operation']['mode'] = 'controlled'
    return r


def physical(model, dependencies, reader, *, warmup_observer=False):
    from inspection_io import resolve_path
    value = copy.deepcopy({k:v for k,v in model.items() if not k.startswith('Output')})
    if warmup_observer:
        from execution_inputs import OBSERVER
        if value.get('PythonPlugin:Instance') != OBSERVER:
            raise ValueError('冻结模型的预热记录程序与登记不符。')
        del value['PythonPlugin:Instance']
    refs = {resolve_path(p):h for p,h in dependencies.items()}
    for schedule in value.get('Schedule:File', {}).values():
        p = resolve_path(schedule['file_name'])
        if p not in refs:
            raise ValueError('外部作息没有登记的内容校验值。')
        reader.check(dict(path=p, sha256=refs[p]))
        schedule['file_name'] = 'sha256:' + refs[p]
    return digest(value)


def queue_snapshot(root):
    from inspection_io import current
    scope=current()
    if scope is not None:
        from inspection_registry import watched_queue
        snapshot=watched_queue(scope,root)
        if snapshot is not None:return snapshot
    path = Path(root).resolve() / 'data/execution/queue.sqlite'
    if not path.exists():return [], {}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        batches = [dict(r) for r in db.execute('SELECT * FROM batches ORDER BY created DESC,rowid DESC')]
        jobs = {(r['batch'],r['idx']):dict(r) for r in db.execute('SELECT * FROM jobs')}
    return batches, jobs


def frozen_batch(row, root):
    p = loads(row['plan'])
    if not re.fullmatch(r'review_[a-f0-9]{32}', row['review']) or p['id'] != row['review']:
        raise ValueError('清单编号不一致。')
    folder = owned(Path(root)/'data/execution/reviews'/row['review'], Path(root)/'data/execution/reviews')
    if sha(folder/'plan.json') != row['checksum'] or read_json(folder/'plan.json') != p:
        raise ValueError('冻结清单发生变化。')
    record = read_json(folder/'record.json')
    if digest(record) != p['record_sha256'] or (record['id'],record['revision']) != (p['record_id'],p['revision']):
        raise ValueError('冻结方案与清单不一致。')
    return p, record, folder


def candidate(record, reference, case, site_id):
    """Broad discovery only. Exact model/weather/engine verification follows."""
    if record['factors']['building']['id'] != reference['factors']['building']['id'] or case['site_id'] != site_id:return False
    materials = record['factors']['materials']
    return not materials.get('applications') and not record['factors']['condition'].get('controls') and not materials.get('legacy_construction_overrides')


def numeric_representation_reference(reference, saved):
    """Borrow only equal envelope values' int/float representation, never values.

    Generated construction names hash those representations. Recompiling this
    copy lets a saved 2500.0 match the browser's 2500 without ignoring names,
    changing old physical hashes, or weakening any actual-model comparisons.
    """
    a=reference['factors']['building'].get('envelope_overrides')
    b=saved['factors']['building'].get('envelope_overrides')
    def equal(x,y):
        if type(x) in (int,float) and type(y) in (int,float):return x==y
        if type(x) is not type(y):return False
        if isinstance(x,dict):return x.keys()==y.keys() and all(equal(x[k],y[k]) for k in x)
        if isinstance(x,list):return len(x)==len(y) and all(equal(v,w) for v,w in zip(x,y))
        return x==y
    if not a or digest(a)==digest(b) or not equal(a,b):return None
    r=copy.deepcopy(reference);r['factors']['building']['envelope_overrides']=copy.deepcopy(b)
    return r


def match_case(reference, case, plan, model, required_physical, weather_sha, reader, equivalent_physical=None):
    reasons = []
    for actual, expected, label in (
        (case['mode'], 'controlled', '运行模式'),
        (case['period'], reference['factors']['scope']['period'], '统计时段'),
        (case['step_minutes'], reference['numerics']['step_minutes'], '求解步长'),
        (plan['engine_files'], reference['numerics'].get('engine_files'), '引擎文件'),
        (case['dependencies'].get(case['weather']), weather_sha, '气象内容')):
        if actual != expected:reasons.append(label+'不同')
    if digest({k:v for k,v in model.items() if not k.startswith('Output')}) != case['physical_digest']:
        raise ValueError('冻结模型与物理内容校验值不一致。')
    if not reasons and physical(model, case['dependencies'], reader, warmup_observer=bool(case.get('warmup_observer'))) not in (required_physical,equivalent_physical):
        reasons.append('实际建筑、使用配置、运行规则或数值模型不同')
    return reasons


def result_evidence(job, case, root):
    if not job or job['identity'] != case['identity']:raise ValueError('任务与算例身份不一致。')
    if job['status'] not in ('passed','reused'):
        return dict(accepted=False, status=job['status'], note='任务尚无已接受结果。')
    path = output_storage.checked_path(job['result'], root)
    if not job['result_sha256'] or sha(path) != job['result_sha256']:raise ValueError('结果汇总缺失或校验不符。')
    r = read_json(path)
    if any(r[k] != case[k] for k in ('identity','site_id','mode','period','step_minutes')) or r['status'] != 'passed':
        raise ValueError('结果身份或接受状态不符。')
    verify_artifacts(r,root)
    review = reviewed(r, root)
    return dict(accepted=True, status=job['status'], result_path=str(path), result_sha256=job['result_sha256'],
                days=r.get('days'), loads=r.get('loads'), scientific_review=review)


def daily_coverage(model, contract):
    # Unknown contracts never gain permission just by adding a field named daily.
    frequencies = {x.get('reporting_frequency') for x in model.get('Output:Variable',{}).values()}
    if contract == 'monthly_period_v1' and frequencies <= {'Monthly','RunPeriod'}:
        return dict(status='not_retained', usable=False, message='仅保留月度/统计期汇总；未保留逐日冷热需求。')
    return dict(status='unverified', usable=False, message='逐日数据的覆盖、单位和时序尚未核对，不能直接生成日历。')


def bindings(record, catalog):
    binding = catalog.get('dynamic_registry',{}).get('records',{}).get(record['provenance'].get('origin_id',record['id']),{})
    rows = []
    for ref in record['factors']['condition'].get('reference_runs',[]):
        if ref.get('kind')=='workspace_daily_calendar_v1':
            from calendar_library import status,verify_reference
            state=next(x for x in status(record,catalog) if x['id']==ref['id'])
            rows.append(dict(id=(state['name'] or ref['id'])+' · v'+str(state['revision']),days=365,
                calendar_intact=state['valid'],registered_reference_match=state['valid'],
                reference=None,rule=ref.get('snapshot',{}).get('content',{}).get('rule'),
                note='工作区显式采用的日历版本；'+state['note']))
            continue
        cal = ref.get('calendar',[])
        intact = bool(cal) and digest(cal) == ref.get('calendar_sha256')
        rows.append(dict(id=ref.get('id'), days=len(cal), calendar_intact=intact,
            registered_reference_match=ref == binding.get('reference'), site_id=binding.get('site_id'),
            reference=ref.get('reference'), rule=ref.get('rule'),
            note='此处仅核对旧绑定身份与日历内容；逐日资料可另点“核对旧逐日资料”检查，适用性不随旧绑定自动确认。'))
    return rows


def build(record, catalog, root=ROOT, accepted_only=False):
    root = Path(root).resolve()
    f = record['factors'];selected = f['scope']['site_ids']
    out = dict(checked_at=now(), record=dict(id=record['id'], revision=record['revision'], name=record['name'], sha256=digest(record)),
        basis='沿用已有 W00 逐日冷热需求驱动光学切换日历的路径，核对原构造参考准备。此准备针对季节光学切换，热阻反馈本身不要求该日历；本清单不指定新的表面光学切换规则。',
        requirements=dict(building=f['building']['name'], period=f['scope']['period'], step_minutes=record['numerics']['step_minutes'],
            mode='controlled', quantity='逐日显热供热需求与制冷需求，kWh；日历与天气、作息日期对应',
            retain='保留当前建筑基础构造、房间配置和运行设置；只在核对副本中移除研究材料及其控制。'),
        existing_bindings=bindings(record,catalog), rows=[], issues=[], can_generate_calendar=False,
        limits=['“输入匹配”核对实际物理模型、气象及引擎；路径不同但内容相同的已登记作息按内容比较。',
                '上方扫描统一队列结果；旧逐日资料请点击“核对旧逐日资料”单独检查。不把队列未留存理解成旧目录无数据。',
                '月份或全年总量不能还原逐日需求。此检查不会启动计算、补跑、生成或采用日历。'])
    try:
        reference = baseline(record)
        out['requirements']['step_minutes'] = reference['numerics']['step_minutes']
    except ValueError as exc:reference = None;out['issues'].append(str(exc))
    if f['scope']['period'] != [1,1,12,31]:
        out['issues'].append('当前是局部时段；已有全年光学切换日历需要完整参考年，本次未扩大范围。')
    batches,jobs = queue_snapshot(root);available=[]
    for b in batches:
        try:
            p,r,folder = frozen_batch(b,root)
            available.append((b,p,r,folder))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            out['issues'].append('批次 '+b['id']+' 未纳入：'+str(exc))
    reader = VerifiedReader(catalog)
    for position,sid in enumerate(selected):
        from inspection_io import progress
        progress('核对逐日参考',position,len(selected),catalog['sites'][sid]['name'])
        site = catalog['sites'][sid];row=dict(site_id=sid, city=site['name'], candidates=[], historical=[], issues=[], status='missing')
        out['rows'].append(row)
        for job in catalog.get('global_bundle',{}).get('jobs',{}).values():
            if job.get('site_id')==sid and job.get('case')=='W00' and f['building']['id']==catalog['global_bundle'].get('building_source',{}).get('building',{}).get('id'):
                row['historical'].append(dict(id=job['id'], step_minutes=15, status='unverified', note='原平台 W00 来源已登记；旧逐日来源通过底部独立按钮核对。'))
        if reference is None:row['status']='needs_definition';continue
        possibles=[(b,p,r,folder,c) for b,p,r,folder in available for c in p['cases'] if candidate(r,reference,c,sid)]
        # Calendar generation can only use accepted results. Avoid compiling
        # every pending city's model while a large reference batch is running.
        # The separate input-readiness view still inspects all candidates.
        if accepted_only:
            possibles=[item for item in possibles if jobs.get((item[0]['id'],item[4]['index']),{}).get('status') in ('passed','reused')]
        if not possibles:continue  # Do not compile new input just to say no result exists.
        try:
            model,report = compile_case(reference,sid,catalog,reader,operation_mode='controlled')
            for path,checksum in reference['numerics']['engine_files'].items():reader.check(dict(path=path,sha256=checksum))
            deps={x['path']:x['sha256'] for x in report['dependencies']}
            expected = physical(model,deps,reader)
            weather = report['weather'];reader.check(weather);weather_sha=weather.get('expected_sha256') or weather['sha256']
            row['required_physical_sha256']=expected;row['weather_sha256']=weather_sha
        except (ValueError,KeyError,TypeError,OSError) as exc:
            row['status']='blocked';row['issues'].append('当前参考输入未能核对：'+str(exc));continue
        for b,p,r,folder,c in possibles:
            item=dict(batch_id=b['id'], record_id=r['id'], revision=r['revision'], name=r['name'], index=c['index'],
                period=c['period'], step_minutes=c['step_minutes'], status='unverified', input_match=False, accepted=False,
                daily=dict(status='unverified',usable=False,message='尚未完成核对。'))
            row['candidates'].append(item)
            try:
                if c['period']!=r['factors']['scope']['period'] or c['step_minutes']!=r['numerics']['step_minutes']:
                    raise ValueError('算例时段/步长与冻结方案不一致。')
                m=reader.json(dict(path=str(owned(folder/c['model_file'],folder)),sha256=c['model_sha256']))
                different=match_case(reference,c,p,m,expected,weather_sha,reader)
                if different==['实际建筑、使用配置、运行规则或数值模型不同']:
                    equivalent=numeric_representation_reference(reference,r)
                    if equivalent is not None:
                        em,er=compile_case(equivalent,sid,catalog,reader,operation_mode='controlled')
                        ep=physical(em,{x['path']:x['sha256'] for x in er['dependencies']},reader)
                        different=match_case(reference,c,p,m,expected,weather_sha,reader,equivalent_physical=ep)
                        if not different:item['input_equivalence']=dict(kind='equal_envelope_numeric_representation',
                            note='构造参数逐值相同；按已保存的整数/小数形式重建后，完整实际模型匹配。',
                            required_physical_sha256=expected,equivalent_physical_sha256=ep)
                item['differences']=different;item['daily']=daily_coverage(m,p['output_contract'])
                if different:item['status']='different';continue
                reader.check(dict(path=str(owned(root/'data/model-inputs'/p['bundle_id']/'manifest.json',root/'data/model-inputs')),sha256=p['bundle_sha256']))
                for path,checksum in c['dependencies'].items():reader.check(dict(path=path,sha256=checksum))
                for path,checksum in p['engine_files'].items():reader.check(dict(path=path,sha256=checksum))
                item['evidence']=result_evidence(jobs.get((b['id'],c['index'])),c,root)
                if p['output_contract']=='daily_sensible_reference_v1' and item['evidence']['accepted']:
                    from daily_results import inspect
                    item['daily']=inspect(m,c,item['evidence'],root)
                item.update(input_match=True,accepted=item['evidence']['accepted'],status='matched')
            except (ValueError,KeyError,TypeError,OSError) as exc:
                item.update(status='blocked',issue=str(exc))
        row['status']='daily_gap' if any(x['input_match'] and x['accepted'] for x in row['candidates']) else 'needs_review'
        if any(x['input_match'] and x['accepted'] and x['daily']['usable'] for x in row['candidates']):row['status']='daily_ready'
    try:reader.unchanged()
    except (ValueError,OSError) as exc:
        out['issues'].append(str(exc))
        for row in out['rows']:
            if row['candidates']:row['status']='blocked'
            for item in row['candidates']:
                item.update(input_match=False,accepted=False,status='blocked',issue='核对期间来源变化。');item['daily']['usable']=False
    out['summary']=dict(sites=len(selected), matched_results=sum(any(c['input_match'] and c['accepted'] for c in r['candidates']) for r in out['rows']),
        daily_ready=sum(r['status']=='daily_ready' for r in out['rows']), missing=sum(not r['candidates'] for r in out['rows']), legacy_bound=len(out['existing_bindings']))
    return out
