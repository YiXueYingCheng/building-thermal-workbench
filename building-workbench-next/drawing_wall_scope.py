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


def select(record, wall_ids, covered, feedback_ids):
    from contracts import normalize
    from surface_controls import thermal_groups
    record = normalize(record)
    if not available(record):
        raise ValueError('请先从材料库选用双状态实体材料并应用到室外墙。')
    if any(not isinstance(ls, list) or len(set(ls)) != len(ls) for ls in (covered, feedback_ids)):
        raise ValueError('选墙清单须由不重复的墙号组成。')
    if not covered or not set(covered) <= set(wall_ids) or not set(feedback_ids) <= set(covered):
        raise ValueError('请至少铺设一段室外墙，反馈组只能从已铺墙中选择。')
    if not set(record['factors']['materials']['applications'][0]['target_ids']) <= set(wall_ids):
        raise ValueError('当前材料应用包含屋面。请在材料库单独选用外墙，再按墙段调整。')
    groups, optical = thermal_groups(record)
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
