"""Exterior wall coverage and thermal groups on a pinned physical material."""
import copy
import math

from ordinary_materials import measure


def available(record):
    f = record['factors']
    definitions = f['materials'].get('definitions', [])
    applications = f['materials'].get('applications', [])
    return (record.get('provenance', {}).get('adapter') in ('global_frozen_v011', 'ordinary_building_v1')
            and len(definitions) == len(applications) == 1
            and definitions[0]['model'] == 'solid_variable_v1'
            and applications[0].get('placement_basis') == 'fixed_surface_material_v1'
            and bool(applications[0]['target_ids']))

def fixed_partial(record):
    f=record['factors'];apps=f['materials']['applications'];walls=f['building'].get('wall_ids',[])
    if (len(apps)==1 and apps[0].get('placement_basis')=='legacy_outer_equivalent_model'
            and set(apps[0]['target_ids'])<set(walls) and not f['condition']['reference_runs']
            and all(c['mode']=='fixed' for c in f['condition']['controls'])):
        from surface_materials import FIXED_MOVABLE
        a=apps[0]
        if a.get('position')!='exterior' or a.get('component')!='wall':
            raise ValueError('活动保温层的应用位置必须是室外墙面。')
        out=copy.deepcopy(record)
        out['factors']['materials']['applications']=[dict(id=a['id'],material_id=a['material_id'],
            component='opaque_exterior',position='exterior',placement_basis=FIXED_MOVABLE,target_ids=list(a['target_ids']))]
        return out
    return record


def select(record, wall_ids, covered, feedback_ids):
    from contracts import normalize
    from surface_controls import thermal_groups
    record = normalize(record)
    from surface_materials import enabled
    f=record['factors']
    fixed_equivalent=(len(f['materials']['definitions'])==len(f['materials']['applications'])==1
        and f['materials']['definitions'][0]['model']=='equivalent_resistance_no_layer_storage'
        and all(c['mode']=='fixed' for c in f['condition']['controls']) and not f['condition']['reference_runs'])
    apps=f['materials']['applications']
    legacy=len(apps)==1 and apps[0].get('placement_basis')=='legacy_outer_equivalent_model'
    if not (enabled(record) or fixed_equivalent or legacy) or len(apps) != 1:
        raise ValueError('请先选用一份可逐墙铺设的外表面材料。')
    if any(not isinstance(ls, list) or len(set(ls)) != len(ls) for ls in (covered, feedback_ids)):
        raise ValueError('选墙清单须由不重复的墙号组成。')
    if not covered or not set(covered) <= set(wall_ids) or not set(feedback_ids) <= set(covered):
        raise ValueError('请至少铺设一段室外墙，反馈组只能从已铺墙中选择。')
    if not set(record['factors']['materials']['applications'][0]['target_ids']) <= set(wall_ids):
        raise ValueError('当前材料应用包含屋面。请在材料库单独选用外墙，再按墙段调整。')
    if f['materials']['definitions'][0]['model']=='layer_stack_v1':
        from composite_materials import configure_feedback
        previous=next((c for c in f['condition']['controls'] if c['mode']=='feedback'),{})
        ordered=[w for w in wall_ids if w in covered]
        return configure_feedback(record,previous.get('layer_number'),feedback_ids,ordered)
    if fixed_equivalent:
        if feedback_ids:raise ValueError('固定热学状态不使用反馈墙组。')
        from surface_materials import fixed_assignments
        app=f['materials']['applications'][0]
        initial=fixed_assignments(record)
        ids=[wall for wall in wall_ids if wall in covered]
        out=copy.deepcopy(record)
        out['factors']['materials']['applications'][0]['target_ids']=ids
        controls=[]
        for i,(channel,key,default) in enumerate((('thermal','state_id','R'),('orientation','face_id','A'))):
            existing={values[i] for values in initial.values()}
            fallback=next(iter(existing)) if len(existing)==1 else default
            groups={}
            for wall in ids:
                value=initial[wall][i] if wall in initial else fallback
                groups.setdefault(value,[]).append(wall)
            for value,walls in groups.items():
                controls.append(dict(application_id=app['id'],channel=channel,mode='fixed',target_ids=walls,**{key:value}))
        out['factors']['condition']['controls']=controls
        return out
    if legacy:
        app=apps[0];wanted=set(covered)
        active={w for c in f['condition']['controls'] if c['channel']=='thermal' and c['mode']=='feedback' for w in c['target_ids']}
        if set(feedback_ids)!=active&wanted:raise ValueError('请在材料控制中选择反馈墙段。')
        added=[w for w in wall_ids if w in wanted and w not in app['target_ids']]
        out=copy.deepcopy(record)
        out['factors']['materials']['applications'][0]['target_ids']=[w for w in wall_ids if w in wanted]
        controls=[]
        for c in f['condition']['controls']:
            keep=[w for w in c['target_ids'] if w in wanted]
            if keep:controls.append({**copy.deepcopy(c),'target_ids':keep})
        if added:
            controls.append(dict(application_id=app['id'],target_ids=added.copy(),channel='thermal',mode='fixed',state_id='R'))
            orientations=[c for c in f['condition']['controls'] if c['channel']=='orientation']
            orientation=orientations[0] if len(orientations)==1 else dict(application_id=app['id'],channel='orientation',mode='fixed',face_id='A')
            controls.append({**copy.deepcopy(orientation),'target_ids':added.copy()})
        out['factors']['condition']['controls']=controls
        return out
    groups, optical = thermal_groups(record)
    if not available(record):
        if feedback_ids or len(groups) != 1 or groups[0]['mode'] != 'fixed':
            raise ValueError('此材料使用固定热学状态，请只选择铺设墙段。')
        targets = [wall for wall in wall_ids if wall in covered]
        out = copy.deepcopy(record)
        out['factors']['materials']['applications'][0]['target_ids'] = targets
        for control in out['factors']['condition']['controls']:
            control['target_ids'] = targets.copy()
        return out
    previous = next((c for c in groups if c['mode'] == 'feedback'), None)
    d = record['factors']['materials']['definitions'][0]
    high = max(d['states'], key=lambda s: s['resistance_m2K_W'])['id']
    fixed = next((c['state_id'] for c in groups if c['mode'] == 'fixed'), high)
    # A newly enabled feedback split leaves passive surfaces in the high-R state.
    if feedback_ids and previous is None:
        fixed = high
    out = copy.deepcopy(record)
    app = out['factors']['materials']['applications'][0]
    covered = [w for w in wall_ids if w in covered]
    active = [w for w in covered if w in feedback_ids]
    passive = [w for w in covered if w not in feedback_ids]
    app['target_ids'] = covered
    cond = out['factors']['condition']
    controls = []
    if active:
        tc = copy.deepcopy(previous) if previous else dict(
            channel='thermal', application_id=app['id'], mode='feedback', state_id='C',
            rule='UNIFIED', reference_step_minutes=record['numerics']['step_minutes'],
            policy=dict(cold_C=18, hot_C=26, flux_deadband_W_m2=1, minimum_hold_minutes=60),
            update=dict(kind='minutes', minutes=5))
        tc['target_ids'] = active
        controls.append(tc)
        out['numerics']['step_minutes'] = 1
    elif previous:
        out['numerics']['step_minutes'] = previous['reference_step_minutes']
    if passive:
        controls.append(dict(channel='thermal', application_id=app['id'], mode='fixed', state_id=fixed, target_ids=passive))
    cond['controls'] = [*controls, {**copy.deepcopy(optical), 'target_ids': covered}]
    if any(c['mode'] != 'fixed' for c in cond['controls']):
        from surface_controls import controls as validate_controls
        validate_controls(out)
    return out


def exterior_walls(model, conditioned):
    from surface_materials import target_rows
    surfaces = model['BuildingSurface:Detailed']
    openings = {}
    for opening in model.get('FenestrationSurface:Detailed', {}).values():
        openings.setdefault(opening['building_surface_name'], []).append(opening)
    rows = []
    for target in target_rows(model):
        if target['type'] != 'Wall':
            continue
        ident, zone = target['id'], target['zone']
        gross, _ = measure(surfaces[ident])
        area = gross - math.fsum(measure(h)[0] * h.get('multiplier', 1) for h in openings.get(ident, []))
        if area < -1e-6:
            raise ValueError(f'{ident} 洞口面积超过墙面面积，请核对模型。')
        rows.append(dict(id=ident, zone=zone, net_m2=round(max(0, area), 6), conditioned=conditioned.get(zone)))
    return rows


def rows(record, catalog):
    from building_configuration import baseline
    from model_adapter import VerifiedReader
    reader = VerifiedReader(catalog)
    usage, model, _ = baseline(catalog, reader, record['factors']['building']['id'])
    walls = exterior_walls(model, {r['zone']:r['conditioned'] for r in usage['rooms']})
    reader.unchanged()
    return walls


def generated(record, original, model, material_audit, conditioned=None):
    assignments = {r['surface']: r for r in material_audit['surfaces']}
    f = record['factors']
    if conditioned is None:
        thermostats = {z['zone_or_zonelist_name'] for z in original.get('ZoneControl:Thermostat', {}).values()}
        conditioned = {zone:zone in thermostats for zone in original.get('Zone', {})}
    controls = {wall: c for c in f['condition']['controls'] if c['channel']=='thermal' for wall in c['target_ids']}
    orientation = next(c for c in f['condition']['controls'] if c['channel']=='orientation')
    if set(assignments) != set(controls):
        raise ValueError('生成的材料表面与已保存的热学范围不一致。')
    rows = []
    for entry in exterior_walls(original, conditioned):
        wall = entry['id']
        base = original['BuildingSurface:Detailed'][wall]
        dest = model['BuildingSurface:Detailed'][wall]
        c = controls.get(wall)
        if not c:
            construction = base['construction_name']
            if dest != base or original['Construction'][construction] != model['Construction'][construction]:
                raise ValueError('未铺墙的构造发生变化：'+wall)
            for layer in original['Construction'][construction].values():
                for kind in ('Material','Material:NoMass','Material:AirGap'):
                    if layer in original.get(kind,{}) and original[kind][layer] != model[kind][layer]:
                        raise ValueError('未铺墙的基础材料参数发生变化：'+wall)
        rows.append(dict(**entry, covered=bool(c), thermal=c['mode'] if c else None,
                         state=c['state_id'] if c else None, optical=orientation['mode'] if c else None,
                         face=orientation.get('face_id') if c else None,
                         baseline=base['construction_name'], construction=dest['construction_name']))
    covered = [w for w in rows if w['covered']]
    feedback = [w for w in covered if w['thermal'] == 'feedback']
    return dict(rows=rows, covered_m2=round(math.fsum(w['net_m2'] for w in covered),6),
                feedback_m2=round(math.fsum(w['net_m2'] for w in feedback),6))
