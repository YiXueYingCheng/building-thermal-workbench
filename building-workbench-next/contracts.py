"""Four research factors, numerical settings and execution settings stay separate."""
from __future__ import annotations
import copy
import datetime as dt
import math
from foundation import digest

FACTOR_KEYS = ('building', 'materials', 'condition', 'scope')

def record_digest(record):
    return digest({k:v for k,v in record.items() if k not in ('revision', 'saved_at', 'record_sha256')})

def calculation_recipe(record):
    """This is an input recipe, not proof of physical/numerical equivalence."""
    factors = copy.deepcopy(record['factors'])
    factors['scope'].pop('aggregation', None)
    return dict(factors=factors, numerics=record['numerics'], source_snapshot=record['provenance']['snapshot_id'])

def recipe_digest(record):
    return digest(calculation_recipe(record))

def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)

def normalize(record):
    record=copy.deepcopy(record)
    for definition in record.get('factors',{}).get('materials',{}).get('definitions',[]):
        for state in definition.get('states',[]):
            if state.get('thermal_input')=='conductivity_thickness':
                d,k=state.get('thickness_mm'),state.get('conductivity_W_mK')
                state['resistance_m2K_W']=d/1000/k if finite_number(d) and finite_number(k) and d>0 and k>0 else None
        optics=definition.get('optics',{})
        for item in optics.values():
            if item.get('input_basis')=='opaque_reflectance':
                rho=item.get('reflectance')
                item['solar_absorptance']=1-rho if finite_number(rho) else None
        if definition.get('optics_depend_on_state') is False:
            for face in ('A','B'):
                if face+'_R' in optics:optics[face+'_C']=copy.deepcopy(optics[face+'_R'])
    return record

def validate(record, sites=None):
    errors=[]
    if not isinstance(record, dict):
        return ['方案必须是对象。']
    if record.get('schema_version') != 1:
        errors.append('方案结构版本不受支持。')
    if not isinstance(record.get('name'), str) or not 1 <= len(record['name'].strip()) <= 100:
        errors.append('方案名称应为 1–100 个字符。')
    f=record.get('factors')
    if not isinstance(f, dict) or set(f) != set(FACTOR_KEYS) or any(not isinstance(f[k],dict) for k in FACTOR_KEYS):
        return errors+['必须提供建筑、材料、工况、范围四个因素。']
    if any(not isinstance(f['building'].get(k),str) or not f['building'][k].strip() for k in ('id','name')):
        errors.append('建筑需要保留编号和名称。')
    try:
        period=f['scope']['period']
        if not isinstance(period,list) or len(period)!=4 or any(type(v) is not int for v in period):
            raise ValueError()
        if dt.date(2025,*period[:2])>dt.date(2025,*period[2:]):
            raise ValueError()
    except (KeyError,ValueError,TypeError):
        errors.append('计算时段应是有效的同一年内月日范围。')
    ids=f['scope'].get('site_ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(v,str) for v in ids) or len(ids)!=len(set(ids)):
        errors.append('地点列表不能为空、重复或含无效编号。')
    elif sites is not None and any(i not in sites for i in ids):
        errors.append('包含未登记的地点。')
    step=record.get('numerics',{}).get('step_minutes')
    if type(step) is not int or step not in (1,2,5,10,15,30,60):
        errors.append('求解步长不受支持。')
    for snapshot,kind in ((f['building'].get('usage_profile'),'usage'),(f['materials'].get('definition_reference'),'material')):
        if snapshot is not None:
            try:
                from component_library import verify
                verify(snapshot,kind)
                if kind=='material':
                    expected=normalize({'factors':{'materials':{'definitions':[snapshot['content']]}}})['factors']['materials']['definitions']
                    if expected!=normalize(record)['factors']['materials'].get('definitions'):errors.append('材料物性已改变，请明确保存新材料版本或解除旧版本绑定。')
            except (ValueError,KeyError,TypeError,AttributeError):errors.append('组件版本快照不完整或已改变。')
    execution=record.get('execution',{})
    cap=execution.get('max_parallel')
    if type(cap) is not int or not 1<=cap<=8:
        errors.append('并行上限应为 1–8。')
    defs=f['materials'].get('definitions',[])
    apps=f['materials'].get('applications',[])
    if not isinstance(defs,list) or not isinstance(apps,list):
        return errors+['材料定义和应用应为列表。']
    materials,material_errors=validate_definitions(defs)
    errors.extend(material_errors)
    applications={}
    for app in apps:
        if not isinstance(app,dict) or not isinstance(app.get('id'),str):
            errors.append('材料应用缺少编号。');continue
        if app['id'] in applications:
            errors.append('材料应用编号重复。')
        applications[app['id']]=app
        if app.get('material_id') not in materials:
            errors.append('材料应用引用了不存在的材料。')
        if app.get('position') not in ('exterior','interior','between','legacy_construction'):
            errors.append('材料安装位置无效。')
        targets=app.get('target_ids')
        if not isinstance(targets,list) or any(not isinstance(x,str) for x in targets) or len(targets)!=len(set(targets)):
            errors.append('材料应用对象应为不重复的构件列表。')
        if app.get('position')=='between':
            layers=app.get('between_layers')
            if not isinstance(layers,list) or len(layers)!=2 or any(not isinstance(v,str) or not v.strip() for v in layers):
                errors.append('中间层应用需要明确前后两个层名。')
    condition=f['condition']
    if not isinstance(condition.get('reference_runs'),list):
        errors.append('控制参考计算应为列表。')
    if condition.get('operation',{}).get('mode') not in ('controlled','natural','both','inherited'):
        errors.append('建筑运行模式无效。')
    controls=condition.get('controls',[])
    if not isinstance(controls,list):
        return errors+['控制策略应为列表。']
    for control in controls:
        if not isinstance(control,dict):
            errors.append('控制策略格式无效。');continue
        allowed_modes={'thermal':('fixed','feedback'),'orientation':('fixed','calendar')}
        if control.get('channel') not in allowed_modes or control.get('mode') not in allowed_modes.get(control.get('channel'),()):
            errors.append('材料使用方式与控制对象不匹配。')
        if control.get('channel')=='thermal' and not isinstance(control.get('state_id'),str):
            errors.append('热学控制需要明确固定或初始状态。')
        if control.get('channel')=='orientation' and control.get('mode')=='fixed' and control.get('face_id') not in ('A','B'):
            errors.append('固定朝向需要明确材料的朝外面。')
        app=applications.get(control.get('application_id'))
        if app is None:
            errors.append('控制策略引用了不存在的材料应用。');continue
        targets=control.get('target_ids',[])
        if not isinstance(targets,list) or any(not isinstance(x,str) for x in targets) or not set(targets)<=set(app['target_ids']):
            errors.append('控制对象必须属于已安装材料的构件。')
        state_id=control.get('state_id')
        if state_id is not None and state_id not in materials.get(app['material_id'],set()):
            errors.append('控制策略引用了不存在的材料状态。')
        cadence=control.get('update',{})
        if cadence.get('kind')=='minutes':
            minutes=cadence.get('minutes')
            if not finite_number(minutes) or minutes<=0:
                errors.append('控制更新间隔应为正数。')
    try:
        digest(record)
    except (TypeError,ValueError):
        errors.append('方案不能包含非有限数值或非 JSON 内容。')
    return list(dict.fromkeys(errors))

def differences(before, after):
    labels={'building':'建筑','materials':'材料','condition':'工况','scope':'范围'}
    rows=[]
    for key,label in labels.items():
        rows.append(dict(key=key,label=label,changed=before['factors'][key]!=after['factors'][key]))
    rows.append(dict(key='numerics',label='计算设置',changed=before['numerics']!=after['numerics']))
    rows.append(dict(key='execution',label='设备投入',changed=before['execution']!=after['execution']))
    return rows


def validate_definitions(defs):
    errors=[]
    if not isinstance(defs,list):return {},['材料定义应为列表。']
    materials={}
    for definition in defs:
        if not isinstance(definition,dict) or not isinstance(definition.get('id'),str):
            errors.append('材料定义缺少编号。');continue
        if definition['id'] in materials:
            errors.append('材料编号重复。')
        states=definition.get('states',[])
        if not isinstance(states,list):
            errors.append('材料状态应为列表。');continue
        state_ids=[]
        for state in states:
            if not isinstance(state,dict) or not isinstance(state.get('id'),str):
                errors.append('材料状态缺少独立编号。');continue
            state_ids.append(state['id'])
            for key in ('resistance_m2K_W','thickness_mm','conductivity_W_mK','areal_capacity_J_m2K'):
                value=state.get(key)
                if value is not None and (not finite_number(value) or value<=0):
                    errors.append('材料热学参数应为正数或待填。')
        if len(state_ids)!=len(set(state_ids)):
            errors.append('材料状态编号重复。')
        optics=definition.get('optics',{})
        if not isinstance(optics,dict):
            errors.append('光学参数格式无效。')
        else:
            for item in optics.values():
                if not isinstance(item,dict):
                    errors.append('光学参数格式无效。');continue
                for key in ('reflectance','solar_absorptance','emissivity'):
                    value=item.get(key)
                    if value is not None and (not finite_number(value) or not 0<=value<=1):
                        errors.append('光学参数应在 0–1 之间或待填。')
        materials[definition['id']]=set(state_ids)
    return materials,errors
