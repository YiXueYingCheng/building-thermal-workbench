"""Read the two pinned inputs and report only observations that pair strictly."""
import pair_archives
import coverage_results
import comparison_results as results
from comparison_reading import question
from foundation import digest, loads
from record_store import Store
from research_sets import recipe, Sets, require


def pin(record):
    return {'id': record['id'], 'revision': record['revision']}


def building_key(record):
    return digest([record['provenance'].get('adapter'), record['provenance'].get('snapshot_id'),
                   record['factors']['building']['id']])


def source(record, options, chosen, mode, catalog, root):
    allowed = [x['id'] for x in options if mode in x['modes']]
    if chosen:
        require(chosen in allowed, '结果来源与所选版本或运行模式不匹配。')
    elif len(allowed) == 1:
        chosen = allowed[0]
    if not chosen:
        return None, '尚无结果来源' if not allowed else '有多个来源，请到结果页选择批次'
    try:
        if chosen.startswith('observed_'):
            data = coverage_results.observed(record, chosen, root)
        elif chosen == 'historical':
            data = results.historical(record, catalog, root)
        else:
            data = results.execution(record, chosen, mode, root)
    except (OSError,ValueError) as error:
        return dict(id=chosen,cases={}), '来源未能核验 · '+str(error)
    return data, ''


def monthly_detail(cases, original):
    first,_,last,_=cases[0]['period']
    months=[(first-1+i)%12+1 for i in range((last-first)%12+1)]
    values=[]
    evidence=[]
    for row in cases:
        raw=row.get('monthly') or []
        by_month={m['month']:m for m in raw}
        require(len(by_month)==len(raw) and set(by_month)==set(months),'当前地点的月度记录不完整或存在重复月份。')
        values.append([[results.finite(by_month[m][k+'_kWh']) for k in ('heating','cooling','total')] for m in months])
        evidence.append({k:(row.get('evidence') or {}).get(k) for k in ('batch_id','index','result_sha256','model_sha256')})
    if original.get('monthly_sources'):
        require(original['monthly_sources']==[s['result_sha256'] for s in evidence],'月度文件与收录时的校验值不同。')
    return dict(months=[dict(month=m,values=[values[0][i],values[1][i]]) for i,m in enumerate(months)],
                month_evidence=evidence)


def read(left, right, request, catalog, root, *, index=None, store=None, reference_cache=None, archive=None, monthly_observation=None):
    metric = request.get('metric', 'total')
    require(metric in ('total','heating','cooling','temperature'), '请选择有效指标。')
    mode = request.get('mode') or ('natural' if metric == 'temperature' and
            any(r['factors']['condition']['operation']['mode'] == 'natural' for r in (left,right)) else 'controlled')
    require(mode in ('controlled','natural'), '请选择有效运行模式。')
    rel = None
    historical = {}
    if request.get('comparison'):
        store = store or Store(catalog, root)
        rel = results.comparison(store, request['comparison'])
        require(rel['left']==pin(left) and rel['right']==pin(right),'比较绑定版本与结果选择不一致。')
        for role in ('left','right'):
            _,historical[role]=store.comparison_input(rel,role)
    records = [left, right]
    scopes = [r['factors']['scope'] for r in records]
    sites = sorted(set().union(*(s['site_ids'] for s in scopes)))
    blocked = results.compatible(left,right,mode,metric)
    if building_key(left) != building_key(right):
        blocked.append('建筑来源不同')
    sources, sides, conditions, notes, ambiguous = [], [], [], [], []
    selected_ids=[request.get(k+'_source') for k in ('left','right')]
    if any(isinstance(s,str) and s.startswith('set_export_') for s in selected_ids):
        require(selected_ids[0]==selected_ids[1],'归档配对的两侧须选用同一份导出。')
        wanted={pair_archives.record_key(r) for r in records}
        archive=archive or pair_archives.load(Sets(catalog,root),root,selected_ids[0],wanted)
        require(archive and archive['id']==selected_ids[0] and wanted.issubset(archive['cases']),'组导出与双方输入版本不匹配。')
        require(mode=='controlled' and metric!='temperature','该组导出提供温控显热需求。')
    if index is None and archive is None:index=results.choice_index(root,{left['id'],right['id']})
    for role,record in zip(('left','right'),records):
        selected=request.get(role+'_source')
        cache_key=(record['id'],record['revision'],mode,selected,historical.get(role))
        cache=reference_cache if role=='left' else None
        if archive:
            data=dict(id=archive['id'],cases=archive['cases'][pair_archives.record_key(record)])
            note,multiple='',False
        elif cache is not None and cache_key in cache:
            data,note,multiple=cache[cache_key]
        else:
            options=results.choices(record,catalog,root,index,historical_bound=historical.get(role))
            multiple=not selected and sum(mode in item['modes'] for item in options)>1
            data,note=source(record,options,selected,mode,catalog,root)
            if cache is not None:
                cache[cache_key]=(data,note,multiple)
        # A saved comparison may replace per-site cases for this pair only.
        if cache is not None and data:
            data=dict(data,cases=dict(data['cases']))
        ambiguous.append(multiple)
        sources.append(data)
        notes.append(note)
    if rel and all(sources) and not any(notes) and not archive:
        from comparison_steps import apply
        apply(rel,records,sources,mode,catalog,root,False)
    for record,scope,data,note,multiple in zip(records,scopes,sources,notes,ambiguous):
        cases = data['cases'] if data else {}
        accepted = sorted(s for s in scope['site_ids'] if catalog['sites'].get(s,{}).get('eligible',True)
                          and cases.get(s,{}).get('status') in ('passed','reused') and cases[s]['mode']==mode)
        sides.append(dict(ref=pin(record),name=record['name'],source=data['id'] if data else None,
                          scope_sites=scope['site_ids'],accepted=accepted, ambiguous=multiple, note=note or ('已核验' if accepted else '缺少已核验结果')))
        conditions.append(dict(sites=[(sid,cases.get(sid,{}).get('weather_sha256') or
                            (catalog['sites'].get(sid,{}).get('weather') or {}).get('sha256'),
                            cases.get(sid,{}).get('step_minutes',record['numerics']['step_minutes']))
                            for sid in sorted(scope['site_ids'])],period=scope['period'],
                            numerics=record['numerics'],operation=record['factors']['condition']['operation']))
    paired, excluded = [], []
    for sid in sites:
        a,b = [s['cases'].get(sid) if s else None for s in sources]
        meta = catalog['sites'].get(sid,{})
        reason = '、'.join(blocked) or results.pair_reason(a,b)
        if not reason and a['mode']!=mode: reason='结果与所选运行模式不一致'
        if not reason and archive and any(sid not in s['site_ids'] or not row['weather_sha256']
                or row['period']!=s['period'] or row['step_minutes']!=r['numerics']['step_minutes']
                for r,s,row in zip(records,scopes,(a,b))):
            reason='组导出与所选版本的运行条件不符'
        if not reason and not archive and metric!='temperature' and {m['month'] for m in a['monthly']}!={m['month'] for m in b['monthly']}:
            reason='双方月度覆盖不一致'
        if not meta.get('eligible',True): reason = '地点暂缓接受'
        if reason:
            excluded.append(dict(site=sid,city=meta.get('name',sid),reason=reason))
            continue
        keys = [digest([side['ref'],side['source'],sid,row]) for side,row in zip(sides,(a,b))]
        item = dict(site=sid,city=meta.get('name',sid),keys=keys)
        if not archive and metric!='temperature' and a.get('monthly') and b.get('monthly'):
            hashes=[row.get('evidence',{}).get('result_sha256') for row in (a,b)]
            if all(hashes):item['monthly_sources']=hashes
        if archive:item['batches']=[row['batch_id'] for row in (a,b)]
        if metric == 'temperature':
            zones = [{r['zone']:r for r in case.get('temperatures',[])} for case in (a,b)]
            if not zones[0] or zones[0].keys()!=zones[1].keys():
                excluded.append(dict(site=sid,city=meta.get('name',sid),reason='缺少可逐房间配对的室温结果'))
                continue
            item['rooms'] = len(zones[0])
        else:
            item['values']=[[results.finite(row['loads'][k+'_kWh']) for k in ('heating','cooling','total')] for row in (a,b)]
        if monthly_observation is not None and sid==monthly_observation['site']:
            require(keys==monthly_observation.get('keys') and item.get('values')==monthly_observation.get('values'),
                    '当前地点的结果与收录时的依据不同，请先核对版本与结果来源。')
            cases=(a,b)
            if archive:
                cases=[pair_archives.monthly_case(record,sid,row,root) for record,row in zip(records,cases)]
            item.update(monthly_detail(cases,monthly_observation))
        paired.append(item)
    return dict(metric=metric,mode=mode,sides=sides,sites=paired,excluded=excluded,
                condition=digest([mode,conditions]),periods=[s['period'] for s in scopes],
                steps=[r['numerics']['step_minutes'] for r in records],
                locations=[catalog['sites'].get(s,{}).get('name',s) for s in sites],
                question=question(left,right),**(dict(export=archive['id'],export_name=archive['group'],
                export_revision=archive['revision']) if archive else {}))


def needs_pair_archive(data):
    return (not data['sites'] and data['metric']!='temperature'
            and not any(s['ambiguous'] for s in data['sides'])
            and any(s['note']=='尚无结果来源' for s in data['sides']))


def archive_alternative(reader,left,right,request,exports,notices):
    matches=pair_archives.matching(exports,left,right)
    if len(matches)>1:
        notices.append(f"{left['name']} → {right['name']} 有多份取值或批次不同的归档配对，请核对原计算型集。")
    if len(matches)!=1:
        return None
    archive=matches[0]
    req=dict(request,left_source=archive['id'],right_source=archive['id'])
    return read(left,right,req,reader.store.catalog,reader.store.root,store=reader.store,archive=archive)


def fixed_optics_candidate(left,right,catalog,root,*,group=None,index=None):
    """Match actual saved recipes, including independently named versions."""
    from controlled_experiment import propose
    sets = Sets(catalog,root)
    refs = [pin(left),pin(right)]
    if group is None:
        with sets.store.connect() as db:
            groups = [loads(row[0]) for row in db.execute('SELECT payload FROM research_sets ORDER BY created DESC, revision DESC')]
    else:
        groups = [group]
    for g in groups:
        if 'feedback' not in g['members']:continue
        members = {k:pin(v['record']) for k,v in g['members'].items()}
        if not (all(ref in members.values() for ref in refs) and members['flip'] in refs):continue
        group = sets.get(g['id'],g['revision'])
        records = sets.records(group)
        try: target,_ = propose(sets,group,records)
        except ValueError:continue
        fixed = records['fixed']
        wanted = recipe(target)
        best = None
        best_rank = (-1,False,False)
        relations = sets.store.comparisons()
        ordered = [ref for rel in relations for ref in (rel['left'],rel['right'])]
        with sets.store.connect() as db:
            ordered.extend(dict(id=row[0],revision=row[1]) for row in db.execute('SELECT id,revision FROM versions ORDER BY revision DESC'))
        ordered.extend(pin(v) for v in catalog['records'].values())
        seen = set()
        for ref in ordered:
            key = (ref['id'],ref['revision'])
            if key in seen:continue
            seen.add(key)
            r = sets.store.study_record(ref)
            if building_key(r)!=building_key(fixed) or recipe(r)!=wanted:continue
            relation = next((rel for rel in relations if rel['left']==pin(fixed) and rel['right']==pin(r) and rel['metric']=='total'),None)
            ident = relation['id'] if relation else None
            evidence = read(fixed,r,dict(comparison=ident),catalog,root,index=index)
            study = evidence['sides'][1]
            rank = (len(evidence['sites']),bool(study['source'] or study['ambiguous']),bool(ident))
            if rank>best_rank:
                best_rank=rank
                best=dict(state='result' if evidence['sites'] else 'saved',right=pin(r),relation=ident,evidence=evidence)
        result = dict(title='全年固定 A 时，按反馈调节热阻是否同样有益？',left=pin(fixed))
        return dict(**result,**(best or dict(state='missing',text='可补充固定 A＋热阻调节，与已有固定蓬松态配对。')))
    return None



def candidates(left,right,catalog,root):
    from comparison_reading import related
    result = related(left,right,catalog,root)
    current = {(r['id'],r['revision']) for r in (left,right)}
    result['candidate'] = (fixed_optics_candidate(left,right,catalog,root)
                           if question(left,right)['kind'] in ('orientation','calendar_feedback') else None)
    result['relations'] = []
    store = Store(catalog,root)
    seen = {frozenset(current)}
    def signature(l,r):
        return frozenset((p['id'],p['revision']) for p in (l,r))
    saved = store.comparisons()
    indexed = {r['id']:r for r in saved}
    for entry in coverage_results.registry(root).get('adjacent_comparisons',[]):
        if entry['id'] in indexed and any(item['export_id']==entry['export_id'] and item['topic']==entry['topic']
                and item['site_id']==entry['site_id'] for item in result['items']):
            rel=indexed[entry['id']]
            seen.add(signature(rel['left'],rel['right']))
    special=result['candidate']
    if special and 'right' in special:
        seen.add(signature(special['left'],special['right']))
    for rel in saved:
        refs=signature(rel['left'],rel['right'])
        if refs in seen or not current.intersection(refs) or rel['metric']!='total':continue
        a,b=[store.comparison_input(rel,k)[0] for k in ('left','right')]
        if not building_key(left)==building_key(a)==building_key(b):continue
        evidence=read(a,b,dict(comparison=rel['id']),catalog,root)
        seen.add(refs)
        result['relations'].append(dict(relation=rel['id'],title=evidence['question']['text'],
            state='result' if evidence['sites'] else 'saved',evidence=evidence))
    return result
