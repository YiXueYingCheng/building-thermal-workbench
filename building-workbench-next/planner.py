"""Case preview and compatibility checks. This stage has no execution dispatch."""
import copy
from contracts import validate, normalize, recipe_digest
from foundation import digest

def original_match(record,catalog):
    ident=record['provenance'].get('origin_id',record['id'])
    original=catalog['records'].get(ident)
    if not original or original['provenance']['snapshot_id']!=record['provenance']['snapshot_id']:
        return None
    original_sites=set(original['factors']['scope']['site_ids'])
    requested_sites=set(record['factors']['scope']['site_ids'])
    if record['provenance']['adapter']=='global_frozen_v011':
        if not requested_sites<=original_sites:return None
    elif requested_sites!=original_sites:
        return None
    a,b=copy.deepcopy(original),copy.deepcopy(record)
    for r in (a,b):
        r['factors']['scope'].pop('site_ids',None)
        r['factors']['scope'].pop('aggregation',None)
    if a['factors']==b['factors'] and a['numerics']==b['numerics']:
        return original
    return None

def preview(record,catalog):
    from model_adapter import capability
    record=normalize(record)
    errors=validate(record,catalog['sites'])
    if errors:return dict(valid=False,errors=errors,execution_enabled=False,cases=[],case_count=None)
    f=record['factors'];mode=f['condition']['operation']['mode']
    modes=['natural','controlled'] if mode=='both' else [mode]
    unresolved=mode=='inherited'
    notes=[]
    if unresolved:notes.append('运行模式仍由旧输入快照决定；暂不推算实际计算数量。')
    requirements=[]
    definitions={d['id']:d for d in f['materials'].get('definitions',[])}
    applications={a['id']:a for a in f['materials'].get('applications',[])}
    for control in f['condition'].get('controls',[]):
        app=applications.get(control.get('application_id'))
        if not app:continue
        material=definitions[app['material_id']]
        if control.get('channel')=='thermal':
            states=material.get('states',[])
            used=states if control.get('mode')=='feedback' else [s for s in states if s['id']==control.get('state_id')]
            for s in used:
                if s.get('resistance_m2K_W') is None:
                    requirements.append(material['name']+' / '+s['name']+'：缺少本模型使用的热阻。')
            if control.get('mode')=='feedback' and len({s.get('resistance_m2K_W') for s in states})<len(states):
                notes.append('两态热阻相同，仍以独立状态编号区分，可保留相应光学差异。')
        if control.get('channel')=='orientation' and app['position']=='between':
            notes.append('材料位于构造内部，原外表面光学切换规则不能直接套用。')
        elif control.get('channel')=='orientation':
            faces=[control.get('face_id')] if control.get('mode')=='fixed' else ['A','B']
            state_ids=set()
            for thermal in f['condition']['controls']:
                if thermal.get('channel')=='thermal' and thermal.get('application_id')==app['id'] and set(thermal['target_ids'])&set(control['target_ids']):
                    state_ids.update(s['id'] for s in material['states']) if thermal['mode']=='feedback' else state_ids.add(thermal.get('state_id'))
            for face in faces:
                for state in state_ids:
                    optical=material.get('optics',{}).get(str(face)+'_'+str(state),{})
                    if optical.get('solar_absorptance') is None or optical.get('emissivity') is None:
                        requirements.append(material['name']+' / '+str(face)+' 组 / '+str(state)+' 态：缺少所选组的光学参数。')
            if app['position']=='interior':notes.append('内侧应用需要核对室内侧表面与控制方向，不能沿用外侧表面光学切换执行映射。')
        if control.get('channel')=='orientation' and control.get('mode')=='calendar':
            references={r.get('id') for r in f['condition'].get('reference_runs',[])}
            if control.get('reference_id') not in references:
                requirements.append('光学切换日历规则需要绑定参考计算及其日历。')
        update=control.get('update',{})
        if update.get('kind')=='minutes' and update['minutes']%record['numerics']['step_minutes']:
            requirements.append('当前更新间隔不是求解步长的整数倍，需明确执行时序。')
    original=original_match(record,catalog)
    source_adapter=record['provenance']['adapter']
    candidates=[];held=[]
    for site_id in f['scope']['site_ids']:
        site=catalog['sites'][site_id]
        if not site.get('eligible',True):
            held.append(site['name']);continue
        for operation in modes:
            row=dict(site_id=site_id,city=site['name'],climate=site.get('climate'),mode=operation,
                step_minutes=record['numerics']['step_minutes'],historical_candidate=False)
            if original and source_adapter=='global_frozen_v011':
                key=site_id+'|'+original['provenance']['case']
                job=catalog['global_bundle']['jobs'].get(key)
                if job:
                    row.update(historical_candidate=True,source_job=job['id'],annual=job['annual'],
                        input_checks_passed=all(r['status']=='verified' for r in [job['model'],job['weather'],job['result'],*job['dependencies']]))
            candidates.append(row)
    if held:notes.append('以下地点保留未接受状态：'+'、'.join(held))
    if not original:notes.append('研究输入已改变，源方案历史结果不能作为本方案的新结果。')
    if source_adapter=='legacy_plan_v011':notes.append('旧方案配置已映射；已完成代表性新旧路径实跑核对，当前方案仍按其输入独立运行和核验。')
    return dict(valid=True,errors=[],requirements=list(dict.fromkeys(requirements)),notes=list(dict.fromkeys(notes)),
        execution_enabled=False,execution_status='本预览不启动计算；生成输入后可准备清单并提交统一队列',generation=capability(record,catalog),cases=candidates,
        case_count=None if unresolved else len(candidates),selected_sites=len(f['scope']['site_ids']),
        historical_candidates=sum(bool(x['historical_candidate']) for x in candidates),
        source_checked_at=catalog['created'],recipe_sha256=recipe_digest(record),
        source_configuration_match=bool(original),held_sites=held)

def compare(left,right):
    out=[]
    for key,label in [('building','建筑'),('materials','材料'),('condition','工况'),('scope','范围')]:
        out.append(dict(key=key,label=label,equal=left['factors'][key]==right['factors'][key]))
    out.append(dict(key='numerics',label='计算设置',equal=left['numerics']==right['numerics']))
    operation_equal=left['factors']['condition']['operation']==right['factors']['condition']['operation']
    if not out[0]['equal']:
        from comparison_results import room_usage_contrast
        if room_usage_contrast(left,right):
            return dict(rows=out,shared_conditions=True,operation_equal=operation_equal,contrast_factor='room_usage',
                note='同一建筑的房间使用配置对照。双方材料、方案运行设置、气象范围和求解设置一致。')
    comparable=operation_equal and all(r['equal'] for r in out if r['key'] in ('building','scope','numerics'))
    return dict(rows=out,shared_conditions=comparable,operation_equal=operation_equal,
        note='共同条件一致，仅表示配置层面可组织对照；科学可比性仍需相应模型和结果核查。' if comparable else '共同建筑、范围、运行或计算设置存在差异，需明确比较目的。')
