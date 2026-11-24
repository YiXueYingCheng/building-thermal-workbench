"""Workspace material library: explicit version adoption and read-only source inventory."""
import copy, math
from pathlib import Path
from foundation import ROOT, digest, now, read_json, sha
from component_library import Library
from contracts import normalize, validate


def normalize_library_material(d):
    """Validate the material itself before normalizing values for a library version."""
    from material_registration import MODELS
    from contracts import validate_definitions
    from solid_eca import MODEL as conserved, physical
    if not isinstance(d, dict) or not isinstance(d.get('model'), str) or d['model'] not in (*MODELS, conserved):
        raise ValueError('材料计算方式不受支持。')
    if not isinstance(d.get('name'), str) or not 1 <= len(d['name'].strip()) <= 100:
        raise ValueError('请核对材料名称。')
    if not isinstance(d.get('id'), str) or not d['id'].strip() or not isinstance(d.get('source_note', ''), str):
        raise ValueError('请核对材料编号和来源说明。')
    states = d.get('states')
    if not isinstance(states, list) or not states or not all(isinstance(s, dict) and isinstance(s.get('id'), str) and isinstance(s.get('name'), str) and s['name'].strip() for s in states):
        raise ValueError('材料状态和状态名称不完整。')
    if not isinstance(d.get('optics'), dict) or not all(isinstance(o, dict) for o in d['optics'].values()):
        raise ValueError('材料表面光学参数格式无效。')
    if d['model'] in ('equivalent_resistance_no_layer_storage', conserved):
        if (set(d) - {'id','name','kind','model','source_note','states','state_identity','optics','optics_depend_on_state'}
                or d.get('kind') != 'single_layer' or d.get('state_identity') != 'independent'
                or type(d.get('optics_depend_on_state')) is not bool
                or [s.get('id') for s in states] != ['R','C']):
            raise ValueError('材料定义仅接受物性与来源，请检查额外字段及 R/C 两态结构。')
        fields = {'id','name','thermal_input','resistance_m2K_W','thickness_mm','conductivity_W_mK'}
        # Older equivalent-R records can retain measured mass and heat capacity as metadata.
        measured = {'density_kg_m3','specific_heat_J_kgK'}
        if d['model'] != conserved:
            measured.update(('areal_mass_kg_m2','areal_capacity_J_m2K'))
        fields.update(measured)
        for s in states:
            if any(type(s[k]) not in (int, float) or not math.isfinite(s[k]) or s[k] <= 0
                   for k in measured.intersection(s) if s[k] is not None):
                raise ValueError('密度、比热、面质量和面热容须为正数或待填。')
            if (set(s) - fields
                    or s.get('thermal_input') not in ('resistance','conductivity_thickness')):
                raise ValueError('材料状态含无法识别的物性或输入方式。')
        for k, o in d['optics'].items():
            if (k not in ('A_R','A_C','B_R','B_C')
                    or set(o) - {'input_basis','reflectance','solar_absorptance','emissivity'}
                    or o.get('input_basis') not in ('solar_absorptance','reflectance','opaque_reflectance')):
                raise ValueError('材料的表面光学输入无效。')
    _, errors = validate_definitions([d])
    if errors:
        raise ValueError('；'.join(errors))
    canonical = normalize({'factors': {'materials': {'definitions': [d]}}})['factors']['materials']['definitions'][0]
    if d['model'] == conserved:
        physical(canonical)
    _, errors = validate_definitions([canonical])
    if errors:
        raise ValueError('；'.join(errors))
    return canonical


def import_definition(document):
    """Validate a portable material before showing it or creating a local identity."""
    if (not isinstance(document, dict) or document.get('schema') != 'workbench-material/v1'
            or not {'schema', 'source_revision', 'material'} <= set(document)
            or set(document) - {'schema', 'source_revision', 'material', 'example_origin'}):
        raise ValueError('请选择由材料库导出的材料 JSON。')
    if 'example_origin' in document:
        from component_library import check_material_origin
        check_material_origin(document['example_origin'])
    if type(document['source_revision']) is not int or document['source_revision'] < 1:
        raise ValueError('材料来源版本无效。')
    d = document['material']
    canonical = normalize_library_material(d)
    states = d['states']
    for state, checked in zip(states, canonical['states']):
        value = state.get('resistance_m2K_W')
        if value is not None and (checked.get('resistance_m2K_W') is None or
                not math.isclose(value, checked['resistance_m2K_W'], rel_tol=1e-12)):
            raise ValueError('材料热阻与厚度、导热率不一致，请核对原材料。')
    if any(canonical['optics'][k] != o for k, o in d['optics'].items()):
        raise ValueError('材料表面参数与所选输入方式或共用状态不一致。')
    return canonical


def inventory(catalog, root=ROOT):
    from material_types import template as new_template, CATEGORIES, support_paths
    template = new_template()
    from starter_library import material_presets
    from material_registration import inventory as registration
    issues = []
    presets = material_presets(issues)
    return dict(versions=Library(root).all('material'), presets=presets, preset_issues=issues, template=template, templates={k:new_template(k) for k in (*CATEGORIES,'pcm','spectral')}, support_paths=support_paths(), registration=registration(), checked_at=now())


def source_materials(catalog, root=ROOT):
    from model_adapter import VerifiedReader
    reader = VerifiedReader(catalog)
    global_job = next((j for k, j in catalog['global_bundle']['jobs'].items() if k.endswith('|W00')),None)
    sources = [('drawing26_global_frozen', 'Drawing26', global_job['model'])] if global_job else []
    sources += [(k, s['building']['name'], s['models']['controlled']) for k, s in catalog.get('ordinary_buildings', {}).items()]
    rows, issues = [], []
    from foundation import config
    public_path=config(root)['public_material_catalog']
    public=[];public_ref=None
    try:
        if not public_path:
            from reference_library import source_path
            public_path=source_path()
        public_path=Path(public_path)
        fingerprint=sha(public_path);public=read_json(public_path)['materials']
        if sha(public_path)!=fingerprint:raise ValueError('读取期间公共库发生变化。')
        public_ref=dict(path=str(public_path),sha256=fingerprint)
    except (OSError,ValueError,KeyError) as error:issues.append('公共库名称暂未读取：'+str(error))
    for ident, name, ref in sources:
        try:
            model = reader.json(ref)
            labels={}
            ordinary=catalog.get('ordinary_buildings',{}).get(ident,{})
            audit_ref=next((r for r in ordinary.get('source_refs',[]) if r['path'].endswith('wall-assignment-audit.json')),None)
            if audit_ref:
                audit=reader.json(audit_ref)
                for layer in audit.get('layers',[]):
                    if layer.get('material_name'):
                        labels.setdefault(layer['ep_material'],[]).append(layer)
            for kind, entries in model.items():
                if kind == 'Material' or kind.startswith(('Material:', 'WindowMaterial:')):
                    for material_name, values in entries.items():
                        title, basis, candidates = material_label(kind,material_name,values,labels,public)
                        rows.append(dict(key=digest([ident, kind, material_name]), name=material_name,
                            display_name=title,name_basis=basis,public_candidates=candidates,
                            name_source=audit_ref if basis=='来源构造层编号对应' else public_ref,
                            kind=kind, building_id=ident, building_name=name, values=values,
                            source=copy.deepcopy(ref), readonly=True))
        except (OSError, ValueError, KeyError) as error:
            issues.append(f'{name}：{error}')
    reader.unchanged()
    return dict(rows=rows, issues=issues, checked_at=now(),
                note='来源模型中的材料，只读查看；方案的局部构造修改另在建筑构造中核对。')


def material_label(kind,name,values,labels,public):
    def equal(a,b):return type(a) in (int,float) and type(b) in (int,float) and math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-9)
    fields={'conductivity':'conductivity_W_mK','density':'density_kg_m3','specific_heat':'specific_heat_J_kgK'}
    exact=labels.get(name,[])
    names={x['material_name'] for x in exact if all(equal(values.get(k),x.get(k)) for k in fields)}
    if len(names)==1:return next(iter(names)),'来源构造层编号对应',[]
    if len(names)>1:return name,'来源构造层存在多个名称，暂保留原编号',[]
    matches=[m for m in public if kind=='Material' and all(equal(values.get(k),m.get(v)) for k,v in fields.items())]
    candidates=[{k:m.get(k) for k in ('id','name','category','status')} for m in matches]
    names={m['name'] for m in matches}
    if len(names)==1:return next(iter(names)),'公共库热物性唯一名称对应；未确认为同一来源身份',candidates
    return name,'公共库存在多个同物性名称，暂保留原编号' if names else '暂无可靠名称对应，保留原编号',candidates


def legacy_feedback_options(record, catalog):
    factors = record['factors']
    apps = factors['materials']['applications']
    if len(apps) != 1 or apps[0].get('placement_basis') != 'legacy_outer_equivalent_model':
        raise ValueError('此选墙入口用于旧等效热阻求解器。')
    supported = {w['surface'] for w in catalog.get('dynamic_registry', {}).get('walls', []) if w.get('zone') and w.get('area_m2',0)>0}
    active = {wall for c in factors['condition']['controls'] if c['application_id'] == apps[0]['id']
              and c['channel'] == 'thermal' and c['mode'] == 'feedback' for wall in c['target_ids']}
    return [dict(id=wall, supported=wall in supported, selected=wall in active) for wall in apps[0]['target_ids']]


def adoption_preview(record, target, catalog, root=ROOT, selection=None):
    from model_adapter import changes, capability
    if (not isinstance(target, dict) or set(target) != {'id', 'revision', 'sha256'}
            or not isinstance(target['id'],str) or type(target['revision']) is not int):
        raise ValueError('请选择明确的材料库版本。')
    row = Library(root).version('material',target['id'],target['revision'])
    if not row or row['sha256'] != target['sha256']:
        raise ValueError('材料版本不存在或已变化，请刷新材料库。')
    from material_registration import check_adoption
    from solid_eca import MODEL as solid_model, enabled as solid_profile
    solid=row['content'].get('model')==solid_model
    if solid and not solid_profile(record):
        raise ValueError(f'当前方案求解步长为 {record["numerics"]["step_minutes"]} min。此质量守恒 ECA 需使用五层建筑的 1 min 外墙有限差分（CondFD）方案。请从该组已保存版本预览选用。')
    check_adoption(record,row['content'])
    from material_types import supported
    materials = record['factors']['materials']
    equivalent = row['content']['model'] == 'equivalent_resistance_no_layer_storage'
    if supported(row['content']) or (equivalent and (selection is not None or not materials['definitions'])):
        from surface_materials import adoption
        selection=selection or {}
        if set(selection)-{'state_id','face','targets'}:raise ValueError('材料选用参数不受支持。')
        return adoption(record,row,catalog,**selection)
    adapter = record['provenance']['adapter']
    if adapter not in ('global_frozen_v011', 'ordinary_building_v1'):
        raise ValueError('当前建筑来源尚未接通等效热阻材料，请检查建筑导入和材料适用范围。')
    out = copy.deepcopy(record)
    m = out['factors']['materials']
    notes = []
    if selection and adapter != 'ordinary_building_v1':
        raise ValueError('请在此方案的材料应用入口修改作用范围。')
    if selection and (set(selection)-{'state_id','face','targets'} or any(c.get('mode')!='fixed' for c in out['factors']['condition']['controls']) or out['factors']['condition']['reference_runs']):
        raise ValueError('请先核对此方案已绑定的日历或控制，再设置固定应用。')
    if not m['definitions'] or selection:
        if adapter == 'global_frozen_v011':
            walls = list(out['factors']['building']['wall_ids'])
            app = dict(id='eca_walls', material_id=row['content']['id'], component='wall', position='exterior',
                       target_ids=walls, orientation=dict(A='cooling_face', B='other_face'),
                       placement_basis='legacy_outer_equivalent_model')
            m = dict(definitions=[row['content']], applications=[app])
            out['factors']['condition']['controls'] = [
                dict(channel='thermal', mode='fixed', application_id=app['id'], target_ids=walls, state_id='R'),
                dict(channel='orientation', mode='fixed', application_id=app['id'], target_ids=walls, face_id='A')]
            notes.append(f'新增 {len(walls)} 面外墙的外侧等效层，全部采用固定 R 状态、固定 A 面。')
        else:
            from ordinary_materials import preset
            from ordinary_building import source
            settings = selection or {}
            state, face = settings.get('state_id','R'), settings.get('face','A')
            m, controls = preset(source(catalog, record['factors']['building']['id']), catalog, state,
                                 definition=row['content'], selected=settings.get('targets'), face=face)
            out['factors']['condition']['controls'] = controls
            notes.append(f"新增 {len(m['applications'][0]['target_ids'])} 面外墙的外侧附加层，采用固定 {state} 状态、{face} 面朝外。")
        out['factors']['materials'] = m
    elif len(m['definitions']) != 1:
        raise ValueError('当前入口只替换单一研究材料，请先核对多材料应用。')
    old_id = m['definitions'][0]['id']
    m['definitions'] = [copy.deepcopy(row['content'])]
    m['definition_reference'] = copy.deepcopy(row)
    for application in m['applications']:
        if application['material_id'] == old_id:
            application['material_id'] = row['content']['id']
    out = normalize(out)
    errors = validate(out, catalog['sites'])
    if errors:
        raise ValueError('选用后配置不完整：' + '；'.join(errors))
    cap = capability(out, catalog)
    if not cap['supported']:
        raise ValueError('此材料版本与当前方案不兼容：' + '；'.join(cap['reasons']))
    if record['factors']['materials']['definitions'] and not selection:
        notes.append('保留当前应用构件、层位及工况控制，仅替换所选材料定义和版本引用。')
    return dict(target=row, materials=out['factors']['materials'], controls=out['factors']['condition']['controls'],
        differences=changes(record['factors']['materials'], out['factors']['materials']),
        control_differences=changes(record['factors']['condition']['controls'], out['factors']['condition']['controls']),
        notes=notes, record_sha256=digest(record), checked_at=now(), generation=cap)
