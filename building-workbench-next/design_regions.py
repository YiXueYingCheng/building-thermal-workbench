"""Regional coverage and grouped derivatives of selected design conditions."""
from collections import defaultdict, Counter
from copy import deepcopy

import calendar_library as calendars
import comparison_results as results
import pair_archives
import reference_readiness as references
from component_library import Library
from contracts import calculation_recipe
from foundation import canonical, digest, loads, now
from pair_evidence import source
from research_sets import require
from scope_management import registered, weather_detail


def shape(record):
    """All research inputs except the target sites and the locally bound calendar."""
    recipe = calculation_recipe(record)
    recipe['adapter'] = record['provenance']['adapter']
    recipe['factors']['scope'].pop('site_ids')
    condition = recipe['factors']['condition']
    active = calendars.active_references(record)
    ids = {ref['id'] for ref in active}
    for control in condition['controls']:
        if control.get('mode') == 'calendar' and control.get('reference_id') in ids:
            control['reference_id'] = 'local_w00_calendar'
    condition['reference_runs'] = [r for r in condition['reference_runs'] if r.get('id') not in ids]
    return digest(calendars.stable_numbers(recipe))


def calendar_context(record, catalog):
    active = calendars.active_references(record)
    uses = [c for c in record['factors']['condition']['controls'] if c.get('mode') == 'calendar']
    if not uses:
        return None
    require(len(active) == 1 and all(c.get('reference_id') == active[0]['id'] for c in uses),
            '这项控制的地域日历需要核对来源。')
    snapshot = calendars.verify_reference(active[0])
    basis = calendars.definition(record, catalog)
    require(snapshot['content']['basis'] == basis, '日历和模板的建筑、温控或数值设置不匹配。')
    return snapshot, digest(basis)


def local_calendar(sid, weather, context, library):
    pinned, basis = context
    found = {}
    for snap in (pinned, *library.get(basis, ())):
        for entry in snap['content']['sites']:
            if entry['site_id'] != sid or entry['weather_sha256'] != weather:
                continue
            key = digest(entry)
            found.setdefault(key, (key, snap['name'] + ' · v' + str(snap['revision'])))
            if snap is pinned:
                return key, '已采用 · ' + found[key][1]
    if len(found) > 1:
        return None, '同一地点有多份不同的日历依据，需选择版本'
    if found:
        key, label = next(iter(found.values()))
        return key, '有匹配日历 · ' + label
    return None, ''


def local_member(reader, body):
    """Project a frozen group member onto one site. Never persist a per-site scheme."""
    store = reader.store
    group = saved_group(store,body.get('id'),body.get('group'))
    sid, cell = body.get('site'), body.get('cell')
    require(isinstance(sid,str) and sid in group['sites'] and type(cell) is int,'请选择本组的地点与工况。')
    member = next((m for m in group['members'] if m['cell']==cell),None)
    require(member is not None,'这项工况不在地区组内。')
    record = deepcopy(member['source'])
    site = group['sites'][sid]
    factors = record['factors']
    view = dict(label=cell_label(group['design'],cell),city=site['name'],climate=site['climate'],
                source=record['name'],revision=record['revision'],period=factors['scope']['period'],
                building=factors['building']['name'],step=record['numerics']['step_minutes'],ready=False)
    if sid not in store.catalog['sites'] or not store.catalog['sites'][sid].get('eligible'):
        return dict(view,note='当地气象尚待核对。')
    weather = weather_detail(sid,store.catalog)
    if weather.get('status')!='matches' or weather.get('actual_sha256')!=site['weather']:
        return dict(view,note='当地气象与派生时的记录不一致。')
    context = calendar_context(record,store.catalog)
    factors['scope']['site_ids'] = [sid]
    calendar = '无需光学切换日历'
    if context:
        pinned, basis = context
        options = [s for s in Library(store.root).all('calendar') if digest(s['content'].get('basis'))==basis]
        key, label = local_calendar(sid,site['weather'],context,{basis:options})
        if not key:
            return dict(view,note=label or '需先准备当地 W00 逐日参考与光学切换日历。')
        snapshot = next(s for s in (pinned,*options) if any(digest(row)==key for row in s['content']['sites']))
        ref = calendars.snapshot_reference(snapshot)
        calendars.bound(record,store.catalog,ref)
        for control in factors['condition']['controls']:
            if control.get('mode')=='calendar':control['reference_id']=ref['id']
        old = pinned['id']
        factors['condition']['reference_runs'] = [ref if r.get('id')==old else r for r in factors['condition']['reference_runs']]
        calendar = label
    require(shape(record)==shape(member['source']),'当地工况与来源版本的共同设置不一致。')
    return dict(view,ready=True,calendar=calendar,weather=site['weather'],
                recipe_sha256=digest(calculation_recipe(record)))


def daily_gaps(record, sites, catalog, root):
    """Use the registered W00 check, only rebuilding reference models for plausible candidates."""
    baseline = references.baseline(record)
    baseline['factors']['scope'].update(period=[1, 1, 12, 31], site_ids=sorted(sites))
    batches, jobs = references.queue_snapshot(root)
    check, pending = set(), set()
    for batch in batches:
        plan = loads(batch['plan'])
        possible = [c for c in plan['cases'] if c['site_id'] in sites and c['mode'] == 'controlled'
                    and c['period'] == [1, 1, 12, 31] and c['step_minutes'] == baseline['numerics']['step_minutes']]
        if not possible:
            continue
        _, saved, _ = references.frozen_batch(batch, root)
        for case in possible:
            sid = case['site_id']
            if not references.candidate(saved, baseline, case, sid):
                continue
            status = jobs.get((batch['id'], case['index']), {}).get('status')
            if status in ('passed', 'reused'):
                check.add(sid)
            elif status in ('review', 'pending', 'running'):
                pending.add(sid)
    notes = {s: ('W00 候选任务待完成或复核' if s in pending else '本地缺匹配的 W00 逐日参考') for s in sites}
    missing = set(sites) - pending
    if check:
        baseline['factors']['scope']['site_ids'] = sorted(check)
        report = references.build(baseline, catalog, root, accepted_only=True)
        for row in report['rows']:
            candidates = {c['daily']['csv_sha256'] for c in row['candidates']
                          if c['input_match'] and c['accepted'] and c['daily']['usable']}
            if report['issues'] or row['issues'] or any(c['status']=='blocked' for c in row['candidates']):
                notes[row['site_id']] = 'W00 逐日来源待核对'
            elif len(candidates) == 1:
                notes[row['site_id']] = '已有匹配 W00 逐日参考，待整理当地日历'
            elif len(candidates) > 1:
                notes[row['site_id']] = '多份 W00 逐日参考，待选择'
            else:
                continue
            missing.discard(row['site_id'])
    return notes, missing


def evidence(reader, candidates, site_ids):
    store = reader.store
    notes = []
    archives = pair_archives.for_members(reader, candidates, notes, min_matches=1) if candidates else []
    index = results.choice_index(store.root, {r['id'] for r in candidates}) if candidates else None
    observations = defaultdict(list)
    unread = set()
    for record in candidates:
        key = pair_archives.record_key(record)
        scope = record['factors']['scope']
        sites = site_ids.intersection(scope['site_ids'])
        options = results.choices(record, store.catalog, store.root, index)
        modes = record['factors']['condition']['operation']['mode']
        for mode in (('controlled','natural') if modes == 'both' else (modes,)):
            cases = [a['cases'][key] for a in archives if key in a['cases']]
            for option in options:
                if mode not in option['modes']:
                    continue
                data, note = source(record, options, option['id'], mode, store.catalog, store.root)
                if note:
                    unread.update((key, sid, mode) for sid in sites)
                if data:
                    cases.append(data['cases'])
            for rows in cases:
                for sid in sites.intersection(rows):
                    row = rows[sid]
                    if row['mode'] != mode:
                        continue
                    token = key, sid, mode
                    current_weather = (store.catalog['sites'].get(sid) or {}).get('weather') or {}
                    if (not current_weather.get('sha256') or row.get('weather_sha256') != current_weather['sha256']
                            or row.get('period') != scope['period'] or row.get('step_minutes') != record['numerics']['step_minutes']):
                        unread.add(token)
                        continue
                    observations[token].append(row)
    return observations, unread, notes


def availability(rows, uncertain):
    valid = [r for r in rows if r['status'] in ('passed', 'reused')]
    ids = {r.get('evidence', {}).get('result_sha256') or digest(r.get('evidence') or r) for r in valid}
    if len(ids) > 1:
        return 'check', '多份核验结果，待选择'
    if valid:
        return 'reuse', '可复用'
    states = {r['status'] for r in rows}
    for state, label in [('running','计算中'), ('pending','已排队'), ('review','待复核')]:
        if state in states:
            return 'existing', label
    if uncertain or states:
        return 'check', '已有任务或来源待核对'
    return 'needed', '缺研究算例'


def group_table(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='design_region_groups'").fetchone()


def saved_groups(store, design_id):
    with store.connect() as db:
        if not group_table(db):
            return []
        return [dict(row) for row in db.execute(
            'SELECT id,name,revision,member_count,site_count FROM design_region_groups WHERE design_id=? ORDER BY rowid DESC',
            (design_id,))]


def saved_group(store, design_id, ident):
    with store.connect() as db:
        row = db.execute('SELECT payload,checksum FROM design_region_groups WHERE design_id=? AND id=?',
                         (design_id,ident)).fetchone() if group_table(db) else None
    require(row is not None, '未找到这个地区研究组。')
    group = loads(row[0])
    require(digest(group)==row[1], '地区组保存内容校验失败。')
    return group


def design_selection(store, body):
    if body.get('group'):
        group = saved_group(store,body.get('id'),body['group'])
        return group['design'], {m['cell']:m['source'] for m in group['members']}, list(group['sites']), group
    with store.connect() as db:
        row = db.execute('SELECT payload FROM comparison_designs WHERE id=? ORDER BY revision DESC LIMIT 1',
                         (body.get('id'),)).fetchone()
    require(row is not None, '请先保存对照设计。')
    design = loads(row[0])
    require(type(body.get('revision')) is int and design['revision'] == body['revision'], '设计版本已变化，请重新打开。')
    cells, sites = body.get('cells'), body.get('sites')
    require(isinstance(cells,list) and len(cells)>=2 and all(type(i) is int and 0<=i<len(design['cells'])
            and design['cells'][i] for i in cells) and len(set(cells))==len(cells), '请选择至少两个有保存版本的工况。')
    registered_sites=registered(store.catalog)
    require(isinstance(sites,list) and sites and all(isinstance(s,str) and s in registered_sites for s in sites)
            and len(set(sites))==len(sites), '请选择已登记的地点，避免重复。')
    templates = {i:store.get(design['cells'][i]['id'],design['cells'][i]['revision']) for i in sorted(cells)}
    return design, templates, sorted(sites), None


def cell_label(design, index):
    axes = design['axes']
    return ' · '.join(axis['values'][(index >> (len(axes)-1-j)) & 1] for j,axis in enumerate(axes))


def preview(reader, body, *, saving=False, for_plans=False):
    store = reader.store
    catalog = store.catalog
    design, templates, sites, group = design_selection(store,body)
    site_pins = {}
    for sid in sites:
        site = catalog['sites'].get(sid) or {}
        site_pins[sid] = dict(name=site.get('name',sid),climate=site.get('climate'),
                              weather=(site.get('weather') or {}).get('sha256'))
    signatures = {i:shape(r) for i,r in templates.items()}
    selected = set(sites)
    candidates = {}
    with store.connect() as db:
        from itertools import chain
        for r in chain(store.catalog['records'].values(), (loads(row[0]) for row in db.execute('SELECT payload FROM versions'))):
            if selected.intersection(r['factors']['scope']['site_ids']) and shape(r) in signatures.values():
                candidates[(r['id'],r['revision'])] = r
    contexts, errors = {}, {}
    for r in {**candidates, **{(r['id'],r['revision']):r for r in templates.values()}}.values():
        pin = r['id'],r['revision']
        try:
            contexts[pin] = calendar_context(r,catalog)
        except (KeyError,ValueError,OSError) as exc:
            errors[pin] = str(exc)
    library = defaultdict(list)
    bases = {ctx[1] for ctx in contexts.values() if ctx}
    if bases:
        for snap in Library(store.root).all('calendar'):
            basis = digest(snap['content'].get('basis'))
            if basis in bases:
                calendars.verify_reference(calendars.snapshot_reference(snap))
                library[basis].append(snap)
    observed, unread, warnings = evidence(reader,list(candidates.values()),selected)
    matches = defaultdict(list)
    unresolved = set()
    for pin,r in candidates.items():
        sig, key = shape(r), pair_archives.record_key(r)
        for sid in selected.intersection(r['factors']['scope']['site_ids']):
            local = ''
            if pin in errors:
                unresolved.add((sid,sig))
                continue
            if contexts[pin]:
                snap, _ = contexts[pin]
                entries = [e for e in snap['content']['sites'] if e['site_id']==sid and
                           e['weather_sha256']==site_pins[sid]['weather']]
                if not entries:continue
                local = digest(entries[0])
            matches[(sid,sig,local)].append(key)
    counts, rows, daily = Counter(), [], defaultdict(set)
    basis_record = {}
    local_keys, missing_daily = {}, {}
    for sid in sites:
        site = catalog['sites'].get(sid) or {}
        try:
            checks = weather_detail(sid,catalog) if site.get('eligible') else {}
        except (ValueError,OSError):
            checks = {}
        weather = checks.get('actual_sha256') if checks.get('status')=='matches' else None
        expected = group['sites'][sid] if group else site_pins[sid]
        if expected['weather'] != weather:
            weather = None
        row = dict(site=sid,city=expected['name'],source_site=any(sid in t['factors']['scope']['site_ids'] for t in templates.values()),
                   cases=[],calendars={})
        rows.append(row)
        counted=set()
        for i,record in templates.items():
            pin = record['id'],record['revision']
            local, label = '', ''
            context=contexts.get(pin)
            if context and weather:
                snap,basis = context
                local,label = local_calendar(sid,weather,context,library)
                if not local and not label:
                    daily[basis].add(sid)
                    basis_record[basis] = record
                row['calendars'][(basis,local or label)] = label
                if for_plans and local:
                    local_keys[i,sid] = local
            modes = record['factors']['condition']['operation']['mode']
            keys = matches.get((sid,signatures[i],local),[])
            for mode in (('controlled','natural') if modes=='both' else (modes,)):
                data=[r for key in keys for r in observed[(key,sid,mode)]]
                if not weather:
                    kind, status = 'check','气象待核对'
                elif pin in errors:
                    kind, status = 'check', errors[pin]
                elif context and not local and label:
                    kind, status = 'check','当地日历待选择'
                else:
                    kind,status = availability(data, warnings or (sid,signatures[i]) in unresolved or any((k,sid,mode) in unread for k in keys))
                origins = []
                if kind == 'reuse':
                    for k in keys:
                        if any(h['status'] in ('passed','reused') for h in observed[(k,sid,mode)]):
                            origins.append(candidates[k[:2]]['name']+' · v'+str(k[1])+' · '+str(record['numerics']['step_minutes'])+' min')
                row['cases'].append(dict(cell=i,mode=mode,kind=kind,status=status,origins=origins))
                identity=(signatures[i],context[1] if context else '',local,mode)
                if identity not in counted:
                    counted.add(identity)
                    counts[kind]+=1
    for basis, ids in daily.items():
        try:
            notes, missing_daily[basis]=daily_gaps(basis_record[basis], ids, catalog, store.root)
        except (OSError,KeyError,ValueError) as exc:
            notes={sid:'W00 来源待核对 · '+str(exc) for sid in ids}
        for row in rows:
            if row['site'] in ids:row['calendars'][(basis,'')]=notes[row['site']]
    for row in rows:row['calendars']=list(dict.fromkeys(row['calendars'].values()))
    result = dict(rows=rows, counts=counts, warnings=list(dict.fromkeys(warnings)), calendar_gaps=sum(map(len,daily.values())), uses_calendar=bool(bases or errors),
                  members=[dict(cell=i,label=cell_label(design,i)) for i in sorted(templates)])
    if for_plans:
        require(group is not None,'请先选择已派生的地区组。')
        return result,group,contexts,library,local_keys,missing_daily
    # Member records are source snapshots. Site scope and optical calendars are resolved locally.
    source = dict(design={k:design[k] for k in ('id','revision','name','axes')}, sites=site_pins,
                  members=[dict(cell=i,source=templates[i]) for i in sorted(templates)])
    if group:
        result['group_name'] = group['name']
    else:
        result['preview_key'] = digest([digest(source),result])
    if saving:
        require(not group and result['preview_key']==body.get('preview_key'), '依据已变化，请重新核对地区预览后再保存。')
        return source
    return result


def derive(reader, body):
    name = body.get('name')
    require(isinstance(name,str) and 0<len(name.strip())<=100,'请填写 1 至 100 字的地区组名称。')
    source = preview(reader,body,saving=True)
    design = source['design']
    ident = 'region_' + digest(source)
    with reader.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        head = db.execute('SELECT MAX(revision) FROM comparison_designs WHERE id=?',(design['id'],)).fetchone()
        require(head[0]==design['revision'],'原设计版本已变化，请重新核对后再保存。')
        db.execute('CREATE TABLE IF NOT EXISTS design_region_groups (id TEXT PRIMARY KEY, design_id TEXT NOT NULL, '
                   'revision INTEGER NOT NULL, name TEXT NOT NULL, member_count INTEGER NOT NULL, site_count INTEGER NOT NULL, '
                   'payload TEXT NOT NULL, checksum TEXT NOT NULL)')
        row = db.execute('SELECT name FROM design_region_groups WHERE id=?',(ident,)).fetchone()
        if row:
            return dict(id=ident,name=row[0],created=False)
        group = dict(source,name=name.strip(),created=now())
        db.execute('INSERT INTO design_region_groups VALUES (?,?,?,?,?,?,?,?)',
                   (ident,design['id'],design['revision'],group['name'],len(source['members']),len(source['sites']),canonical(group),digest(group)))
        return dict(id=ident,name=group['name'],created=True)
