"""Read an existing input bundle without regenerating or preparing calculations."""
from pathlib import Path
import re
from foundation import owned,read_json,sha,digest,now
from preparation_recovery import saved_input,submitted


def stack_readback(model, application):
    """Join the saved layer identities to their actual slots in the selected case."""
    layers = application['layers']
    actuators = {a['actuated_component_unique_name'].casefold()
                 for a in model.get('EnergyManagementSystem:Actuator', {}).values()
                 if a['actuated_component_control_type'].casefold() == 'thermal conductivity'
                 and a['actuated_component_type'].casefold() == 'condfd surface material layer'}
    phase = model.get('MaterialProperty:PhaseChange', {})
    groups = [{} for _ in layers]
    for surface in application['surfaces']:
        name = surface['surface']
        construction = model['Construction'][model['BuildingSurface:Detailed'][name]['construction_name']]
        slots = [construction['outside_layer'], *(construction['layer_'+str(i)] for i in range(2,len(construction)+1))]
        solid_index = 0
        for i, layer in enumerate(layers):
            coating = layer['model'] == 'optical_surface_v1'
            solid = surface['inserted_layers'][solid_index]
            if solid not in slots:
                raise ValueError(f'{name} 的生成记录与构造层序不一致，请核对原模型输入。')
            material = model['Material'][solid]
            props = dict(slot=slots.index(solid)+1)
            if coating or (i==0 and props['slot']==1 and application.get('position')=='exterior'):
                props.update(solar_absorptance=material['solar_absorptance'],emissivity=material['thermal_absorptance'])
            if not coating:
                solid_index += 1
                props.update(thickness_mm=material['thickness']*1000, conductivity=material['conductivity'],
                             feedback=(name+':'+solid).casefold() in actuators,
                             enthalpy_points=len(phase.get(solid,{}).get('values',[])))
            key = tuple(props.values())
            groups[i].setdefault(key,dict(**props,surfaces=[]))['surfaces'].append(name)
    return dict(surface_count=len(application['surfaces']),calendar_optics=application.get('calendar_optics'), layers=[
        dict(name=l['name'],revision=l['revision'],model=l['model'],groups=list(group.values()))
        for l,group in zip(layers,groups)])


def wall_model(root, ident, index, store, expected):
    """Return only case choices or the wall stacks of one verified saved input."""
    manifest, _, _ = saved_input(root, ident, store, expected)
    cases = manifest['cases']
    if index is None:
        fields = ('city', 'site_id', 'mode', 'period', 'step_minutes')
        return {'cases': [{k: c.get(k) for k in fields} for c in cases]}
    if not 0 <= index < len(cases):
        raise ValueError('该输入包没有所选算例。')
    case = cases[index]
    if not re.fullmatch(r'[0-9]{3,}\.epJSON', case['model_file']):
        raise ValueError('输入模型文件名无效。')
    folder = owned(Path(root)/'data/model-inputs'/ident, root)
    path = owned(folder / case['model_file'], folder)
    if sha(path) != case['model_sha256']:
        raise ValueError('算例模型校验失败，请在输入核对中检查该文件。')
    model = read_json(path)
    if digest(model) != case['generated_model_digest']:
        raise ValueError('模型与生成时的记录不一致。')
    walls = {name: row['construction_name'] for name, row in model['BuildingSurface:Detailed'].items()
             if row['surface_type'].lower() == 'wall'}
    stacks = {}
    for name in set(walls.values()):
        construction = model.get('Construction', {}).get(name, {})
        if 'outside_layer' in construction:
            layers = sorted((k for k in construction if re.fullmatch(r'layer_\d+', k)),
                            key=lambda k: int(k[6:]))
            stacks[name] = [construction['outside_layer'], *(construction[k] for k in layers)]
    insulation = {}
    for item in model.get('SurfaceControl:MovableInsulation', {}).values():
        insulation.setdefault(item['surface_name'], []).append(item)
    exterior_heat_sources = {item['surface_name']: item['outside_face_heat_source_term_schedule_name']
                             for item in model.get('SurfaceProperty:HeatBalanceSourceTerm', {}).values()
                             if item.get('outside_face_heat_source_term_schedule_name')}
    names = {stack[0] for stack in stacks.values()}
    names.update(item['material_name'] for group in insulation.values() for item in group)
    fields = ('solar_absorptance', 'thermal_absorptance', 'visible_absorptance')
    layer_optics = {
        name: {k: values[k] for k in fields if k in values}
        for kind in ('Material', 'Material:NoMass')
        for name, values in model.get(kind, {}).items() if name in names
    }
    return dict(walls=walls, stacks=stacks, insulation=insulation, layer_optics=layer_optics,
                exterior_heat_sources=exterior_heat_sources, file=path.name,
                model_sha256=case['model_sha256'])

def inspect(root,ident,store):
    root=Path(root).resolve();m,r,checksum=saved_input(root,ident,store)
    folder=owned(root/'data/model-inputs'/ident,root)
    if type(m['case_count']) is not int or m['case_count']!=len(m['cases']):raise ValueError('输入清单数量不一致。')
    anchors=submitted(root,ident)
    for b in anchors:
        p=b['plan']
        if not re.fullmatch(r'review_[a-f0-9]{32}',b['review']):raise ValueError('原批次清单编号无效。')
        review=owned(root/'data/execution/reviews'/b['review']/'plan.json',root)
        if sha(review)!=b['checksum'] or read_json(review)!=p:raise ValueError('原批次冻结清单变化，请保留并核查。')
        if (p['bundle_sha256'],p['record_id'],p['revision'],p['record_sha256'])!=(checksum,r['id'],r['revision'],digest(r)):
            raise ValueError('输入包与原批次冻结记录不一致。')
    seen=set()
    for c in m['cases']:
        name=c['model_file']
        if not isinstance(name,str) or not re.fullmatch(r'[0-9]{3,}\.epJSON',name) or name in seen:raise ValueError('输入模型文件名无效或重复。')
        seen.add(name);path=owned(folder/name,folder)
        if sha(path)!=c['model_sha256']:raise ValueError('输入模型内容变化：'+name)
        if c.get('audit'):
            audit=c['audit'];detail=owned(folder/audit['file'],folder)
            if audit.get('kind')!='case_audit_v1' or sha(detail)!=audit['sha256']:raise ValueError('算例详情校验不符，请保留输入包并核查。')
        elif digest(read_json(path))!=c['generated_model_digest']:raise ValueError('输入模型内容变化：'+name)
    if sha(folder/'manifest.json')!=checksum or read_json(folder/'record.json')!=r:raise ValueError('读取期间输入记录发生变化，请重新读取。')
    return dict(manifest=m,record={k:r[k] for k in ('id','revision','name')},operation_mode=r['factors']['condition']['operation']['mode'],
        period=r['factors']['scope']['period'],manifest_sha256=checksum,checked_models=len(seen),batch_anchor_count=len(anchors),checked_at=now())

def case_detail(root,ident,index,store):
    import copy,json
    from input_pipeline import read_audit
    m,r,checksum=saved_input(root,ident,store)
    if not 0<=index<len(m['cases']):raise ValueError('算例序号无效。')
    folder=owned(Path(root)/'data/model-inputs'/ident,root);row=m['cases'][index]
    model=owned(folder/row['model_file'],folder)
    if sha(model)!=row['model_sha256']:raise ValueError('所选模型内容变化，请保留并核查。')
    values=read_json(model)
    if digest(values)!=row['generated_model_digest']:raise ValueError('所选模型内容变化，请保留并核查。')
    fields=('city','mode','period','step_minutes','wall_assignments','wall_assignments_basis','differences',
        'usage_configuration','usage_version','operation_overrides','control_groups','source_model','weather','dependencies','calendar_binding','orientation_calendar','drawing_wall_scope')
    complete=read_audit(folder,row);report={k:copy.deepcopy(complete[k]) for k in fields if k in complete}
    application=complete.get('material_application') or {}
    if application.get('surfaces'):
        report['applied_surfaces']=[surface['surface'] for surface in application['surfaces']]
    if application.get('model')=='layer_stack_v1':
        report['stack_readback']=stack_readback(values,application)
    del complete,values
    if isinstance(report.get('usage_version'),dict):report['usage_version']={k:report['usage_version'][k] for k in ('id','revision','name') if k in report['usage_version']}
    url=f'/api/model-inputs/{ident}/'+row.get('audit',{}).get('file','manifest.json')
    # Keep all paths and counts visible, read long values only on demand.
    for difference in report.get('differences',[]):
        for side in ('before','after'):
            value=difference.get(side)
            if isinstance(value,(dict,list)) and len(json.dumps(value,ensure_ascii=False))>2048:
                difference[side+'_preview']=dict(items=len(value),url=url)
                difference.pop(side,None)
    return dict(report,model_file=row['model_file'],audit_url=url,manifest_sha256=checksum)
