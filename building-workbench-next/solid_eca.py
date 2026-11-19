"""Opt-in official CondFD / conserved-mass ECA adapter. No engine patch.

Physical state values remain in the library; the 2 mm coordinate layer is only
an execution representation. Existing NoMass / CTF records never enter this path.
"""
import copy, math
from foundation import digest

MODEL='solid_conserved_mass_v1'
PROFILE='five_storey_condfd_1min_v1'
PLACEMENT='ordinary_exterior_solid_v1'
PREFIX='NX_Fb'
POLICY=dict(rule='UNIFIED',policy=dict(cold_C=18,hot_C=26,flux_deadband_W_m2=1,
            minimum_hold_minutes=60),update=dict(kind='minutes',minutes=5))

def enabled(record):return record['numerics'].get('heat_transfer_profile')==PROFILE

def numerics(record,source):
    expected=dict(source['numerics'],step_minutes=1,heat_transfer_profile=PROFILE)
    if record['numerics']!=expected:raise ValueError('实体材料正式对照须统一为官方引擎、外墙 CondFD、1 min 求解；材料每 5 min 判断。')

def definition():
    states=[]
    for ident,name,d,rho in [('R','蓬松',10,3.07),('C','压缩',2,15.35)]:
        states.append(dict(id=ident,name=name,thermal_input='conductivity_thickness',thickness_mm=d,
            conductivity_W_mK=.03302,density_kg_m3=rho,specific_heat_J_kgK=1200,resistance_m2K_W=d/1000/.03302))
    optics={}
    for face,r,e in [('A',.938,.988),('B',.176,.659)]:
        for state in ('R','C'):optics[face+'_'+state]=dict(reflectance=r,solar_absorptance=1-r,emissivity=e,input_basis='reflectance')
    return dict(id='eca_solid_conserved',name='ECA 实体层 · 质量守恒',kind='single_layer',model=MODEL,
        state_identity='independent',states=states,optics=optics,optics_depend_on_state=False,
        source_note='用户确认 2026-11-13：同一试件，质量和面积不变；压缩密度由守恒推算。实体参数与内部参考坐标分开保存。')

def physical(definition):
    d=definition
    if d.get('model')!=MODEL or d.get('kind')!='single_layer' or d.get('state_identity')!='independent':raise ValueError('请选择独立实体 ECA 材料版本。')
    if set(d)-{'id','name','kind','model','state_identity','states','optics','optics_depend_on_state','source_note'}:raise ValueError('实体材料存在未适配字段。')
    states={s['id']:s for s in d['states']}
    if set(states)!={'R','C'} or len(d['states'])!=2:raise ValueError('实体材料须有独立的蓬松 R、压缩 C 两态。')
    mapped={};mass=[];capacity=[]
    for name,s in states.items():
        if set(s)-{'id','name','thermal_input','resistance_m2K_W','thickness_mm','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK'}:raise ValueError('实体状态含未适配字段。')
        vals=[s.get(k) for k in ('thickness_mm','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK')]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in vals):raise ValueError('实体层需明确正值厚度、导热率、密度及比热。')
        mm,k,rho,cp=vals;thickness=mm/1000;r=thickness/k
        if s.get('thermal_input')!='conductivity_thickness' or not math.isclose(s.get('resistance_m2K_W',0),r,rel_tol=1e-10):raise ValueError('实体热阻必须由真实厚度与导热率计算。')
        mass.append(rho*thickness);capacity.append(rho*cp*thickness)
        mapped[name]=dict(thickness=.002,conductivity=k*.002/thickness,density=rho*thickness/.002,specific_heat=cp)
    if not math.isclose(mass[0],mass[1],rel_tol=1e-10) or not math.isclose(capacity[0],capacity[1],rel_tol=1e-10) or states['R']['specific_heat_J_kgK']!=states['C']['specific_heat_J_kgK']:raise ValueError('此接法要求两态面质量及比热守恒，不能静默补齐实体参数。')
    # First production version is deliberately the calibrated physical specimen.
    expected={s['id']:s for s in globals()['definition']()['states']}
    for name,s in states.items():
        for k in ('thickness_mm','conductivity_W_mK','density_kg_m3','specific_heat_J_kgK'):
            if not math.isclose(s[k],expected[name][k],rel_tol=1e-10):raise ValueError('当前实体接法仅开放已完成固定两态校准的参数；新试件需独立校准。')
    if d.get('optics_depend_on_state'):raise ValueError('首轮实体接法保持光学与热阻独立。')
    for face in ('A','B'):
        a,b=d['optics'].get(face+'_R',{}),d['optics'].get(face+'_C',{})
        for key in ('solar_absorptance','emissivity'):
            v=a.get(key)
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 or v!=b.get(key):raise ValueError('两态须共用同一面的完整光学参数。')
        if not 0<a['emissivity']<=.99999:raise ValueError('发射率超出官方接口范围。')
    return dict(states=mapped,areal_mass_kg_m2=mass[0],areal_capacity_J_m2K=capacity[0],reference_thickness_mm=2)

def validate(record,source):
    from ordinary_materials import targets,SURFACE_DEFAULTS,BUILDING
    numerics(record,source);f=record['factors'];m=f['materials'];controls=f['condition']['controls'];refs=f['condition']['reference_runs']
    if source['building']['id']!=BUILDING:raise ValueError('实体层首轮只接通已核实的五层建筑。')
    if m==dict(definitions=[],applications=[]) and not controls and not refs:return None
    if set(m)-{'definitions','applications','definition_reference'} or len(m['definitions'])!=1 or len(m['applications'])!=1:raise ValueError('实体 ECA 首轮使用一个外侧附加层。')
    d=m['definitions'][0];a=m['applications'][0];mapping=physical(d);ids=targets(source)
    expected=dict(id=a['id'],material_id=d['id'],component='wall',position='exterior',target_ids=ids,orientation={'A':'cooling_face','B':'other_face'},placement_basis=PLACEMENT,surface_model=SURFACE_DEFAULTS)
    actual=copy.deepcopy(a);actual['target_ids']=sorted(actual.get('target_ids',[]))
    if actual!=expected or len(ids)!=135:raise ValueError('实体 ECA 采用全部 135 面外墙外侧；其他范围需重新核对。')
    thermals=[c for c in controls if c.get('channel')=='thermal'];orientations=[c for c in controls if c.get('channel')=='orientation']
    if len(controls)!=2 or len(thermals)!=1 or len(orientations)!=1:raise ValueError('须明确热学控制及光学朝向。')
    t,o=thermals[0],orientations[0];feedback=t.get('mode')=='feedback';state=t.get('state_id')
    if state not in ('R','C'):raise ValueError('实体层初始状态无效。')
    want=dict(application_id=a['id'],channel='thermal',mode='feedback' if feedback else 'fixed',target_ids=ids,state_id=state)
    if feedback:
        want.update(POLICY)
        if state!='C':raise ValueError('当前反馈已验证的初始化为 C；预热不反馈，正式时段重置 C。')
    actual=copy.deepcopy(t);actual['target_ids']=sorted(actual.get('target_ids',[]))
    if actual!=want:raise ValueError('首轮反馈采用全墙统一、18/26°C、1 W/m²、5 min 判断及 60 min 保持。')
    want=dict(application_id=a['id'],channel='orientation',mode=o.get('mode'),target_ids=ids,face_id='A')
    if o.get('mode')=='calendar':
        if refs:
            from calendar_library import verify_reference
            if len(refs)!=1:raise ValueError('请绑定唯一的本建筑日历。')
            snap=verify_reference(refs[0]);basis=snap['content'].get('basis',{})
            if basis.get('building',{}).get('id')!=BUILDING or snap['content']['schema_version']!=2:raise ValueError('需采用本建筑的新逐日参考日历。')
            want['reference_id']=refs[0]['id']
    elif o.get('mode')!='fixed' or refs:raise ValueError('朝向须为 A 面或明确绑定的日历。')
    actual=copy.deepcopy(o);actual['target_ids']=sorted(actual.get('target_ids',[]))
    if actual!=want:raise ValueError('实体层朝向设置与日历绑定不一致。')
    return dict(material_id=d['id'],name=d['name'],state=state,face='A',feedback=feedback,
        resistance_m2K_W=next(s['resistance_m2K_W'] for s in d['states'] if s['id']==state),optics=copy.deepcopy(d['optics']['A_'+state]),targets=ids,surface_model=copy.deepcopy(SURFACE_DEFAULTS),mapping=mapping)

def apply_numerics(model,record,source):
    from ordinary_materials import targets
    numerics(record,source)
    model['Timestep']={'Timestep':dict(number_of_timesteps_per_hour=60)}
    model['SurfaceProperty:HeatTransferAlgorithm']={w:dict(surface_name=w,algorithm='ConductionFiniteDifference') for w in targets(source)}
    model['HeatBalanceSettings:ConductionFiniteDifference']={'ECA official':dict(difference_scheme='FullyImplicitFirstOrder',space_discretization_constant=3,relaxation_factor=1,inside_face_surface_temperature_convergence_criteria=.002)}

def apply(model,record,source):
    from ordinary_materials import inventory
    spec=validate(record,source)
    if spec is None:return None
    name='NX_ECA_Solid_'+digest(spec)[:20];v=spec['mapping']['states']['R' if spec['feedback'] else spec['state']]
    values=dict(**spec['surface_model'],**v,solar_absorptance=spec['optics']['solar_absorptance'],thermal_absorptance=spec['optics']['emissivity'])
    if name in model.get('Material',{}):raise ValueError('实体层名称冲突。')
    model.setdefault('Material',{})[name]=values;rows=[]
    walls=inventory(model,source,record['factors']['building'].get('envelope_overrides'))
    if not math.isclose(walls['totals']['net_m2'],952,abs_tol=1e-8):raise ValueError('已验证的外墙净面积变化。')
    for ident in spec['targets']:
        surface=model['BuildingSurface:Detailed'][ident];old=surface['construction_name'];c=model['Construction'][old]
        layers=[c['outside_layer']]+[c[k] for k in sorted((k for k in c if k.startswith('layer_')),key=lambda k:int(k.split('_')[1]))]
        if len(layers)>=10:raise ValueError('原构造层数无法再添加研究层。')
        key=name+'_'+digest(dict(original=old,layers=layers))[:12]
        model['Construction'][key]=dict(outside_layer=name,**{'layer_'+str(i+2):v for i,v in enumerate(layers)})
        surface['construction_name']=key;rows.append(dict(surface=ident,original=old,construction=key,layers_before=layers,layers_after=[name]+layers))
    if spec['feedback']:
        from solid_feedback import control
        control(model,walls['rows'],name,spec['mapping'])
    return dict(**spec,object_kind='Material',object_name=name,object_values=values,surfaces=rows,model='官方 CondFD 实体层；2 mm 参考坐标保持真实热阻与面热容')

def compact_schedules(model,dependencies,reader):
    """Only merge identical complete file schedule objects, never actuated names."""
    files=model.get('Schedule:File',{});act={v['actuated_component_unique_name'].upper() for v in model.get('EnergyManagementSystem:Actuator',{}).values()}
    from pathlib import Path
    refs={str(Path(x['path']).resolve()):x for x in dependencies}
    first={};aliases={};signatures={}
    for name,value in files.items():
        if name.upper() in act:continue
        path=str(Path(value['file_name']).resolve())
        if path not in refs:raise ValueError('作息归并需要已登记的文件校验值。')
        reader.check(refs[path]);signature=dict(value,file_name='sha256:'+refs[path]['sha256']);sig=digest(signature);signatures[name]=signature
        if sig in first and signatures[first[sig]]==signature:aliases[name]=first[sig]
        else:first[sig]=name
    for objects in ('EnergyManagementSystem:Program','EnergyManagementSystem:Subroutine'):
        for p in model.get(objects,{}).values():
            for line in p['lines']:
                for name in list(aliases):
                    if name.upper() in line['program_line'].upper():aliases.pop(name)
    changes=[]
    def walk(v,path=()):
        if isinstance(v,dict):
            for k,x in v.items():v[k]=walk(x,path+(k,))
        elif isinstance(v,list):
            for i,x in enumerate(v):v[i]=walk(x,path+(str(i),))
        elif isinstance(v,str) and v in aliases:
            changes.append(dict(path=list(path),old=v,new=aliases[v]));return aliases[v]
        return v
    walk(model)
    model['Schedule:File']={k:v for k,v in files.items() if k not in aliases}
    return dict(before=len(files),after=len(model['Schedule:File']),aliases=aliases,references=changes,basis='相同完整设置与已验证文件内容；不合并执行器目标')
