"""Five-storey ECA orientation, pinned to accepted baseline daily evidence."""
import copy
import datetime as dt
import math
from foundation import digest
from contracts import normalize
from model_adapter import VerifiedReader
from ordinary_building import source,compile_case
from ordinary_materials import validate,inventory,BUILDING

PREFIX='NX_FiveStorey_Flip'
CALLING_POINT='BeginZoneTimestepBeforeInitHeatBalance'
EXECUTION_VERIFIED=True


def fixed_record(record):
    r=copy.deepcopy(record);r['factors']['condition']['reference_runs']=[]
    for control in r['factors']['condition']['controls']:
        if control['channel']=='orientation':
            control.update(mode='fixed',face_id='A');control.pop('reference_id',None)
    return r


def validate_binding(record,catalog):
    from calendar_library import active_references,bound
    if not EXECUTION_VERIFIED:raise ValueError('五层表面光学切换短期实跑尚未完成。')
    refs=active_references(record)
    if len(refs)!=1:raise ValueError('五层表面光学切换须绑定唯一逐日日历。')
    optics(record,catalog);bound(record,catalog,refs[0])
    return refs[0]['snapshot']['content']


def optics(record,catalog):
    r=normalize(record)
    spec=validate(r,source(catalog,r['factors']['building']['id']))
    if not spec:raise ValueError('当前是原构造方案。可独立保存日历；核对表面光学切换输入需先选择 ECA 材料应用。')
    if spec['state']!='R' and not spec.get('feedback') and 'mapping' not in spec:raise ValueError('固定压缩与光学切换需使用已校准的实体 ECA 层。')
    d=r['factors']['materials']['definitions'][0];faces={}
    for face in ('A','B'):
        item=copy.deepcopy(d['optics'].get(face+'_'+spec['state'],{}))
        for key,label in (('solar_absorptance','太阳吸收率'),('emissivity','发射率')):
            v=item.get(key)
            if v is None:raise ValueError(f'当前材料版本尚未登记 {face} 组的{label}；请先核对并采用双面材料版本。')
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError(f'{face} 组{label}无效。')
        if not 0<item['emissivity']<=.99999:raise ValueError(f'{face} 组发射率不在本引擎支持范围内。')
        faces[face]=item
    return r,spec,faces


def program(calendar,faces):
    # One material is exposed only on the 135 selected exterior walls. No original
    # substrate material or internal-face property is actuated.
    lines=[f'SET {PREFIX}_Face = {calendar[0]}']
    for i in range(1,365):
        if calendar[i]!=calendar[i-1]:lines += [f'IF DayOfYear >= {i+1}',f'SET {PREFIX}_Face = {calendar[i]}','ENDIF']
    lines += [f'IF {PREFIX}_Face == 1']
    for face in ('A','B'):
        if face=='B':lines.append('ELSE')
        lines += [f'SET {PREFIX}_Solar = {faces[face]["solar_absorptance"]:.15g}',f'SET {PREFIX}_Thermal = {faces[face]["emissivity"]:.15g}']
    return lines+['ENDIF']


def compile_inspection(record,catalog,content,site_id,reader=None,operation_mode=None):
    """Caller supplies a freshly verified calendar; this function pins and checks its evidence."""
    from calendar_library import temporary_snapshot,snapshot_reference,bound
    from queue_calendar import ACCEPTANCE
    from calendar_preview import calculate
    r,spec,faces=optics(record,catalog)
    if r['factors']['building']['id']!=BUILDING or content.get('acceptance')!=ACCEPTANCE:raise ValueError('需使用五层建筑自身已接受的逐日日历。')
    if site_id not in r['factors']['scope']['site_ids']:raise ValueError('地点不在本方案范围。')
    row=bound(r,catalog,snapshot_reference(temporary_snapshot(content)))[site_id]
    reader=reader or VerifiedReader(catalog)
    for ref in row['evidence']:reader.check(ref)
    reader.check(row['daily'])
    # Recompile the annual baseline with today's adapter as well as checking
    # the bound source files. A changed compiler cannot silently reuse dates.
    from reference_readiness import baseline,physical
    baseline_record=baseline(r);baseline_record['factors']['scope']['period']=[1,1,12,31]
    baseline_model,baseline_report=compile_case(baseline_record,site_id,catalog,reader,'controlled')
    dependencies={x['path']:x['sha256'] for x in baseline_report['dependencies']}
    if physical(baseline_model,dependencies,reader)!=row['physical_sha256']:
        raise ValueError('当前生成的全年原构造输入与日历参考不同，请重新核对。')
    result=reader.json(row['result']);daily=result['daily_reference']['daily']
    verified=calculate([d['heating_kWh'] for d in daily],[d['cooling_kWh'] for d in daily])
    import transition_confirmation as tc
    from foundation import sha
    reader.check(dict(path=str(__import__('pathlib').Path(tc.__file__).resolve()),sha256=sha(tc.__file__)))
    tc.verify_entry(content['basis'],verified,row)
    calendar=row['calendar']
    # The ordinary compiler still accepts fixed A only. This isolated copy adds
    # orientation controls after fixed construction/configuration is complete.
    m,base=compile_case(fixed_record(r),site_id,catalog,reader,operation_mode)
    applied=base['material_application'];name=applied['object_name'];s=source(catalog,BUILDING)
    measured=inventory(m,s,r['factors']['building'].get('envelope_overrides'))
    if len(applied['surfaces'])!=135 or not math.isclose(measured['totals']['net_m2'],952,abs_tol=1e-8):raise ValueError('已确认的外墙范围发生变化。')
    exposed=[]
    for ident,surface in m['BuildingSurface:Detailed'].items():
        layers=m['Construction'][surface['construction_name']]
        if name in layers.values():
            if ident not in spec['targets'] or layers['outside_layer']!=name or list(layers.values()).count(name)!=1 or len(layers)<2:
                raise ValueError('研究层出现在已确认外墙外侧以外的位置。')
            exposed.append(ident)
    if sorted(exposed)!=spec['targets']:raise ValueError('材料暴露面与应用范围不一致。')
    start=(dt.date(2025,*r['factors']['scope']['period'][:2])-dt.date(2025,1,1)).days
    initial=faces['A' if calendar[start] else 'B']
    m[applied.get('object_kind','Material:NoMass')][name].update(solar_absorptance=initial['solar_absorptance'],thermal_absorptance=initial['emissivity'])
    for kind,objects in m.items():
        if isinstance(objects,dict) and any(str(k).startswith(PREFIX) for k in objects):raise ValueError('表面光学切换输入对象名称与已有模型冲突。')
    def add(kind,key,value):m.setdefault(kind,{})[PREFIX+key]=value
    for key,control in (('_Solar','Solar'),('_Thermal','Thermal')):
        add('EnergyManagementSystem:Actuator',key,dict(actuated_component_unique_name=name,actuated_component_type='Material',actuated_component_control_type=f'Surface Property {control} Absorptance'))
    lines=program(calendar,faces)
    add('EnergyManagementSystem:GlobalVariable','_Variables',dict(variables=[dict(erl_variable_name=PREFIX+'_Face')]))
    add('EnergyManagementSystem:Program','_Apply',dict(lines=[dict(program_line=x) for x in lines]))
    add('EnergyManagementSystem:ProgramCallingManager','_Control',dict(energyplus_model_calling_point=CALLING_POINT,programs=[dict(program_name=PREFIX+'_Apply')]))
    add('EnergyManagementSystem:OutputVariable','_FaceOutput',dict(ems_variable_name=PREFIX+'_Face',type_of_data_in_variable='Averaged',update_frequency='ZoneTimestep'))
    for freq in ('Daily','Monthly','RunPeriod'):add('Output:Variable','_Face_'+freq,dict(key_value='*',variable_name=PREFIX+'_FaceOutput',reporting_frequency=freq))
    reader.unchanged()
    report=dict(status='input_ready',execution_enabled=EXECUTION_VERIFIED,runtime_verified=EXECUTION_VERIFIED,new_simulations=0,
        site_id=site_id,material_name=spec['name'],state=spec['state'],resistance_m2K_W=spec['resistance_m2K_W'],faces=faces,
        surfaces=len(exposed),net_area_m2=measured['totals']['net_m2'],period=r['factors']['scope']['period'],initial_face='A' if calendar[start] else 'B',
        calendar_sha256=digest(calendar),calendar_content_sha256=digest(content),material_sha256=digest(r['factors']['materials']['definitions'][0]),
        material_version=copy.deepcopy(r['factors']['materials'].get('definition_reference')),source=row['reference_record'],
        generated_model_sha256=digest(m),control=dict(calling_point=CALLING_POINT,lines=lines,thermal_state='feedback' if spec.get('feedback') else 'fixed_'+spec['state'],
            warmup='沿用原求解器预热；预热也按当前模拟日期取光学参数组，不追加实际天气前置。',date_basis='实际非闰年日序，局部时段不从日历第一项重排。'),
        days=[dict(day_of_year=i+1,date=(dt.date(2025,1,1)+dt.timedelta(days=i)).strftime('%m-%d'),face='A' if f else 'B',
            solar_absorptance=faces['A' if f else 'B']['solar_absorptance'],emissivity=faces['A' if f else 'B']['emissivity']) for i,f in enumerate(calendar)],
        note='已核对双面参数、范围及日历接线；采用后需保存方案，再准备计算。' if EXECUTION_VERIFIED else '双面参数、范围及日历接线已核对；短期实跑尚未完成。')
    return m,report


def compile_bound(record,site_id,catalog,reader,operation_mode=None):
    content=validate_binding(record,catalog)
    model,orientation=compile_inspection(record,catalog,content,site_id,reader,operation_mode)
    # The ordinary base report remains the queue contract; add the optical
    # control changes to its audited model differences without replacing inputs.
    fixed,report=compile_case(fixed_record(record),site_id,catalog,reader,operation_mode)
    from model_adapter import changes
    report['differences']+=changes(fixed,model)
    report.update(orientation_calendar=orientation,generated_model_digest=digest(model),exact_input_match=False)
    return model,report


def inspect(record,catalog,content,site_id):
    try:return compile_inspection(record,catalog,content,site_id,operation_mode='controlled')[1]
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return dict(status='needs_material',execution_enabled=False,runtime_verified=False,new_simulations=0,note=str(exc))
