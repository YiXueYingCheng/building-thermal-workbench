"""An ordered assembly of immutable material versions, separate from its installation."""
from component_library import verify
from foundation import canonical, loads, digest
import research_materials as research

MODEL = 'layer_stack_v1'
LEAVES = {'optical_surface_v1', 'solid_layer_v1', 'solid_variable_v1', research.PCM}
STATE = {'id': 'R', 'name': '各层固定状态'}


def template():
    return dict(id='user_stack', name='', kind='layer_stack', category='stack', model=MODEL,
                state_identity='independent', states=[STATE.copy()], faces=['A'], optics_depend_on_state=False,
                optics={}, layers=[], property_source=dict(method='source_reference', note='各层采用所列材料版本。'),
                source_note='')


def resolve(d, library):
    """Resolve new selections once. Previously frozen rows survive removal from the source library."""
    for item in d.get('layers', []):
        if not isinstance(item, dict):
            raise ValueError('组合层条目无效。')
        if 'reference' in item:
            ref = item['reference']
            if not isinstance(ref, dict) or set(ref) != {'id', 'revision', 'sha256'} or 'version' in item:
                raise ValueError('请选择明确的材料版本。')
            row = library.version('material', ref['id'], ref['revision'])
            if row is None or row['sha256'] != ref['sha256']:
                raise ValueError('所选层的材料版本已变化，请重新选择。')
            del item['reference']
            item['version'] = canonical(row)
    layers = unpack(d)
    d['optics'] = {'A_R': layers[0]['optics'].copy()}
    return d


def unpack(d):
    import material_types
    items = d.get('layers')
    if not isinstance(items, list) or len(items) < 2 or len(items) > 10:
        raise ValueError('请选择至少两层。每面构件与原构造合计最多十个实体层。')
    parts = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict) or set(item) != {'version', 'state', 'face'} or not isinstance(item['version'], str):
            raise ValueError(f'第 {n} 层缺少完整的材料版本。')
        row = verify(loads(item['version']), 'material')
        leaf = row['content']
        kind = leaf.get('model')
        if kind not in LEAVES:
            raise ValueError(f'第 {n} 层需要实体材料、相变材料或表面涂层。')
        if kind == 'optical_surface_v1' and n != 1:
            raise ValueError('纯光学涂层须放在组合的最外侧。')
        errors = material_types.validate(leaf, complete=True)
        if errors:
            raise ValueError(f'第 {n} 层「{row["name"]}」：'+ '；'.join(errors))
        state = next((s for s in leaf['states'] if s['id'] == item['state']), None)
        face = item['face']
        if state is None or face not in leaf['faces']:
            raise ValueError(f'第 {n} 层的状态或光学面与材料版本不符。')
        suffix = '_'+(state['id'] if leaf['optics_depend_on_state'] else 'R')
        reverse = next((f for f in leaf['faces'] if f != face), face)
        parts.append(dict(row=row, leaf=leaf, state=state, face=face,
                          optics=leaf['optics'].get(face+suffix, {}), inside=leaf['optics'].get(reverse+suffix, {})))
    return parts


def validate(d):
    try:
        expected = template()
        if set(d) != set(expected) or any(d[k] != expected[k] for k in
                ('kind','category','model','state_identity','states','faces','optics_depend_on_state','property_source')):
            raise ValueError('组合材料的固定定义无效。')
        if d['optics'] != {'A_R': unpack(d)[0]['optics']}:
            raise ValueError('组合的外表面参数与第一层版本不一致。')
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return [str(exc)]
    return []


def has_pcm(d):
    return d.get('model') == MODEL and any(p['leaf']['model'] == research.PCM for p in unpack(d))


def outer_optics(part, face):
    leaf=part['leaf']
    if face not in leaf['faces']:
        raise ValueError('组合最外层的保存版本未登记该光学组。')
    state=part['state']['id'] if leaf['optics_depend_on_state'] else 'R'
    values=leaf['optics'].get(face+'_'+state,{})
    if any(values.get(k) is None for k in ('solar_absorptance','emissivity')):
        raise ValueError(f'最外层 {face} 组需要完整的太阳吸收率和长波发射率。')
    return values


def calendar_step(control):
    value=control['calendar_step_minutes']
    if type(value) is not int or value not in (1,2,5,10,15,30,60):
        raise ValueError('原墙参考步长需选用支持的分钟数。')
    return value

def feedback_layer(definition, application, number, outer_face=None):
    parts = unpack(definition)
    if type(number) is not int or not 1 <= number <= len(parts):
        raise ValueError('请选择已保存组合中的一层。')
    part = parts[number-1]
    d = part['leaf']
    if d['model'] != 'solid_variable_v1':
        raise ValueError('反馈层须为已保存的两态实体材料。')
    # The feedback actuator changes conductivity only. Preserve both exposed optical boundaries.
    outside = number == 1 and application['position'] == 'exterior'
    inside = number == len(parts) and application['position'] == 'interior'
    if d['optics_depend_on_state'] and (outside or inside):
        face = (outer_face or part['face']) if outside else next((f for f in d['faces'] if f != part['face']),part['face'])
        for key in ('emissivity','solar_absorptance','visible_absorptance'):
            if d['optics'].get(face+'_R',{}).get(key) != d['optics'].get(face+'_C',{}).get(key):
                raise ValueError('此层暴露面的光学参数随热学状态变化，当前组合反馈需要固定的边界光学参数。')
    solid_index = number-1-int(parts[0]['leaf']['model']=='optical_surface_v1')
    return part, solid_index


def configure_feedback(record, layer_number, active_targets, covered=None):
    import copy
    from surface_controls import thermal_groups, controls as validate_controls
    out = copy.deepcopy(record)
    f = out['factors']
    m = f['materials']
    if len(m['definitions'])!=1 or m['definitions'][0]['model'] != MODEL:
        raise ValueError('请选择组合材料方案。')
    groups, optical = thermal_groups(out)
    app = m['applications'][0]
    previous = next((g for g in groups if g['mode']=='feedback'), None)
    if covered is not None:
        app['target_ids'] = list(covered)
    targets = app['target_ids']
    if (not isinstance(active_targets,list) or any(not isinstance(t,str) for t in active_targets)
            or len(set(active_targets))!=len(active_targets) or not set(active_targets)<=set(targets)):
        raise ValueError('反馈范围必须从已铺构件中选择，且同一构件只选一次。')
    active = set(active_targets)
    base = dict(channel='thermal',application_id=app['id'],state_id='R')
    updated = []
    if active:
        tc = copy.deepcopy(previous) if previous else dict(**base,mode='feedback',rule='UNIFIED',
            reference_step_minutes=out['numerics']['step_minutes'],
            policy=dict(cold_C=18,hot_C=26,flux_deadband_W_m2=1,minimum_hold_minutes=60),
            update=dict(kind='minutes',minutes=5))
        tc.update(layer_number=layer_number,target_ids=[t for t in targets if t in active])
        updated.append(tc)
        out['numerics']['step_minutes']=1
    elif previous:
        out['numerics']['step_minutes']=previous['reference_step_minutes']
    passive = [t for t in targets if t not in active]
    if passive:
        updated.append(dict(**base,mode='fixed',target_ids=passive))
    f['condition']['controls'] = [*updated, {**optical,'target_ids':targets.copy()}]
    if active or optical['mode']=='calendar':
        validate_controls(out)
    return out


def install(model, spec, application):
    parts = unpack(spec['definition'])
    if 'outer_face' in spec:
        parts[0]['optics']=outer_optics(parts[0],spec['outer_face'])
    coating = parts[0]['leaf']['model'] == 'optical_surface_v1'
    position = application['position']
    if coating and position != 'exterior':
        raise ValueError('纯外表面涂层需要面向室外。内侧或层间铺设可选用实体层组合。')
    solids = parts[int(coating):]
    surfaces = []
    for target in spec['targets']:
        surface = model['BuildingSurface:Detailed'][target]
        if any(v.get('surface_name') == target for v in model.get('SurfaceControl:MovableInsulation', {}).values()):
            raise ValueError(f'{target} 已有活动保温层，请先核对组合。')
        old = surface['construction_name']
        c = model['Construction'][old]
        keys = ['outside_layer'] + [f'layer_{i}' for i in range(2, len(c)+1)]
        if set(keys) != set(c):
            raise ValueError(f'{target} 原构造层序无法解析。')
        original = [c[k] for k in keys]
        index = 0 if position == 'exterior' else len(original) if position == 'interior' else application['after_layer']
        if position == 'between' and not 0 < index < len(original):
            raise ValueError(f'{target} 原构造共 {len(original)} 层，无法插在第 {index} 层之后。')
        if len(original)+len(solids) > 10:
            raise ValueError(f'{target} 组合后超过 EnergyPlus 的十层上限。')
        def visible(key, inside=False):
            base = next((model[k][key] for k in ('Material','Material:NoMass') if key in model.get(k,{})), {})
            return base.get('visible_absorptance_inside_face',base.get('visible_absorptance',.7)) if inside else base.get('visible_absorptance',.7)
        prefix = 'NX_Stack_'+digest([target, spec['definition'], position, index])[:24]
        cname = prefix+'_Construction'
        names = []
        for i, p in enumerate(solids):
            name = prefix+'_'+str(i+1)
            if name in model.setdefault('Material',{}) or cname in model['Construction']:
                raise ValueError('组合层名称与原模型冲突。')
            s = p['state']
            outer = parts[0]['optics'] if coating and i == 0 else p['optics']
            inner = p['inside']
            material = dict(roughness='MediumSmooth', thickness=s['thickness_mm']/1000,
                            conductivity=s['conductivity_W_mK'], density=s['density_kg_m3'],
                            specific_heat=s['specific_heat_J_kgK'])
            for opt, suffix, default in ((outer,'',visible(original[0])), (inner,'_inside_face',visible(original[-1],True))):
                exposed = ((not suffix and i == 0 and position == 'exterior') or
                           (suffix and i == len(solids)-1 and position == 'interior'))
                for field, key, fallback in (('solar_absorptance','solar_absorptance',.7), ('thermal_absorptance','emissivity',.9)):
                    value = opt.get(key)
                    if exposed and value is None:
                        raise ValueError(f'{target} 暴露面的太阳吸收率与长波发射率须填全。')
                    material[field+suffix] = fallback if value is None else value
                v = opt.get('visible_absorptance')
                material['visible_absorptance'+suffix] = default if v is None else v
            model['Material'][name] = material
            if p['leaf']['model'] == research.PCM:
                research.pcm_layer(model, name, cname, s, p['leaf'])
            names.append(name)
        after = original[:index] + names + original[index:]
        model['Construction'][cname] = dict(outside_layer=after[0], **{f'layer_{i}':x for i,x in enumerate(after[1:],2)})
        surface['construction_name'] = cname
        surfaces.append(dict(surface=target, original=old, construction=cname, layers_before=original,
                             layers_after=after, inserted_after=index, inserted_layers=names))
    return dict(model=MODEL, state='R', state_name=STATE['name'], face=spec.get('outer_face',parts[0]['face']), position=position,
                **({'outer_face':spec['outer_face']} if 'outer_face' in spec else {}),
                layers=[dict(name=p['row']['name'], revision=p['row']['revision'], sha256=p['row']['sha256'],
                             model=p['leaf']['model'], state=p['state']['id'], face=p['face']) for p in parts],
                surfaces=surfaces, note='按所选层序与固定状态写入构造，各层分别传热。')
