"""Preview selected wall observations and save them together in one target version."""
from copy import deepcopy
from datetime import date

import composite_materials
from contracts import record_digest
from foundation import digest
from navigation_cache import geometry
from wall_observations import FREQUENCIES, METRICS


def require(ok, message):
    if not ok:
        raise ValueError(message)


def installed_layers(record, wall):
    materials = record['factors']['materials']
    definitions = {d['id']: d for d in materials['definitions']}
    result = []
    for app in materials['applications']:
        definition = definitions[app['material_id']]
        if wall not in app['target_ids'] or definition.get('model') != composite_materials.MODEL:
            continue
        require(not result, '同一墙面有多组分层定义，请先核对铺设。')
        for i, part in enumerate(composite_materials.unpack(definition), 1):
            row = part['row']
            if part['leaf']['model'] != 'optical_surface_v1':
                result.append(dict(layer=i, sha256=row['sha256'], name=row['name'], revision=row['revision'], id=row['id']))
    return result


def wall_zones(record, catalog, root, walls):
    g = geometry(record, catalog, root)
    rows = [w for w in g.get('walls', []) if w['exterior']]
    if not g.get('supported') or set(walls).intersection(g.get('unplotted_walls', [])):
        from model_adapter import compile_case, VerifiedReader
        from surface_materials import baseline, target_rows
        base = baseline(record)
        reader = VerifiedReader(catalog)
        model, _ = compile_case(base, base['factors']['scope']['site_ids'][0], catalog, reader)
        reader.unchanged()
        rows = [w for w in target_rows(model) if w['type'] == 'Wall']
    wanted = set(walls)
    zones = {}
    for row in rows:
        wall = row['id']
        if wall in wanted:
            require(wall not in zones and row.get('zone'), wall+' 的房间不明确，请核对这面外墙。')
            zones[wall] = row['zone']
    missing = wanted.difference(zones)
    require(not missing, '未能核实外墙及所属房间：'+'、'.join(sorted(missing)))
    return zones


def merge(source, target, request, zone, execution=None):
    wall, fields, layers = (request[k] for k in ('wall','fields','layers'))
    require(isinstance(fields,list) and all(f in METRICS for f in fields) and len(set(fields))==len(fields), '墙面观测量无效。')
    require(isinstance(layers,list) and (layers or fields), '请先选定至少一个测点。')
    if execution is None:
        execution = deepcopy(target['execution'])
    building = target['factors']['building']['id']
    config = execution.get('wall_observations') or {}
    points = config.get('points', [])
    frequency = request['frequency']
    frequency_note=''
    require(frequency in FREQUENCIES, '测点频率无效。')
    if fields:
        require(not points or config.get('building_id')==building, '目标方案已有另一栋建筑的测点，请先核对。')
        existing_points = (target['execution'].get('wall_observations') or {}).get('points')
        if existing_points:
            frequency = config['frequency']
            if frequency!=request['frequency']:
                frequency_note='目标已有墙面测点，继续使用这些测点共用的保存频率。'
        period = target['factors']['scope']['period']
        days = (date(2025,*period[2:])-date(2025,*period[:2])).days+1
        if frequency=='Timestep' and days>31:
            require(not existing_points, '目标方案的逐步测点超过 31 天，请先核对已有设置。')
            frequency='Hourly'
            frequency_note='目标时段超过 31 天，墙面与房间采用逐时保存。'
        point = next((p for p in points if p['wall']==wall), None)
        if point:
            require(not point.get('zone') or point['zone']==zone, '目标已有测点的房间与实际几何不符。')
            point['fields'] = list(dict.fromkeys([*point['fields'], *fields]))
        else:
            points.append(dict(wall=wall, zone=zone, fields=fields))
        execution['wall_observations'] = dict(config, building_id=building,points=points,frequency=frequency)
    applied, skipped = [], []
    if layers:
        original = installed_layers(source,wall)
        available = installed_layers(target,wall)
        same_layout = original==available
        selected = list(execution.get('stack_response',[]))
        for item in layers:
            part = next((p for p in original if (p['layer'],p['sha256'])==(item['layer'],item['sha256'])),None)
            require(part is not None,'源方案的已保存材料版本与所选层不符，请先保存材料配置。')
            label = part['name']+' · v'+str(part['revision'])
            matches = [p for p in available if p['sha256']==part['sha256'] and (not same_layout or p['layer']==part['layer'])]
            if len(matches)!=1:
                reason = '同一版本重复铺设，层位无法唯一对应' if matches else (
                    '材料版本不同' if any(p['id']==part['id'] for p in available) else '无此材料层')
                skipped.append(dict(label=label,reason=reason))
                continue
            n = matches[0]['layer']
            point = dict(wall=wall, layer=n, sha256=part['sha256'])
            prior = next((p for p in selected if p['wall']==wall and p['layer']==n),None)
            if prior and prior!=point:
                skipped.append(dict(label=label,reason='目标层已有不同版本的测点，请先核对'))
                continue
            if not prior:selected.append(point)
            applied.append(dict(label=label,layer=n))
        if applied:execution['stack_response']=selected
    return execution,dict(fields=fields,frequency=frequency,frequency_note=frequency_note,applied=applied,skipped=skipped)


def handle(root, catalog, store, request):
    src,dst=request['source'],request['target']
    require((src['id'],src['revision'])!=(dst['id'],dst['revision']), '请选择另一份方案或保存版本。')
    source=store.get(src['id'],src['revision'])
    target=store.get(dst['id'],dst['revision'])
    require(source['factors']['building']['id']==target['factors']['building']['id'], '两侧需要采用同一栋建筑。')
    legacy = 'walls' not in request
    selections = [request] if legacy else request['walls']
    require(isinstance(selections, list) and selections, '请至少选择一面已设置测点的墙。')
    require(all(isinstance(item, dict) and isinstance(item.get('wall'), str) and item['wall']
                for item in selections), '待复用的墙号无效。')
    walls = [item['wall'] for item in selections]
    require(len(set(walls)) == len(walls), '同一面墙只能选择一次。')
    source_zones = wall_zones(source, catalog, root, walls)
    target_zones = wall_zones(target, catalog, root, walls)
    execution = deepcopy(target['execution'])
    results = []
    for item in selections:
        wall = item['wall']
        zone = source_zones[wall]
        require(target_zones[wall] == zone, wall+' 在两侧方案中的所属房间不同。')
        _, info = merge(source, target, dict(item, frequency=request['frequency']), zone, execution)
        results.append(dict(info, wall=wall, zone=zone))
    current=store.get(dst['id'])
    clone=(target['status']!='draft' or target['revision']!=current['revision'] or target['id'] in store.member_owners())
    changed=execution!=target['execution']
    def signature_for(latest,copy_target):
        identity = [src,source.get('record_sha256'),dst,latest,target.get('record_sha256')]
        if legacy:
            return digest([*identity,wall,zone,execution,copy_target,info])
        return digest([*identity,execution,copy_target,results])
    signature=signature_for(current['revision'],clone)
    out=dict(results[0] if legacy else {'walls': results},step=target['numerics']['step_minutes'],changed=changed,clone=clone,signature=signature)
    if request.get('action')=='preview':return out
    require(request.get('action')=='apply','请选择预览或保存。')
    if request.get('signature')!=signature:
        # A successful save may have lost its HTTP reply. Only accept the exact resulting snapshot.
        retry=(target['status']=='draft' and current['revision']!=target['revision'] and
               request.get('signature')==signature_for(target['revision'],False) and
               record_digest(store.update_payload(target,dict(execution=execution)))==record_digest(current))
        require(retry,'目标或选择已变化，请重新核对复用预览。')
        return dict(out,clone=False,saved=dict(id=current['id'],revision=current['revision']))
    if not changed:return out
    if clone:
        out_record=store.update_payload(target,dict(execution=execution,name=target['name'][:89]+' · 测点对照'))
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(store.get(dst['id'])['revision']==current['revision'],'目标版本有更新，请重新预览。')
            db.execute('CREATE TABLE IF NOT EXISTS probe_copies(signature TEXT PRIMARY KEY, record_id TEXT NOT NULL)')
            existing=db.execute('SELECT v.id,v.revision FROM probe_copies p JOIN versions v ON v.id=p.record_id WHERE p.signature=? AND v.revision=1',(signature,)).fetchone()
            if existing:return dict(out,saved=dict(existing))
            saved=store.insert_draft(db,target,out_record)
            db.execute('INSERT OR REPLACE INTO probe_copies VALUES(?,?)',(signature,saved['id']))
    else:
        saved=store.save(dst['id'],dst['revision'],dict(execution=execution))
    return dict(out,saved=dict(id=saved['id'],revision=saved['revision']))
