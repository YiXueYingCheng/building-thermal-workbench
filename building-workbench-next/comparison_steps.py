"""Choose an alternate solver step for one site in a pinned two-condition comparison."""
from foundation import canonical, digest, loads, now
from execution_queue import Queue
from comparison_results import execution, compatible, pair_reason
from site_recalculation import allowed_steps, links

WHERE = 'comparison=? AND left_batch=? AND right_batch=? AND mode=?'
SIDES = ('left','right')


def key(relation, sources, mode):
    return (relation['id'], sources[0]['id'], sources[1]['id'], mode)


def selections(db, scope):
    return {r['site']:loads(r['selection']) for r in db.execute(
        'SELECT site,selection FROM comparison_step_choices WHERE '+WHERE,scope)}


def pin(row):
    if not row:
        return None
    e=row['evidence']
    if e['kind']!='execution':
        return dict(historical=digest(e),step=row['step_minutes'])
    return {k:e[k] for k in ('batch_id','index','attempt','identity','result_sha256')} | dict(step=row['step_minutes'])


def eligible(side,rows,sources,records):
    a,b=rows[side],rows[1-side]
    if not a or not b or a['step_minutes']==b['step_minutes']:
        return False
    return (a['evidence'].get('batch_id')==sources[side]['id'] and
            b['step_minutes'] in allowed_steps(records[side],a['step_minutes']) and
            pair_reason(dict(a,step_minutes=b['step_minutes']),b) is None)


def can_waive(rows):
    left,right=rows
    if not left or not right or left['step_minutes']==right['step_minutes']:
        return False
    shorter_recovery=any(row['step_minutes'] < row['evidence'].get('original_failure',{}).get('step_minutes',0)
                         for row in rows)
    if not shorter_recovery or pair_reason(left,right,ignore_step=True):
        return False
    field,key=('monthly','month') if left['mode']=='controlled' else ('temperatures','zone')
    entries=[{v[key] for v in (r.get(field) or [])} for r in rows]
    return bool(entries[0]) and entries[0]==entries[1]


def available(rows, sources, records, candidates):
    options=[]
    for side,label in enumerate(SIDES):
        if not eligible(side,rows,sources,records):continue
        original=pin(rows[side]);target=rows[1-side]['step_minutes']
        runs=[{k:r[k] for k in ('child','step','status','attempt','result_sha256','error')}
              for r in candidates[side] if r['purpose']=='comparison' and r['idx']==original['index'] and
              r['original_attempt']==original['attempt'] and r['step']==target]
        options.append(dict(side=label,parent=original['batch_id'],index=original['index'],
                            attempt=original['attempt'],step=target,runs=runs))
    return options


def selected_case(choice, rows, site, mode, records, sources, root):
    side=SIDES.index(choice['side'])
    if choice['pins']!=[pin(r) for r in rows] or not eligible(side,rows,sources,records):
        raise ValueError('原结果或配对侧已经变化。')
    original=rows[side]
    e=original['evidence']
    report=execution(records[side],choice['child'],mode,root)
    ref=report.get('site_recalculation') or {}
    new=report['cases'].get(site)
    if (ref.get('purpose')!='comparison' or ref.get('parent')!=e['batch_id'] or ref.get('idx')!=e['index']
            or ref.get('parent_checksum')!=sources[side]['plan_sha256'] or ref.get('original_attempt')!=e['attempt']
            or ref.get('original_identity')!=e['identity'] or ref.get('original_result_sha256')!=e['result_sha256']
            or ref.get('original_model_sha256')!=e['model_sha256'] or ref.get('original_step')!=original['step_minutes']
            or not new or pair_reason(new,rows[1-side]) or pin(new)!=choice['chosen']):
        raise ValueError('加算的来源、结果或配对条件发生变化。')
    new['evidence']['comparison_selection']=dict(original=choice['pins'][side],counterpart=choice['pins'][1-side],
                                                  confirmed_at=choice['confirmed_at'])
    return new


def apply(relation,records,sources,mode,catalog,root,with_controls):
    scope=key(relation,sources,mode)
    q=Queue(root)
    with q.db() as db:
        saved=selections(db,scope)
        candidates=[links(db,source['id']) for source in sources] if with_controls else []
    if not saved and not with_controls:return {},{}
    controls={}
    waivers={}
    issues=compatible(*records,mode,relation['metric'])
    ids=set(sources[0]['cases'])|set(sources[1]['cases'])
    for site in ids:
        rows=[s['cases'].get(site) for s in sources]
        choice=saved.get(site)
        usable=not issues and catalog['sites'].get(site,{}).get('eligible',True)
        waive=usable and can_waive(rows)
        if choice and choice.get('kind')=='waiver':
            valid=waive and choice['pins']==[pin(r) for r in rows]
            if valid:waivers[site]=choice
            elif rows[0]:sources[0]['cases'][site]=dict(rows[0],choice_error='豁免绑定的结果或配对条件已变化，请重新核对。')
            if with_controls:
                options=available(rows,sources,records,candidates) if valid else []
                controls[site]=dict(selected=choice,expected=digest(choice),options=options)
        elif choice:
            side=SIDES.index(choice['side'])
            try:
                if not usable:raise ValueError('双方方案条件或地点资格已变化。')
                sources[side]['cases'][site]=selected_case(choice,rows,site,mode,records,sources,root)
            except (ValueError,OSError,KeyError) as error:
                if rows[side]:sources[side]['cases'][site]=dict(rows[side],status='excluded',choice_error='已选加算需核对：'+str(error))
            if with_controls:controls[site]=dict(selected=choice,expected=digest(choice),options=[])
        elif with_controls and usable:
            options=available(rows,sources,records,candidates)
            if options or waive:controls[site]=dict(selected=None,expected=digest([pin(r) for r in rows]),options=options,can_waive=waive)
    return controls,waivers


def check_current(db,p):
    if not p or 'historical' in p:return
    job=db.execute('SELECT status,attempt,identity,result_sha256 FROM jobs WHERE batch=? AND idx=?',
                   (p['batch_id'],p['index'])).fetchone()
    if (not job or job['status'] not in ('passed','reused') or
            any(job[k]!=p[k] for k in ('attempt','identity','result_sha256'))):
        raise ValueError('结果已变化，请重新读取本次对照。')


def choose(root,catalog,body):
    from comparison_results import read_sources
    relation,records,sources=read_sources(body['id'],body['left_source'],body['right_source'],body['mode'],catalog,root)
    mode,site=body['mode'],body['site']
    scope=key(relation,sources,mode)
    q=Queue(root)
    with q.db() as db:
        old=selections(db,scope).get(site)
        candidates=[links(db,s['id']) for s in sources]
    if body['action']=='clear':
        if not old or digest(old)!=body.get('expected'):raise ValueError('选用记录已变化，请刷新。')
        choice=None
    elif body['action'] in ('select','waive'):
        if old and not (old.get('kind')=='waiver' and body['action']=='select'):
            raise ValueError('此地点已有选用记录，请刷新。')
        if compatible(*records,mode,relation['metric']) or not catalog['sites'].get(site,{}).get('eligible',True):
            raise ValueError('双方方案或地点不符合配对条件。')
        rows=[s['cases'].get(site) for s in sources]
        pins=[pin(r) for r in rows]
        expected=digest(old) if old else digest(pins)
        if expected!=body.get('expected') or (old and old['pins']!=pins):
            raise ValueError('双方结果已变化，请重新读取。')
        if body['action']=='waive':
            if not can_waive(rows):raise ValueError('此地点未满足短步长补算的豁免条件。')
            choice=dict(kind='waiver',pins=pins,confirmed_at=now())
        else:
            choice=select_alternate(body,rows,records,sources,candidates,site,mode,root,pins)
    else:
        raise ValueError('请选择选用、豁免或恢复。')
    with q.db() as db:
        if selections(db,scope).get(site)!=old:raise ValueError('选用记录已变化，请刷新。')
        if choice:
            for p in choice['pins']:check_current(db,p)
            if 'chosen' in choice:check_current(db,choice['chosen'])
            db.execute('INSERT INTO comparison_step_choices VALUES(?,?,?,?,?,?) '
                       'ON CONFLICT(comparison,left_batch,right_batch,mode,site) DO UPDATE SET selection=excluded.selection',
                       (*scope,site,canonical(choice)))
        else:
            db.execute('DELETE FROM comparison_step_choices WHERE '+WHERE+' AND site=?',(*scope,site))
        q.event(db,scope[1],'comparison_site_step',dict(comparison=scope[0],sources=scope[1:3],mode=mode,
                                                        site=site,previous=old,selected=choice))
    return dict(selected=choice)


def select_alternate(body,rows,records,sources,candidates,site,mode,root,pins):
    options=available(rows,sources,records,candidates)
    option=next((o for o in options if o['side']==body['side']),None)
    run=next((r for r in (option or {}).get('runs',[]) if r['child']==body['child']),None)
    if not run or run['status'] not in ('passed','reused') or not run['result_sha256'] or run['result_sha256']!=body['result_sha256']:
        raise ValueError('该加算尚未通过或结果已变化。')
    side=SIDES.index(option['side'])
    link=next(r for r in candidates[side] if r['child']==run['child'])
    chosen=dict(batch_id=run['child'],index=0,attempt=run['attempt'],identity=link['identity'],
                result_sha256=run['result_sha256'],step=run['step'])
    choice=dict(side=option['side'],child=run['child'],chosen=chosen,pins=pins,confirmed_at=now())
    selected_case(choice,rows,site,mode,records,sources,root)
    return choice
