"""Pinned, explicit result sources; paired observations precede aggregation.

This module never dispatches, resumes, or changes the acceptance of a simulation.
"""
from __future__ import annotations
import math
from pathlib import Path
import statistics
import coverage_results
from foundation import ROOT, read_json, sha, digest, owned, loads, now
from model_adapter import VerifiedReader
from record_store import Store
from execution_queue import Queue
from review_evidence import reviewed

NOTE = '逐地点配对后，按气候类型对有效代表点等权平均；范围为地点最小/最大值，非置信区间。地图将类型均值映射到同类气候区域，不表示逐像元模拟，也不代表全球建筑总量。'


def comparison(store, ident):
    values = [c for c in store.comparisons() if c['id'] == ident]
    if len(values) != 1:
        raise ValueError('未找到已保存的比较关系。')
    return values[0]


def batch_rows(root, ident=None):
    q = Queue(root)
    with q.db() as db:
        return [dict(r) for r in db.execute('SELECT * FROM batches'+(' WHERE id=?' if ident else '')+' ORDER BY created DESC,rowid DESC',(ident,) if ident else ())]


def choice_index(root, record_ids=None):
    """One request can look up several saved versions while scanning each batch plan once."""
    batches = {}
    with Queue(root).db() as db:
        for batch in db.execute('SELECT id,created,mode,plan FROM batches ORDER BY created DESC,rowid DESC'):
            plan = loads(batch['plan'])
            if plan.get('site_recalculation') or (record_ids is not None and plan['record_id'] not in record_ids):
                continue
            key = (plan['record_id'],plan['revision'],plan['record_sha256'])
            batches.setdefault(key,[]).append(dict(id=batch['id'],name=f"{plan['record_name']} · {batch['created']} · {batch['mode']}",
                                                   modes=sorted({case['mode'] for case in plan['cases']})))
    return coverage_results.registry(root)['sources'],batches


def choices(record, catalog, root, index=None, *, historical_bound=None):
    observed,batches = choice_index(root,{record['id']}) if index is None else index
    checksum = digest(record)
    result = list(observed.get(checksum,[]))
    if historical_bound is None:
        historical_bound = bool(catalog.get('global_bundle',{}).get('historical') and record['id'] in ('global_w00','global_fixed') and record == catalog['records'].get(record['id']))
    if historical_bound:
        result.append(dict(id='historical', name='原正式全球批次 · 15 min · 已复核历史来源', modes=['controlled']))
    result.extend(batches.get((record['id'], record.get('revision'), checksum),[]))
    return result


def available(ident, catalog, root=ROOT):
    store = Store(catalog, root); rel = comparison(store, ident)
    data = dict(comparison=rel)
    for side in ('left','right'):
        record,bound = store.comparison_input(rel,side)
        data[side] = choices(record,catalog,root,historical_bound=bound)
    return data


def historical(record, catalog, root=ROOT):
    reader = VerifiedReader(catalog,history_root=root); source = catalog['global_bundle']['historical']['source']
    reader.check(source)
    values = {}; case = record['provenance']['case']
    for job in catalog['global_bundle']['jobs'].values():
        if job['case'] != case:
            continue
        for ref in [job['model'], job['weather'], job['result'], *job['dependencies']]:
            reader.check(ref)
        accepted = job['review_status'].startswith('accepted') and catalog['sites'][job['site_id']]['eligible']
        values[job['site_id']] = dict(status='passed' if accepted else 'review', mode='controlled',
            period=[1,1,12,31], step_minutes=15, days=365, loads=job['annual'], monthly=job['monthly'],
            temperatures=[], weather_sha256=job['weather']['sha256'], pending_warnings=job['pending_warnings'],
            evidence=dict(kind='reviewed_historical', job_id=job['id'], review_status=job['review_status'],
                model=job['model'], weather=job['weather'], result=job['result'], warnings=job['warnings']))
    reader.unchanged()
    return dict(id='historical', kind='reviewed_historical', record_sha256=digest(record), source=source, cases=values)


def execution(record, ident, mode, root):
    matches = batch_rows(root,ident)
    if len(matches) != 1:
        raise ValueError('未找到选定批次。')
    b = matches[0]; p = loads(b['plan']); folder = owned(Path(root)/'data/execution/reviews'/p['id'], root)
    if sha(folder/'plan.json') != b['checksum'] or read_json(folder/'plan.json') != p:
        raise ValueError('批次清单校验不一致。')
    frozen = read_json(folder/'record.json')
    if frozen != record or digest(frozen) != p['record_sha256']:
        raise ValueError('批次未绑定比较关系中的方案版本。')
    if p['conditioned_area_m2'] != record['factors']['building'].get('conditioned_area_m2'):
        raise ValueError('批次面积与方案版本不一致。')
    # Source verification is independent of whether the current executor may resume an old plan.
    reader = VerifiedReader(history_root=root)
    bundle_dir = owned(Path(root)/'data/model-inputs'/p['bundle_id'], root)
    manifest_ref = dict(path=str(bundle_dir/'manifest.json'), sha256=p['bundle_sha256'])
    reader.check(manifest_ref)
    from drawing_wall_scope import available as has_wall_material
    from input_pipeline import read_audit
    input_cases = {}
    if has_wall_material(record):
        manifest = reader.json(manifest_ref)
        input_cases = {(row['site_id'], row.get('mode') or record['factors']['condition']['operation']['mode']):row for row in manifest.get('cases', [])}

    followup = p.get('site_recalculation')
    expected_step = followup['step'] if followup else record['numerics']['step_minutes']
    if followup and (len(p['cases']) != 1 or followup['original_step'] != record['numerics']['step_minutes']):
        raise ValueError('地点补算未绑定原方案步长。')
    for c in p['cases']:
        if c['period'] != record['factors']['scope']['period'] or c['step_minutes'] != expected_step:
            raise ValueError('算例时段或步长与方案版本不一致。')
        reader.check(dict(path=str(owned(folder/c['model_file'],folder)),sha256=c['model_sha256']))
        for path, checksum in c['dependencies'].items():
            reader.check(dict(path=path,sha256=checksum))
    q = Queue(root)
    with q.db() as db:
        from site_recalculation import links
        candidates = [] if followup else links(db,ident)
        jobs = {r['idx']:dict(r) for r in db.execute('SELECT * FROM jobs WHERE batch=?',(ident,))}
    from result_reading import results as readable_results
    results = {r['index']:r for r in readable_results(root,ident)['results']}
    values = {}
    for c in p['cases']:
        if c['mode'] != mode:
            continue
        sid = c['site_id']
        if sid in values:
            raise ValueError('同一批次出现重复地点和模式，无法唯一配对。')
        j = jobs[c['index']]; r = results.get(c['index'])
        if j['identity'] != c['identity']:
            raise ValueError('任务与清单身份不一致。')
        if r and any(r[k] != c[k] for k in ('site_id','mode','period','step_minutes','identity')):
            raise ValueError('结果的地点、时段或计算设置与清单不一致。')
        status = j['status']
        if r and r['status'] == 'review': status = 'review'
        if status in ('passed','reused') and (not r or r['status'] != 'passed'):
            raise ValueError('任务状态与结果核验状态不一致。')
        review = reviewed(r, root) if r else None
        values[sid] = dict(r or {}, status=status, mode=mode, period=c['period'],step_minutes=c['step_minutes'],
            weather_sha256=c['dependencies'][c['weather']],
            evidence=dict(kind='execution',batch_id=ident,index=c['index'],attempt=j['attempt'],identity=c['identity'],
                result_path=j['result'],result_sha256=j['result_sha256'],model_sha256=c['model_sha256'],scientific_review=review,**({'data_retention':r['data_retention']} if r and r.get('data_retention') else {})))
        pinned = input_cases.get((sid, mode))
        if pinned and r:
            scope = read_audit(bundle_dir,pinned).get('drawing_wall_scope')
            if scope:
                values[sid]['wall_scope'] = scope
    reader.unchanged()
    if candidates:
        from site_recalculation import effective
        effective(record,ident,values,jobs,b['checksum'],root,candidates)
    return dict(id=ident,kind='execution',record_sha256=digest(record),plan_sha256=b['checksum'],cases=values,site_recalculation=followup)


def room_usage_contrast(a,b):
    """Recognize a controlled single-factor change on the same building snapshot."""
    from component_library import verify
    left,right=a['factors'],b['factors']
    if a['numerics']!=b['numerics'] or {k:v for k,v in left.items() if k!='building'}!={k:v for k,v in right.items() if k!='building'}:
        return False
    first,second=dict(left['building']),dict(right['building'])
    profiles=(first.pop('usage_profile',None),second.pop('usage_profile',None))
    if first!=second or profiles[0]==profiles[1]:return False
    for key in ('adapter','snapshot_id'):
        origin=a.get('provenance',{}).get(key)
        if not origin or origin!=b.get('provenance',{}).get(key):return False
    bases=set()
    for profile in profiles:
        if profile is not None:
            content=verify(profile,'usage')['content']
            if content['building_id']!=first['id']:return False
            bases.add(content['baseline_sha256'])
    return len(bases)==1


def compatible(a, b, mode, metric):
    issues = []
    if a['factors']['building']!=b['factors']['building'] and not room_usage_contrast(a,b):
        issues.append('建筑定义不同')
    for r in (a,b):
        if r['factors']['condition']['operation']['mode'] not in (mode,'both'):
            issues.append('所选运行模式不属于双方共同模式')
    ao = dict(a['factors']['condition']['operation'],mode=mode)
    bo = dict(b['factors']['condition']['operation'],mode=mode)
    if ao != bo: issues.append('建筑运行设置不同')
    if {k:v for k,v in a['numerics'].items() if k!='step_minutes'} != {k:v for k,v in b['numerics'].items() if k!='step_minutes'}: issues.append('引擎或其他数值设置不同')
    if a['factors']['scope']['period'] != b['factors']['scope']['period']: issues.append('计算时段不同')
    if metric != 'temperature' and mode != 'controlled': issues.append('负荷比较需要双方温控结果')
    for r in (a,b):
        ag = r['factors']['scope']['aggregation']
        if ag.get('weighting') not in (None,'equal_sites'): issues.append('尚未支持该汇总权重')
    if metric != 'temperature':
        area = a['factors']['building'].get('conditioned_area_m2')
        if area is not None and (not isinstance(area,(int,float)) or not math.isfinite(area) or area <= 0):
            issues.append('温控面积无效')
    return list(dict.fromkeys(issues))


def pair_reason(left, right, *, ignore_step=False):
    for r in (left,right):
        if r and r.get('choice_error'):return r['choice_error']
    if left is None or right is None: return '缺少一侧结果或未在该侧范围内'
    for label, row in [('参考',left),('研究',right)]:
        if row['status'] not in ('passed','reused'):
            return label+'侧'+{'review':'待复核','pending':'待计算','running':'计算中','failed':'失败','interrupted':'中断','cancelled':'已取消'}.get(row['status'],'无有效结果')
    for key,label in [('weather_sha256','气象'),('period','时段'),('step_minutes','求解步长'),('mode','运行模式'),('days','覆盖天数')]:
        if key=='step_minutes' and ignore_step:continue
        if left.get(key) != right.get(key):
            if key=='step_minutes':return f"求解步长不一致（参考 {left.get(key)} min，研究 {right.get(key)} min）"
            return label+'不一致'
    return None


def finite(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('结果含缺失或非有限数值。')
    return value


def aggregate(sites, metadata):
    groups = []
    for meta in metadata:
        selected = [s for s in sites if s.get('climate') == meta['climate']]
        valid = [s for s in selected if s['status'] == 'paired']; n = len(valid)
        row = dict(id=meta['id'],climate=meta['climate'],name=meta['name'],catalog_sites=meta['expected_sites'],
            selected_sites=len(selected),valid_sites=n,status='no_data' if not n else 'complete' if n==len(selected) else 'partial')
        for metric in ('heating','cooling','total'):
            for unit in ('kWh','MJ_m2'):
                vals = [s[metric+'_saved_'+unit] for s in valid if s[metric+'_saved_'+unit] is not None]
                for name,fn in [('mean',statistics.mean),('min',min),('max',max)]:
                    row[metric+'_saved_'+unit+'_'+name] = fn(vals) if vals else None
            for side in ('left','right'):
                row[side+'_'+metric+'_kWh_mean'] = statistics.mean(s[side+'_'+metric+'_kWh'] for s in valid) if n else None
        from site_recalculation import step_label
        row['paired_step_label']=step_label(s['left_step_minutes'] for s in valid if s.get('left_step_minutes') is not None)
        row['right_step_label']=step_label(s['right_step_minutes'] for s in valid)
        row['left_step_label']=row['paired_step_label']
        if any(s['left_step_minutes']!=s['right_step_minutes'] for s in valid):
            row['paired_step_label']='参考 '+row['left_step_label']+' / 研究 '+row['right_step_label']
        groups.append(row)
    return groups


def pairing_summary(label,sites,metric):
    paired=[s for s in sites if s['status']=='paired']
    row=dict(basis=label,selected_sites=len(sites),paired_sites=len(paired),
             waived_sites=sum(s['pairing_basis']=='跨步长豁免' for s in paired))
    if metric!='temperature':
        for key in ('heating','cooling','total'):
            for col in ('left_'+key+'_kWh','right_'+key+'_kWh',key+'_saved_kWh'):
                row[col+'_per_paired_site']=statistics.mean(s[col] for s in paired) if paired else None
    return row


def assemble(rel, a, b, left, right, catalog, mode, *, waivers=None):
    waivers=waivers or {}
    metric = rel['metric']; issues = compatible(a,b,mode,metric)
    area = a['factors']['building'].get('conditioned_area_m2')
    ids = set(a['factors']['scope']['site_ids']) | set(b['factors']['scope']['site_ids'])
    if left['id'] == right['id'] == 'historical':
        ids |= {s['id'] for s in catalog['sites'].values() if s.get('source_kind') == 'reviewed_global'}
    sites = []; rooms = []; monthly = []; wall_scopes = {}
    for sid, meta in catalog['sites'].items():
        if sid not in ids: continue
        l = left['cases'].get(sid); r = right['cases'].get(sid)
        waiver=waivers.get(sid)
        reason = '；'.join(issues) if issues else pair_reason(l,r,ignore_step=bool(waiver))
        if not meta.get('eligible',True): reason = '来源地点暂缓接受'
        row = dict(site_id=sid,city=meta['name'],climate=meta.get('climate'),country=meta.get('country'),
            site_kind=meta.get('site_kind'),latitude=meta.get('latitude'),longitude=meta.get('longitude'),
            status='excluded' if reason else 'paired',reason=reason,
            left_step_minutes=l.get('step_minutes') if l else None,right_step_minutes=r.get('step_minutes') if r else None,
            left_status=l['status'] if l else 'missing',right_status=r['status'] if r else 'missing',
            left_evidence=l.get('evidence') if l else None,right_evidence=r.get('evidence') if r else None,
            left_pending_warnings=l.get('pending_warnings',[]) if l else [],right_pending_warnings=r.get('pending_warnings',[]) if r else [])
        for side,item in (('left',l),('right',r)):
            scope = (item or {}).get('wall_scope')
            if scope:
                wall_scopes.setdefault(sid,{})[side] = scope
            selection=(item or {}).get('evidence',{}).get('comparison_selection')
            row[side+'_original_step_minutes']=selection['original']['step'] if selection else (item or {}).get('evidence',{}).get('original_failure',{}).get('step_minutes',row[side+'_step_minutes'])
            row[side+'_selected_batch']=item['evidence']['batch_id'] if selection else ''
        for key in ('heating','cooling','total'):
            for prefix,suffix in [('left','kWh'),('right','kWh'),('','saved_kWh'),('','saved_MJ_m2'),('','saved_percent')]:
                row[(prefix+'_' if prefix else '')+key+'_'+suffix] = None
        if not reason and metric != 'temperature':
            for key in ('heating','cooling','total'):
                lv = finite(l['loads'][key+'_kWh']); rv = finite(r['loads'][key+'_kWh']); delta = lv-rv
                row.update({f'left_{key}_kWh':lv,f'right_{key}_kWh':rv,f'{key}_saved_kWh':delta,
                    f'{key}_saved_MJ_m2':delta*3.6/area if area else None,f'{key}_saved_percent':delta/lv*100 if lv else None})
            lm={x['month']:x for x in l['monthly']}; rm={x['month']:x for x in r['monthly']}
            if set(lm)!=set(rm): raise ValueError('双方月度覆盖不一致。')
            for month in sorted(lm):
                m=dict(pairing_basis='跨步长豁免' if waiver else '严格配对',left_step_minutes=l['step_minutes'],right_step_minutes=r['step_minutes'],site_id=sid,city=meta['name'],climate=meta.get('climate'),month=month)
                for key in ('heating','cooling','total'):
                    lv=finite(lm[month][key+'_kWh']);rv=finite(rm[month][key+'_kWh'])
                    m.update({f'left_{key}_kWh':lv,f'right_{key}_kWh':rv,f'{key}_saved_kWh':lv-rv,f'{key}_saved_MJ_m2':(lv-rv)*3.6/area if area else None})
                monthly.append(m)
        elif not reason:
            lt={x['zone']:x for x in l['temperatures']};rt={x['zone']:x for x in r['temperatures']}
            if not lt or set(lt)!=set(rt):
                row.update(status='excluded',reason='缺少可逐房间配对的温度结果')
            else:
                for zone in sorted(lt):
                    rr=dict(pairing_basis='跨步长豁免' if waiver else '严格配对',left_step_minutes=l['step_minutes'],right_step_minutes=r['step_minutes'],site_id=sid,city=meta['name'],zone=zone)
                    for key in ('mean_C','min_C','max_C'):
                        lv=finite(lt[zone][key]);rv=finite(rt[zone][key]);rr.update({f'left_{key}':lv,f'right_{key}':rv,f'right_minus_left_{key}':rv-lv})
                    rooms.append(rr)
        row['pairing_basis']='未配对' if row['status']!='paired' else '跨步长豁免' if waiver else '严格配对'
        row['waiver_confirmed_at']=waiver['confirmed_at'] if waiver else ''
        row['step_waiver']=waiver
        sites.append(row)
    groups = aggregate(sites,catalog['global_bundle']['classes']) if metric != 'temperature' else []
    period = a['factors']['scope']['period']
    result = dict(schema=1,comparison=rel,created=now(),mode=mode,metric=metric,blocked=issues,
        left={k:v for k,v in left.items() if k!='cases'},right={k:v for k,v in right.items() if k!='cases'},
        records={side:dict(id=r['id'],revision=r['revision'],name=r['name'],sha256=digest(r)) for side,r in [('left',a),('right',b)]},
        period=period,annual=period==[1,1,12,31],step_minutes=a['numerics']['step_minutes'],conditioned_area_m2=area,normalized=bool(area and area>0),
        note=NOTE if metric!='temperature' else '逐房间显示研究减参考的温差；不将房间温度任意平均为气候类型指标。极值差不是同一时刻温差。',
        energy_basis='建筑显热需求，非设备电耗',difference='参考减研究；正值表示需求降低，负值表示增加' if metric!='temperature' else '研究减参考，单位 °C',
        paired_sites=sum(s['status']=='paired' for s in sites),selected_sites=len(sites),sites=sites,classes=groups,monthly=monthly,rooms=rooms)
    if not issues and room_usage_contrast(a,b):
        result['contrast_factor']='room_usage'
        result['difference']='房间使用配置对照 · '+result['difference']
    if all(len(r['factors']['materials']['definitions'])==1 and r['factors']['materials']['definitions'][0]['model'] in ('phase_change_layer_v1','spectral_exterior_v1') for r in (a,b)):
        result['material_response_available']=True
    if wall_scopes:
        result['wall_scopes'] = wall_scopes
    strict=[dict(s,status='excluded') if s['pairing_basis']=='跨步长豁免' else s for s in sites]
    result['pairing_summaries']=[pairing_summary('严格配对',strict,metric),pairing_summary('含已确认豁免',sites,metric)]
    result['strict_classes']=aggregate(strict,catalog['global_bundle']['classes']) if metric!='temperature' and waivers else groups
    from research_input_notes import describe
    result['research_input_notes']={side:describe(r,catalog) for side,r in [('left',a),('right',b)]}
    steps={s[key] for s in sites for key in ('left_step_minutes','right_step_minutes') if s[key] is not None}
    result['step_minutes']=next(iter(steps)) if len(steps)==1 else None
    result['step_label']=' / '.join(f'{s} min' for s in sorted(steps)) or '—'
    coverage_results.annotate(result,(a,b),(left,right),catalog)
    result['dataset_sha256']=digest({k:v for k,v in result.items() if k!='created'})
    return result


def read_sources(ident, left_source, right_source, mode, catalog, root):
    if mode not in ('controlled','natural'): raise ValueError('请选择温控或自然室温模式。')
    store=Store(catalog,root);rel=comparison(store,ident);records=[];sources=[]
    for side,selected in [('left',left_source),('right',right_source)]:
        record,bound=store.comparison_input(rel,side);records.append(record)
        allowed=choices(record,catalog,root,historical_bound=bound)
        if not any(x['id']==selected and mode in x['modes'] for x in allowed):
            raise ValueError('请选择绑定该侧方案版本及运行模式的结果来源。')
        if selected.startswith('observed_'):
            sources.append(coverage_results.observed(record,selected,root))
        else:
            sources.append(historical(record,catalog,root) if selected=='historical' else execution(record,selected,mode,root))
    return rel,records,sources


def build(ident,left_source,right_source,mode,catalog,root=ROOT,*,with_controls=False):
    from comparison_steps import apply
    rel,records,sources=read_sources(ident,left_source,right_source,mode,catalog,root)
    controls,waivers=apply(rel,records,sources,mode,catalog,root,with_controls)
    result=assemble(rel,*records,*sources,catalog,mode,waivers=waivers)
    if with_controls:result['step_controls']=controls
    return result
