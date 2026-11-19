"""Site calendar and heat-flux feedback for a scheme's selected physical surface layers."""
import copy
import math
from foundation import digest
from ordinary_materials import measure


def active(record):
    return any(c['mode'] != 'fixed' for c in record['factors']['condition']['controls'])


def fixed(record):
    """Use the same material and targets to assemble the initial construction."""
    r = copy.deepcopy(record)
    cond = r['factors']['condition']
    cond['reference_runs'] = []
    for c in cond['controls']:
        c['mode'] = 'fixed'
        for key in ('reference_id', 'rule', 'policy', 'update','reference_step_minutes'):
            c.pop(key, None)
    return r


def thermal_groups(record):
    f = record['factors']
    apps = f['materials']['applications']
    if len(apps) != 1:
        raise ValueError('请选择一项外表面材料应用。')
    targets = apps[0]['target_ids']
    controls = f['condition']['controls']
    optical = [c for c in controls if c['channel'] == 'orientation']
    groups = [c for c in controls if c['channel'] == 'thermal']
    if (len(optical) != 1 or len(groups) + 1 != len(controls)
            or sorted(optical[0]['target_ids']) != sorted(targets)
            or any(c['application_id'] != apps[0]['id'] for c in controls)):
        raise ValueError('光学设置须覆盖全部已铺表面，控制应绑定当前材料应用。')
    assigned = [t for c in groups for t in c['target_ids']]
    if (not targets or len(set(targets)) != len(targets) or sorted(assigned) != sorted(targets)
            or any(not c['target_ids'] for c in groups)):
        raise ValueError('每面已铺墙须恰好属于一个热学分组。')
    if len(groups) != 1:
        if len(groups) != 2 or {c['mode'] for c in groups} != {'fixed', 'feedback'}:
            raise ValueError('支持一个统一反馈组和一个固定热阻组。')
        groups.sort(key=lambda c: c['mode'] != 'feedback')
    return groups, optical[0]


def group_record(record, group, optical):
    """Project onto a single partition, preserving the material and physical state."""
    r = copy.deepcopy(record)
    targets = list(group['target_ids'])
    r['factors']['materials']['applications'][0]['target_ids'] = targets
    r['factors']['condition']['controls'] = [copy.deepcopy(group), {**optical, 'target_ids': targets}]
    return r


def initial_application(model, record):
    from surface_materials import apply
    groups, optical = thermal_groups(record)
    audits = []
    for group in groups:
        initial = fixed(group_record(record, group, optical)) if len(groups) > 1 else fixed(record)
        audit = apply(model, initial)
        for row in audit['surfaces']:
            row.update(thermal_mode=group['mode'], initial_state=group['state_id'], orientation_mode=optical['mode'])
        audits.append(audit)
    result = audits[0]
    if len(audits) > 1:
        result['surfaces'].extend(audits[1]['surfaces'])
        result.update(state='per_surface', state_name='逐墙分组', physical=None)
    return result


def controls(record):
    from calendar_library import active_references
    from surface_materials import specification
    groups, oc = thermal_groups(record)
    tc = groups[0]
    spec = specification(fixed(group_record(record, tc, oc))) if len(groups) > 1 else specification(fixed(record))
    if len(groups) > 1:
        specification(fixed(group_record(record, groups[1], oc)))
        if set(groups[1]) != {'application_id','channel','mode','target_ids','state_id'}:
            raise ValueError('固定热阻分组含有未支持的控制字段。')
    d = spec['definition']
    cond = record['factors']['condition']
    common = {'application_id', 'target_ids', 'mode', 'channel'}
    thermal, flip = tc['mode'] == 'feedback', oc['mode'] == 'calendar'
    if set(tc) != common | {'state_id'} | ({'policy','rule','update','reference_step_minutes'} if thermal else set()):
        raise ValueError('请核对热学控制的规则与初始状态。')
    if set(oc) != common | {'face_id'} | ({'reference_id'} if flip else set()):
        raise ValueError('请核对外表面光学参数组及其绑定的日历。')
    refs = active_references(record)
    if len(refs) != int(flip) or cond['reference_runs'] != refs:
        raise ValueError('按日历切换表面光学参数须采用本方案唯一的逐日日历。')
    if flip and d.get('faces') != ['A','B']:
        raise ValueError('表面光学切换需要在材料版本中填写 A、B 两组表面光学参数。')
    if d['model'] == 'optical_surface_v1':
        raise ValueError('此组合工况使用有蓄热的实体材料层。')
    states = {s['id']:s for s in d['states']}
    cp = spec['state']['specific_heat_J_kgK']
    if thermal:
        if d['model'] != 'solid_variable_v1' or set(states) != {'R','C'}:
            raise ValueError('可调热阻需要两个已登记的实体状态。')
        mass = [s['thickness_mm'] * s['density_kg_m3'] for s in states.values()]
        if not math.isclose(*mass, rel_tol=1e-8) or any(not math.isclose(s['specific_heat_J_kgK'], cp, rel_tol=1e-10) for s in states.values()):
            raise ValueError('当前热阻切换按同一试件处理，请核对两态面质量和比热。')
        if math.isclose(states['R']['resistance_m2K_W'], states['C']['resistance_m2K_W'],rel_tol=1e-10):
            raise ValueError('两态热阻相同，请核对用于切换的材料。')
        p, update = tc['policy'], tc['update']
        if (tc['rule'] != 'UNIFIED' or set(p) != {'cold_C','hot_C','flux_deadband_W_m2','minimum_hold_minutes'}
                or not all(type(v) in (int,float) and math.isfinite(v) for v in p.values())
                or p['hot_C'] <= p['cold_C'] or p['flux_deadband_W_m2'] < 0 or p['minimum_hold_minutes'] < 0):
            raise ValueError('请核对统一反馈的温度阈值、热流死区与保持时间。')
        step = record['numerics']['step_minutes']
        if step != 1 or type(tc['reference_step_minutes']) is not int or tc['reference_step_minutes'] not in (1,2,5,10,15,30,60):
            raise ValueError('实体反馈使用 1 min 求解，并单独记录原构造日历的参考步长。')
        if set(update) != {'kind','minutes'} or update['kind'] != 'minutes' or type(update['minutes']) is not int or update['minutes'] <= 0 or update['minutes'] % step:
            raise ValueError('反馈判断间隔须为正数且为求解步长的整数倍。')
    for sid in (states if thermal else [tc['state_id']]):
        for face in (('A','B') if flip else [oc['face_id']]):
            optics = d['optics'].get(face + '_' + (sid if d['optics_depend_on_state'] else 'R'), {})
            if any(optics.get(k) is None for k in ('solar_absorptance','emissivity')):
                raise ValueError(f'请补齐 {face} 组、{sid} 态的太阳吸收率和长波发射率。')
    return spec, tc, oc


def apply(model, record, calendar=None):
    spec, tc, oc = controls(record)
    feedback = tc['mode'] == 'feedback'
    flip = oc['mode'] == 'calendar'
    if flip and (not isinstance(calendar, list) or len(calendar)!=365 or any(type(v) is not int or v not in (0,1) for v in calendar)):
        raise ValueError('当前地点缺少完整的 365 天 光学切换日历。')
    prefix = 'NX_SC_'
    if any(str(k).upper().startswith(prefix) for group in model.values() if isinstance(group,dict) for k in group):
        raise ValueError('源模型包含同名材料控制对象，需先核对。')
    audit = initial_application(model, record)
    def add(kind, name, fields):
        model.setdefault(kind, {})[prefix + name] = fields
    def var(name):
        return prefix + name
    def actuator(name, component, kind, control):
        add('EnergyManagementSystem:Actuator', name, dict(actuated_component_unique_name=component,
            actuated_component_type=kind, actuated_component_control_type=control))
        return var(name)
    def number(value):
        return format(value,'.15g')
    d = spec['definition']
    states = {s['id']:s for s in d['states']}
    start = int(tc['state_id'] == 'C')
    init = [f'SET NX_SC_State = {start}', 'SET NX_SC_Age = 0', 'SET NX_SC_Clock = 0', 'SET NX_SC_Ready = 0']
    globals_ = ['State','Age','Clock','Ready','Vote','Face']
    votes, capture, setters = [], [], []
    area_sum = 0.
    openings = {}
    for item in model.get('FenestrationSurface:Detailed',{}).values():
        parent = item['building_surface_name']
        if parent in spec['targets']:
            openings[parent] = openings.get(parent,0.) + measure(item)[0] * item.get('multiplier',1)
    opt_actions = {}
    for idx, row in enumerate(audit['surfaces']):
        ident, layer = row['surface'], row['layers_after'][0]
        surface = model['BuildingSurface:Detailed'][ident]
        mat = model['Material'][layer]
        participates = row['thermal_mode'] == 'feedback'
        if participates:
            area = measure(surface)[0] - openings.get(ident,0.)
            if area <= 0: raise ValueError(f'{ident} 扣除门窗后的面积须大于零。')
            zone = surface['zone_name']
            weight = area * model['Zone'][zone].get('multiplier',1)
            area_sum += weight
            algorithms = model.setdefault('SurfaceProperty:HeatTransferAlgorithm',{})
            for setting in algorithms.values():
                if setting['surface_name'].casefold() == ident.casefold() and setting['algorithm'] != 'ConductionFiniteDifference':
                    raise ValueError(f'{ident} 的传热算法与热阻反馈冲突。')
            if not any(setting['surface_name'].casefold()==ident.casefold() for setting in algorithms.values()):
                algorithms[var('FD'+str(idx))] = dict(surface_name=ident,algorithm='ConductionFiniteDifference')
            # A fixed coordinate preserves R and heat capacity per unit area in both states.
            ref_length = min(s['thickness_mm'] for s in states.values()) / 1000
            mat.update(thickness=ref_length, conductivity=ref_length/spec['state']['resistance_m2K_W'],
                density=spec['state']['density_kg_m3']*spec['state']['thickness_mm']/(1000*ref_length))
            kact = actuator('K'+str(idx), ident+':'+layer, 'CondFD Surface Material Layer', 'Thermal Conductivity')
            setters += [f'IF NX_SC_State == 0',f'SET {kact} = {number(ref_length/states["R"]["resistance_m2K_W"])}',
                'ELSE',f'SET {kact} = {number(ref_length/states["C"]["resistance_m2K_W"])}','ENDIF']
            for key, obj, output in [('T',zone,'Zone Mean Air Temperature'),('Q',ident,'Surface Outside Face Conduction Heat Transfer Rate per Area')]:
                name = key+str(idx)
                add('EnergyManagementSystem:Sensor',name,dict(output_variable_or_output_meter_index_key_name=obj,output_variable_or_output_meter_name=output))
                globals_.append('Last'+name)
                capture.append(f'SET {var("Last"+name)} = '+('0 - ' if key=='Q' else '')+var(name))
            t,q=var('LastT'+str(idx)),var('LastQ'+str(idx))
            p=tc['policy']
            deadband = number(p["flux_deadband_W_m2"])
            votes += [f'IF {q} > {deadband} || {q} < (0 - {deadband})',f'IF {t} < {number(p["cold_C"])}',
                f'SET NX_SC_Vote = NX_SC_Vote - ({q} * {number(weight)})',f'ELSEIF {t} > {number(p["hot_C"])}',
                f'SET NX_SC_Vote = NX_SC_Vote + ({q} * {number(weight)})','ENDIF','ENDIF']
        inherited=row['visible_absorptance']['original_value']
        for prop, suffix, ep in [('solar_absorptance','S','Solar'),('emissivity','E','Thermal'),('visible_absorptance','V','Visible')]:
            values={}
            for sid in (states if feedback else [tc['state_id']]):
                for face in (('A','B') if flip else [oc['face_id']]):
                    wall_state = sid if participates else row['initial_state']
                    attrs=d['optics'][face+'_'+(wall_state if d['optics_depend_on_state'] else 'R')]
                    val=attrs.get(prop)
                    values[sid,face] = val if val is not None else (.7 if inherited is None else inherited)
            if len(set(values.values())) == 1:continue
            act=actuator(suffix+str(idx),layer,'Material','Surface Property '+ep+' Absorptance')
            for (sid,face),value in values.items():
                opt_actions.setdefault((sid,face),[]).append(f'SET {act} = {number(value)}')
    step=record['numerics']['step_minutes']
    update=[]
    if feedback:
        next(iter(model['Timestep'].values()))['number_of_timesteps_per_hour']=60//step
        p=tc['policy']
        hi=int(states['C']['resistance_m2K_W']>states['R']['resistance_m2K_W'])
        update=['IF WarmupFlag == 0 && NX_SC_Ready == 1',f'SET NX_SC_Age = NX_SC_Age + {step}',
            f'SET NX_SC_Clock = NX_SC_Clock + {step}',f'IF NX_SC_Clock >= {tc["update"]["minutes"]}',
            'SET NX_SC_Clock = 0','SET NX_SC_Vote = 0',*votes,
            f'IF NX_SC_Age >= {number(p["minimum_hold_minutes"])}',
            f'IF NX_SC_Vote > {number(area_sum*p["flux_deadband_W_m2"])} && NX_SC_State <> {hi}',
            f'SET NX_SC_State = {hi}','SET NX_SC_Age = 0',
            f'ELSEIF NX_SC_Vote < (0 - {number(area_sum*p["flux_deadband_W_m2"])}) && NX_SC_State <> {1-hi}',
            f'SET NX_SC_State = {1-hi}','SET NX_SC_Age = 0','ENDIF','ENDIF','ENDIF','ENDIF']
    update.append(f'SET NX_SC_Face = {calendar[0] if flip else int(oc["face_id"]=="A")}')
    if flip:
        for i in range(1,365):
            if calendar[i]!=calendar[i-1]:
                update += [f'IF DayOfYear >= {i+1}',f'SET NX_SC_Face = {calendar[i]}','ENDIF']
    update.extend(setters)
    for (sid,face),lines in opt_actions.items():
        update.extend([f'IF NX_SC_State == {int(sid=="C")} && NX_SC_Face == {int(face=="A")}',*lines,'ENDIF'])
    add('EnergyManagementSystem:GlobalVariable','Globals',dict(variables=[dict(erl_variable_name=var(v)) for v in globals_]))
    programs=[('Init',init,'BeginNewEnvironment'),('Reset',init,'AfterNewEnvironmentWarmUpIsComplete'),
              ('Control',update,'BeginZoneTimestepBeforeInitHeatBalance')]
    if feedback:
        programs.append(('Capture',['IF WarmupFlag == 0',*capture,'SET NX_SC_Ready = 1','ENDIF'],'EndOfZoneTimestepAfterZoneReporting'))
    for name,lines,point in programs:
        add('EnergyManagementSystem:Program',name,dict(lines=[dict(program_line=l) for l in lines]))
        add('EnergyManagementSystem:ProgramCallingManager',name+'Manager',dict(energyplus_model_calling_point=point,programs=[dict(program_name=var(name))]))
    for name in ('State','Face'):
        output=var(name+'Output')
        add('EnergyManagementSystem:OutputVariable',name+'Output',dict(ems_variable_name=var(name),type_of_data_in_variable='Averaged',update_frequency='ZoneTimestep'))
        add('Output:Variable',name+'Daily',dict(key_value='*',variable_name=output,reporting_frequency='Daily'))
    audit.update(thermal_mode=tc['mode'],orientation_mode=oc['mode'],feedback_area_m2=area_sum,
        note='按所选构件、材料物性和方案控制生成输入。',calendar_sha256=digest(calendar) if flip else None)
    return audit
