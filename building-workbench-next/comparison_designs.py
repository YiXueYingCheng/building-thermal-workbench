"""User-defined contrast drafts. Each cell can point to an immutable version or stay open."""
import re

from foundation import canonical, digest, loads, now
from research_sets import require
from theme_groups import valid_pin


def ensure(db):
    db.execute('CREATE TABLE IF NOT EXISTS comparison_designs (id TEXT, revision INTEGER, payload TEXT NOT NULL, PRIMARY KEY(id,revision))')


def drafts(store):
    with store.connect() as db:
        ensure(db)
        rows=db.execute('SELECT payload FROM comparison_designs AS d WHERE revision=(SELECT MAX(revision) FROM comparison_designs WHERE id=d.id) ORDER BY rowid DESC')
        return [loads(row[0]) for row in rows]


def label(value, limit):
    require(isinstance(value,str) and 0<len(value.strip())<=limit,'请填写研究问题、因素名称及每个取值。')
    return value.strip()


def save(store, body):
    ident=body.get('id')
    require(isinstance(ident,str) and re.fullmatch(r'design_[0-9a-f]{32}',ident),'对照设计编号无效。')
    title=label(body.get('name'),100)
    base=valid_pin(store,body.get('base'))
    axes=body.get('axes')
    require(isinstance(axes,list) and len(axes) in (1,2),'请选择一个或两个研究因素。')
    normalized=[]
    for axis in axes:
        require(isinstance(axis,dict),'因素格式无效。')
        values=axis.get('values')
        require(isinstance(values,list) and len(values)==2,'每个因素需要两种取值。')
        values=[label(v,64) for v in values]
        require(values[0]!=values[1],'同一因素的两种取值须能区分。')
        normalized.append(dict(name=label(axis.get('name'),64),values=values))
    require(len({a['name'] for a in normalized})==len(axes),'两条研究轴须有不同的名称。')
    cells=body.get('cells')
    require(isinstance(cells,list) and len(cells)==2**len(axes),'工况格数与因素不符。')
    cells=[None if ref is None else valid_pin(store,ref) for ref in cells]
    used=[(p['id'],p['revision']) for p in cells if p]
    require(len(set(used))==len(used),'同一版本不能同时代表两种预期设置。')
    content=dict(id=ident,name=title,base=base,axes=normalized,cells=cells)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        ensure(db)
        row=db.execute('SELECT payload FROM comparison_designs WHERE id=? ORDER BY revision DESC LIMIT 1',(ident,)).fetchone()
        old=loads(row[0]) if row else None
        if old and all(content[k]==old[k] for k in content):
            return old
        rev=old['revision'] if old else 0
        require(type(body.get('expected_revision')) is int and body['expected_revision']==rev,'这份设计已在另一窗口更新，请重新打开后核对。')
        saved=dict(content,revision=rev+1,updated=now())
        if old and old.get('cell_origins'):
            saved['cell_origins']={str(i):entry for i,ref in enumerate(cells)
                                   for entry in old['cell_origins'].values() if ref==entry['bound']}
        db.execute('INSERT INTO comparison_designs VALUES(?,?,?)',(ident,rev+1,canonical(saved)))
        return saved


def checked_edges(records, selected, evidence):
    """Pair accepted controlled observations in place, using a common export when needed."""
    from comparison_results import compatible
    from pair_evidence import building_key, site_reason

    edges=[]
    for left,right in ((0,1),(2,3),(0,2),(1,3)):
        if left not in selected or right not in selected:continue
        sites={}
        edges.append(dict(left=left,right=right,sites=sites))
        first=evidence.get(left,{})
        second=evidence.get(right,{})
        common=first.keys() & second.keys()
        if not common:continue
        pair=records[left],records[right]
        issues=compatible(*pair,'controlled','total')
        if building_key(pair[0])!=building_key(pair[1]):issues.append('建筑来源不同')
        for site in sorted(common):
            if issues:
                sites[site]='、'.join(issues)
                continue
            # The empty key denotes original observations. A named export must cover both cells.
            sources=first[site].keys() & second[site].keys()
            reason='两格缺少可共同核验的结果来源'
            for source_id in sorted(sources):
                observations=first[site][source_id],second[site][source_id]
                reason=site_reason(pair,observations,site,'controlled','total',archive=bool(source_id))
                if not reason:break
            sites[site]=reason or ''
    return edges


def coverage(reader, body):
    """Inspect known results at each requested location without creating a plan or estimating run time."""
    from collections import Counter
    import comparison_results as results
    import pair_archives
    from pair_evidence import source
    from research_sets import recipe
    store=reader.store
    with store.connect() as db:
        ensure(db)
        row=db.execute('SELECT payload FROM comparison_designs WHERE id=? ORDER BY revision DESC LIMIT 1',(body.get('id'),)).fetchone()
    require(row is not None,'请先保存设计。')
    design=loads(row[0]);require(body.get('revision')==design['revision'],'设计版本已变化，请重新打开核对。')
    cells=body.get('selected')
    require(isinstance(cells,list) and 0<len(cells)<=len(design['cells']) and all(type(i) is int and 0<=i<len(design['cells']) for i in cells),'请选择要核对的工况。')
    records={i:store.get(**dict(ident=p['id'],revision=p['revision'])) for i in dict.fromkeys(cells) if (p:=design['cells'][i])}
    index=results.choice_index(store.root,{r['id'] for r in records.values()}) if records else None
    notices=[]
    archives=pair_archives.for_members(reader,list(records.values()),notices,min_matches=1) if records else []
    inspect_edges=body.get('compare_edges') is True and len(design['axes'])==2
    edge_evidence={}
    items=[];missing=set();counts=Counter()
    for i in dict.fromkeys(cells):
        if i not in records:
            items.append(dict(cell=i,status='待选或待派生',sites=[]));continue
        record=records[i];scope=record['factors']['scope'];options=results.choices(record,store.catalog,store.root,index)
        mode=record['factors']['condition']['operation']['mode']
        if mode not in ('controlled','natural','both'):
            items.append(dict(cell=i,status='请先核对运行模式',sites=[]));continue
        rows=[];key=pair_archives.record_key(record)
        for current in (('controlled','natural') if mode=='both' else (mode,)):
            evidence=[];unclear=False
            for option in options:
                if current not in option['modes']:continue
                data,note=source(record,options,option['id'],current,store.catalog,store.root)
                if note:unclear=True
                if data:evidence.append(('',data['cases']))
            evidence.extend((archive['id'],archive['cases'][key]) for archive in archives if key in archive['cases'])
            for site in scope['site_ids']:
                observations=[(source_id,e[site]) for source_id,e in evidence if site in e and e[site].get('mode')==current]
                hits=[h for _,h in observations]
                accepted={h.get('evidence',{}).get('result_sha256') or digest(h) for h in hits if h.get('status') in ('passed','reused')}
                states={h.get('status') for h in hits}
                if not store.catalog['sites'].get(site,{}).get('eligible',True):state='地点待核对'
                elif len(accepted)>1:state='多份结果待选'
                elif accepted:state='已有核验结果'
                elif 'running' in states:state='计算中'
                elif 'pending' in states:state='已排队'
                elif 'review' in states:state='待复核'
                elif unclear or notices:state='来源待核对'
                elif states:state='已有任务需处理'
                else:
                    state='已有方案，缺结果';missing.add((recipe(record),site,current))
                counts[state]+=1
                row=dict(site=site,city=store.catalog['sites'].get(site,{}).get('name',site),mode=current,status=state)
                if state=='已有核验结果' and current=='controlled':
                    hit=next(h for h in hits if h.get('status') in ('passed','reused'))
                    if hit.get('loads'):
                        row['loads']={k:results.finite(hit['loads'][k]) for k in ('heating_kWh','cooling_kWh','total_kWh')}
                        if inspect_edges:
                            matching={source_id:case for source_id,case in observations
                                      if case.get('status') in ('passed','reused') and case.get('loads')==hit['loads']}
                            edge_evidence.setdefault(i,{})[site]=matching
                rows.append(row)
        items.append(dict(cell=i,status='',sites=rows))
    result=dict(items=items,counts=dict(counts),missing_cases=len(missing),notices=notices)
    if inspect_edges:result['edges']=checked_edges(records,cells,edge_evidence)
    return result


def question_edge(store,design,left,right,target_recipe,rules):
    """Use exact saved pins, or verify an empty neighbouring cell against the question's input."""
    from design_derivation import preview
    pins=design['cells']
    if left in pins and right and right in pins:
        a,b=pins.index(left),pins.index(right)
        return ([a,b],{}) if (a^b) in (1,2) else (None,{})
    if left in pins:
        anchor=pins.index(left); wanted=right; reverse=False
    elif right and right in pins:
        anchor=pins.index(right); wanted=left; reverse=True
    else:
        return None,{}
    if not wanted and not target_recipe:return None,{}
    empty=[]
    with store.connect() as db:
        for cell,pin in enumerate(pins):
            if pin or (cell^anchor) not in (1,2):continue
            try:
                result,_=preview(store,db,design,cell,rules,expected_ref=wanted,expected_recipe=target_recipe,check_model=False)
            except ValueError:
                continue
            if result['kind'] in ('existing','derive'):
                empty.append(cell)
    if len(empty)!=1:return None,{}
    cell=empty[0]
    return ([cell,anchor] if reverse else [anchor,cell]),{cell:dict(expected_ref=wanted,expected_recipe=target_recipe,rules=rules)}


def question_designs(reader,body):
    """Find a saved edge by both pinned versions, then verify coverage in the question's conditions."""
    import plan_workflow
    from design_derivation import AXES, VALUES
    from theme_groups import design_facts
    from foundation import owned, read_json, sha
    store=reader.store
    left,right=body['left'],body.get('right')
    target_recipe=body.get('target_recipe')
    rules=body.get('target_rules',{})
    require(isinstance(rules,dict) and all(k in ('optical','thermal') and isinstance(v,str) for k,v in rules.items()),'追问的控制规则无效。')
    require(isinstance(left,dict) and (isinstance(right,dict) or isinstance(target_recipe,str) and re.fullmatch('[a-f0-9]{64}',target_recipe)), '追问缺少工况依据。')
    require(isinstance(body.get('scope'),list) and all(isinstance(s,str) for s in body['scope']),'追问缺少地点范围。')
    scope=set(body['scope'])
    mode,period,steps=body['mode'],body['period'],body['steps']
    require(left!=right and bool(scope) and mode in ('controlled','natural') and len(steps)==2,'追问的版本或范围无效。')
    results=[]
    checked_budgets={}
    for design in drafts(store):
        pins=design['cells']
        edge,targets=question_edge(store,design,left,right,target_recipe,rules)
        if not edge:continue
        a,b=edge
        records=[store.study_record(p) if p else None for p in pins]
        def fits(i,allowed_steps):
            record=records[i]
            if not record:return False
            facts=design_facts(record)
            for j,axis in enumerate(design['axes']):
                field=next((k for k,pattern in AXES.items() if pattern.fullmatch(axis['name'])),None)
                expected=axis['values'][(i>>(len(design['axes'])-j-1))&1]
                if field and expected in VALUES[field] and facts[field]!=expected:return False
            return (record['factors']['scope']['period']==period and
                    record['numerics']['step_minutes'] in allowed_steps and scope.issubset(record['factors']['scope']['site_ids']) and
                    record['factors']['condition']['operation']['mode'] in (mode,'both'))
        if not all(fits(i,[step]) for i,step in zip(edge,steps) if pins[i]):continue
        if targets and (len(set(steps))!=1 or not scope.issubset(store.study_record(design['base'])['factors']['scope']['site_ids'])):continue
        selected=list(range(len(pins)))
        coverage_rows=coverage(reader,dict(id=design['id'],revision=design['revision'],selected=selected))
        ready=0;budgets={}
        for item in coverage_rows['items']:
            i=item['cell'];record=records[i]
            rows=[s for s in item['sites'] if s['site'] in scope and s['mode']==mode]
            if not fits(i,steps):continue
            if rows and all(s['status']=='已有核验结果' for s in rows) and len(rows)==len(scope):
                ready+=1
            missing={s['site'] for s in rows if s['status']=='已有方案，缺结果'}
            if not missing:continue
            pin_key=(pins[i]['id'],pins[i]['revision'])
            if pin_key not in checked_budgets:
                candidates,_=plan_workflow.preparations(record,{},store.root,bindings=plan_workflow.source_bindings(store.catalog,store.root,record))
                plans=[]
                for r in candidates:
                    if r['valid']:
                        path=owned(store.root/'data/execution/reviews'/r['id']/'plan.json',store.root)
                        plan=read_json(path)
                        plans.append((plan,sha(path)))
                checked_budgets[pin_key]=plans
            for plan,checksum in checked_budgets[pin_key]:
                covered={c['site_id'] for c in plan['cases'] if c['mode']==mode and c['period']==period
                         and c['step_minutes']==record['numerics']['step_minutes']}
                if missing.issubset(covered):
                    budgets.setdefault(i,[]).append(dict(id=plan['id'],sha256=checksum,created=plan['created'],count=plan['case_count']))
        results.append(dict(id=design['id'],revision=design['revision'],name=design['name'],edge=edge,targets=targets,ready=ready,
                            total=len(pins),budgets=budgets))
    return dict(designs=results)
