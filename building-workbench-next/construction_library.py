"""Explicit library construction replacement on opaque exterior walls and roofs."""
import copy, math
from foundation import digest
from component_library import Library, verify

KEY='library_constructions'


def enabled(record):return KEY in record['factors']['building']


def baseline(record):
    out=copy.deepcopy(record);out['factors']['building'].pop(KEY,None);return out


def validate_content(content):
    if not isinstance(content,dict) or content.get('schema_version')!=1 or not isinstance(content.get('layers'),list) or not 1<=len(content['layers'])<=10:
        raise ValueError('构造需包含 1–10 个明确材料层。')
    if [r.get('sequence') for r in content['layers'] if isinstance(r,dict)]!=list(range(1,len(content['layers'])+1)):raise ValueError('请保留连续的原层号。')
    for row in content['layers']:
        if not isinstance(row,dict) or not {'sequence','thickness_mm','material'}<=set(row):raise ValueError('构造层字段不完整。')
        m=row['material']
        if not isinstance(m,dict) or not isinstance(m.get('name'),str) or not m['name'].strip():raise ValueError('请保留材料名称。')
        for value in [row['thickness_mm'],m.get('conductivity_W_mK'),m.get('density_kg_m3'),m.get('specific_heat_J_kgK')]:
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('构造层需补齐正数厚度、导热率、密度、比热；不将空气间层默认为实体材料。')
        if m['specific_heat_J_kgK']<100:raise ValueError('当前引擎要求比热不低于 100 J/(kg·K)。')
    return content


def validate_bindings(bindings):
    if not isinstance(bindings,list):raise ValueError('构造选用记录应为列表。')
    seen=set()
    for entry in bindings:
        if not isinstance(entry,dict) or set(entry)!={'reference','target_ids','order','optics_basis'}:raise ValueError('构造选用快照不完整。')
        row=verify(entry['reference'],'construction');validate_content(row['content'])
        ids=entry['target_ids']
        if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)) or seen&set(ids):raise ValueError('构造目标为空或重复。')
        seen.update(ids)
        if entry['order'] not in ('original','reversed') or entry['optics_basis']!='retain_target_surface_optics':raise ValueError('请明确室外至室内层序，并确认沿用目标原表面光学。')


def apply(model,record):
    bindings=record['factors']['building'].get(KEY,[]);validate_bindings(bindings)
    from material_types import supported
    if any(not supported(d) for d in record['factors']['materials']['definitions']):raise ValueError('当前库构造选用不能叠加旧 ECA 活动保温层；请从原构造方案另存，或采用新的固定实体材料入口。')
    from surface_materials import target_rows
    eligible={r['id'] for r in target_rows(model)};audit=[]
    def surface_props(name):
        found=[model[k][name] for k in ('Material','Material:NoMass') if name in model.get(k,{})]
        if len(found)!=1:raise ValueError('原构造表面不是已支持的不透明材料。')
        o=found[0]
        return dict(roughness=o['roughness'],solar_absorptance=o.get('solar_absorptance',.7),thermal_absorptance=o.get('thermal_absorptance',.9),visible_absorptance=o.get('visible_absorptance',.7))
    for entry in bindings:
        if set(entry['target_ids']) & set(record['factors']['building'].get('envelope_overrides',{})):raise ValueError('目标构件已有原层局部编辑，请先撤销对应编辑再采用整套构造，避免覆盖。')
        if not set(entry['target_ids'])<=eligible:raise ValueError('构造首批选用仅支持室外不透明墙面／屋面。')
        layers=entry['reference']['content']['layers']
        if entry['order']=='reversed':layers=layers[::-1]
        for target in entry['target_ids']:
            if any(x.get('surface_name')==target for x in model.get('SurfaceControl:MovableInsulation',{}).values()):raise ValueError('目标已有活动保温层，不能直接替换基础构造。')
            s=model['BuildingSurface:Detailed'][target];old=s['construction_name'];c=model['Construction'][old]
            before=[c['outside_layer']]+[c[k] for k in sorted((k for k in c if k.startswith('layer_')),key=lambda x:int(x[6:]))]
            outside,inside=surface_props(before[0]),surface_props(before[-1])
            if len(layers)==1 and outside!=inside:raise ValueError('单层构造不能同时沿用两组不同内外表面光学；请先明确单层两面接法。')
            name='NX_Library_'+digest([target,entry,outside,inside])[:24];after=[]
            if name in model['Construction']:raise ValueError('构造版本生成名称冲突。')
            for index,layer in enumerate(layers):
                m=layer['material'];prop=copy.deepcopy(outside if index==0 else inside if index==len(layers)-1 else dict(roughness='MediumSmooth',solar_absorptance=.7,thermal_absorptance=.9,visible_absorptance=.7))
                prop.update(thickness=layer['thickness_mm']/1000,conductivity=m['conductivity_W_mK'],density=m['density_kg_m3'],specific_heat=m['specific_heat_J_kgK'])
                ident=name+'_L'+str(index+1)
                if ident in model.get('Material',{}):raise ValueError('构造材料生成名称冲突。')
                model.setdefault('Material',{})[ident]=prop;after.append(ident)
            model['Construction'][name]=dict(outside_layer=after[0],**{'layer_'+str(i+1):v for i,v in enumerate(after[1:],1)})
            s['construction_name']=name
            audit.append(dict(surface=target,original=old,construction=name,layers_before=before,layers_after=after,
                library_name=entry['reference']['name'],revision=entry['reference']['revision'],order=entry['order'],
                outside_optics=outside,inside_optics=inside,material_names=[l['material']['name'] for l in layers]))
    return audit


def capability(record,catalog):
    from contracts import validate
    from model_adapter import capability as base_capability, compile_case, VerifiedReader
    try:
        errors=validate(record,catalog['sites'])
        if errors:raise ValueError('；'.join(errors))
        cap=base_capability(baseline(record),catalog)
        if not cap['supported']:return cap
        reader=VerifiedReader(catalog);model,_=compile_case(baseline(record),record['factors']['scope']['site_ids'][0],catalog,reader)
        apply(model,record);reader.unchanged();return dict(supported=True,reasons=[],case='LIBRARY_CONSTRUCTION')
    except (ValueError,KeyError,TypeError,AttributeError,OSError) as e:return dict(supported=False,reasons=[str(e)])


def compile_case(record,site_id,catalog,reader=None,operation_mode=None):
    from contracts import validate
    from model_adapter import compile_case as base_compile, VerifiedReader,changes
    errors=validate(record,catalog['sites'])
    if errors:raise ValueError('；'.join(errors))
    reader=reader or VerifiedReader(catalog)
    model,report=base_compile(baseline(record),site_id,catalog,reader,operation_mode)
    before=copy.deepcopy(model);report['library_constructions']=apply(model,record)
    report['differences']=report.get('differences',[])+changes(before,model)
    report.update(generated_model_digest=digest(model),exact_input_match=False,construction_adapter='fixed_library_construction_v1')
    return model,report


def preview(root,record,catalog,target,selection):
    from model_adapter import compile_case,VerifiedReader,capability
    from surface_materials import baseline as material_baseline,target_rows
    if not isinstance(target,dict) or set(target)!={'id','revision','sha256'}:raise ValueError('请选择明确的构造版本。')
    row=next((r for r in Library(root).all('construction') if r['id']==target['id'] and r['revision']==target['revision'] and r['sha256']==target['sha256']),None)
    if not row:raise ValueError('构造版本不存在或已变化。')
    validate_content(row['content'])
    if not isinstance(selection,dict) or set(selection)!={'scope','order','confirmed'} or selection['confirmed'] is not True:raise ValueError('请确认室外至室内层序及表面光学处理。')
    if selection['scope'] not in ('walls','roofs'):raise ValueError('首批支持外墙或屋面。')
    out=copy.deepcopy(record);base=material_baseline(baseline(record));reader=VerifiedReader(catalog)
    model,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
    targets=[r['id'] for r in target_rows(model) if r['type']==('Wall' if selection['scope']=='walls' else 'Roof')]
    entry=dict(reference=row,target_ids=targets,order=selection['order'],optics_basis='retain_target_surface_optics')
    kept=[]
    for old in out['factors']['building'].get(KEY,[]):
        remaining=[i for i in old['target_ids'] if i not in targets]
        if remaining:kept.append({**old,'target_ids':remaining})
    out['factors']['building'][KEY]=kept+[entry]
    audit=apply(model,out);reader.unchanged()
    cap=capability(out,catalog)
    if not cap['supported']:raise ValueError('选用后暂不支持计算：'+'；'.join(cap['reasons']))
    return dict(building=out['factors']['building'],audit=audit,record_sha256=digest(record),
        note='按明确方向替换所选外表面构造；保留几何、边界、原内外表面光学和未选构件。采用后仍需保存方案版本。')
