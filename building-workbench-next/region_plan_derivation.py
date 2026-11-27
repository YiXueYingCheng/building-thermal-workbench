"""Turn a saved regional study into ordinary, versioned multi-site calculation plans."""
from collections import defaultdict
from copy import deepcopy

import calendar_library as calendars
from contracts import calculation_recipe
from design_regions import preview, shape
from foundation import digest, loads
from model_adapter import capability
from reference_readiness import baseline
from research_sets import require


def plan_key(record):
    recipe = calculation_recipe(record)
    recipe['factors']['scope']['site_ids'].sort()
    return digest(calendars.stable_numbers([recipe, record['provenance']['adapter'],
                                           record['execution'],record['factors']['scope'].get('aggregation')]))


def pin(record):
    return dict(id=record['id'],revision=record['revision'],name=record['name'])


def records(db,store):
    yield from store.catalog['records'].values()
    for row in db.execute('SELECT payload FROM versions ORDER BY created DESC,rowid DESC'):
        yield loads(row[0])


def bind_calendar(record,context,library,entries):
    """Select one saved calendar that contains every locally matched entry."""
    pinned,basis = context
    for snapshot in (pinned,*library[basis]):
        applicable = {r['site_id']:digest(r) for r in snapshot['content']['sites'] if r['site_id'] in entries}
        if applicable != entries:
            continue
        ref = calendars.snapshot_reference(snapshot)
        condition = record['factors']['condition']
        for control in condition['controls']:
            if control.get('mode')=='calendar' and control.get('reference_id')==pinned['id']:
                control['reference_id']=ref['id']
        condition['reference_runs']=[ref if r.get('id')==pinned['id'] else r for r in condition['reference_runs']]
        return True
    return False


def proposals(reader,body):
    report,group,contexts,library,local,missing_daily=preview(reader,body,for_plans=True)
    store=reader.store
    plans,waiting=[],[]
    baselines={}
    labels={v['cell']:v['label'] for v in report['members']}
    rows=report['rows']

    def add(slot,label,source,target,sites,mode,daily=False):
        target['factors']['scope']['site_ids']=sorted(sites)
        target['factors']['condition']['operation']['mode']=mode
        target['name']=(target['factors']['building']['name']+' · '+label+' · '+str(len(sites))+' 地点')[:100]
        target=store.update_payload(target,{})
        support=capability(target,store.catalog)
        if not support['supported']:
            waiting.append(dict(label=label,count=len(sites),reason='；'.join(support['reasons'])))
            return
        info=dict(slot=slot,label=label,source=pin(source),sites=sorted(sites),key=plan_key(target),
                  mode=mode,daily=daily,step=target['numerics']['step_minutes'],period=target['factors']['scope']['period'])
        plans.append((info,source,target))

    for member in group['members']:
        i,source=member['cell'],member['source']
        context=contexts.get((source['id'],source['revision']))
        needed=defaultdict(set)
        no_calendar=set()
        for row in rows:
            sid=row['site']
            modes={c['mode'] for c in row['cases'] if c['cell']==i and c['kind']=='needed'}
            if not modes:
                continue
            if context and (i,sid) not in local:
                no_calendar.add(sid)
                if sid in missing_daily.get(context[1],()):
                    baselines.setdefault(context[1],(source,set()))[1].add(sid)
                continue
            require(modes<={'controlled','natural'},'工况的运行模式尚未明确。')
            mode='both' if len(modes)==2 else next(iter(modes))
            needed[mode].add(sid)
        if no_calendar:
            waiting.append(dict(label=labels[i],count=len(no_calendar),reason='待当地 W00 逐日参考与光学切换日历就绪'))
        for mode,sites in needed.items():
            target=deepcopy(source)
            if context and not bind_calendar(target,context,library,{sid:local[i,sid] for sid in sites}):
                waiting.append(dict(label=labels[i],count=len(sites),reason='请先核对并保存覆盖这些地点的一份光学切换日历'))
                continue
            add('cell-'+str(i)+'-'+mode,labels[i],source,target,sites,mode)
    if baselines:
        with store.connect() as db:
            pool=list(records(db,store))
        for basis,(source,sites) in sorted(baselines.items()):
            target=baseline(source)
            target['factors']['scope']['period']=[1,1,12,31]
            original=next((r for r in pool if not r.get('archived') and not r['factors']['materials']['applications']
                           and shape(r)==shape(target) and r['factors']['scope']['site_ids']==source['factors']['scope']['site_ids']),source)
            add('daily-'+basis,'W00 · 原构造逐日参考',original,target,sites,'controlled',True)
    return plans,dict(waiting=waiting,counts=report['counts'],warnings=report['warnings'])


def links(db,group_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='design_region_plans' AND type='table'").fetchone():
        return []
    return [dict(r) for r in db.execute('SELECT * FROM design_region_plans WHERE group_id=? ORDER BY rowid DESC',(group_id,))]


def daily_navigation(store,records):
    """Latest daily link per regional slot, preserving its exact saved version."""
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='design_region_plans'").fetchone():
            return []
        pins=db.execute('''SELECT record_id,revision FROM design_region_plans
            WHERE rowid IN (SELECT MAX(rowid) FROM design_region_plans WHERE daily=1 GROUP BY group_id,slot)
            GROUP BY record_id,revision ORDER BY MAX(rowid) DESC''').fetchall()
    heads={r['id']:r for r in records}
    items=[]
    for ident,revision in pins:
        record=heads.get(ident)
        if not record or record.get('archived'):
            continue
        if revision!=record['revision']:
            try:record=store.get(ident,revision)
            except KeyError:continue
        items.append(pin(record))
    return items


def plan_origins(store):
    """Describe versions created by regional derivation, including existing receipts."""
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='design_region_plans'").fetchone():
            return []
        rows=db.execute('''SELECT p.record_id,p.revision,p.label,p.daily,g.name,g.site_count,
            json_array_length(v.payload,'$.factors.scope.site_ids') AS plan_sites,
            json_extract(v.payload,'$.provenance.parent_id') AS parent_id,
            json_extract(v.payload,'$.provenance.parent_revision') AS parent_revision,
            json_extract(parent.payload,'$.name') AS parent_name
            FROM design_region_plans p JOIN versions v ON (v.id,v.revision)=(p.record_id,p.revision)
            LEFT JOIN design_region_groups g ON g.id=p.group_id
            LEFT JOIN versions parent ON (parent.id,parent.revision)=
                (json_extract(v.payload,'$.provenance.parent_id'),json_extract(v.payload,'$.provenance.parent_revision'))
            WHERE p.owned=1 ORDER BY p.rowid''')
        origins=[]
        for row in rows:
            ident,rev,label,daily,group,total,sites,parent_id,parent_rev,parent_name=row
            if not parent_name:
                source=store.catalog['records'].get(parent_id)
                if source and source['revision']==parent_rev:
                    parent_name=source['name']
            origins.append(dict(id=ident,revision=rev,label=label,daily=bool(daily),group=group,
                                group_sites=total,sites=sites,parent_name=parent_name,parent_revision=parent_rev))
        return origins


def derive_plans(reader,body,confirm=False):
    store=reader.store
    require(isinstance(body.get('group'),str) and body['group'],'请从已保存的地区组派生。')
    plans,result=proposals(reader,body)
    token=digest([body['group'],[(p['slot'],p['key']) for p,_,_ in plans],result])
    if confirm:
        require(body.get('preview_key')==token,'范围、来源或缺项已变化，请重新核对后再派生。')
    with store.connect() as db:
        if confirm:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('SELECT 1 FROM design_region_groups WHERE id=? AND design_id=?',(body['group'],body['id'])).fetchone(),
                    '地区组已移除，请返回设计。')
            db.execute('CREATE TABLE IF NOT EXISTS design_region_plans (group_id TEXT, design_id TEXT, slot TEXT, recipe TEXT, '
                       'record_id TEXT, revision INTEGER, label TEXT, daily INTEGER, owned INTEGER, PRIMARY KEY(group_id,slot,recipe))')
        saved=links(db,body['group'])
        pool=list(records(db,store))
        by_pin={(r['id'],r['revision']):r for r in pool}
        scopes={frozenset(info['sites']) for info,_,_ in plans}
        matches={}
        for r in pool:
            if not r.get('archived') and frozenset(r['factors']['scope']['site_ids']) in scopes:
                matches.setdefault(plan_key(r),r)
        for info,source,target in plans:
            prior=next((r for r in saved if r['slot']==info['slot'] and r['recipe']==info['key']),None)
            found=by_pin.get((prior['record_id'],prior['revision'])) if prior else None
            if prior:
                require(found is not None and plan_key(found)==info['key'],'已关联版本的输入需要复核。')
            found=found or matches.get(info['key'])
            info['linked']=bool(prior)
            if confirm and not prior:
                owned=False
                if not found:
                    last=next((r for r in saved if r['slot']==info['slot'] and r['owned']),None)
                    head=store.get(last['record_id']) if last else None
                    if head and head['revision']==last['revision'] and not head.get('archived'):
                        changes={k:target[k] for k in ('name','factors','numerics','execution')}
                        updated=store.update_payload(head,changes)
                        require(plan_key(updated)==info['key'],'更新后的工况输入与预览不一致。')
                        found=store.insert_revision(db,updated,head['revision'])
                    else:
                        found=store.insert_draft(db,source,target)
                    owned=True
                    matches[info['key']]=found
                db.execute('INSERT INTO design_region_plans VALUES (?,?,?,?,?,?,?,?,?)',
                           (body['group'],body['id'],info['slot'],info['key'],found['id'],found['revision'],info['label'],info['daily'],owned))
                info['linked']=True
            info['version']=pin(found) if found else None
        active={(p['slot'],p['key']) for p,_,_ in plans}
        result['previous']=[dict(label=s['label'],daily=bool(s['daily']),version=pin(by_pin[(s['record_id'],s['revision'])]))
                            for s in saved if (s['slot'],s['recipe']) not in active and (s['record_id'],s['revision']) in by_pin]
    result.update(plans=[p for p,_,_ in plans],preview_key=token)
    return result
