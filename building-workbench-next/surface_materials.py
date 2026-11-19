"""Fixed physical layers and effective surface optics on opaque exterior surfaces.

Uses the original wall construction. It never reuses the ECA movable-insulation
scaffold, and never switches physical thickness or storage during a run.
"""
import copy
from foundation import digest
import material_types


def enabled(record):
    return any(material_types.supported(d) for d in record['factors']['materials'].get('definitions',[]))


def baseline(record):
    r=copy.deepcopy(record)
    restore_reference_step(r)
    r['factors']['materials']=dict(definitions=[], applications=[])
    r['factors']['condition']['controls']=[]
    r['factors']['condition']['reference_runs']=[]
    return r


def restore_reference_step(r):
    for control in r['factors']['condition'].get('controls',[]):
        if control.get('mode')=='feedback' and 'reference_step_minutes' in control and enabled(r):
            r['numerics']['step_minutes']=control['reference_step_minutes']


def specification(record):
    from contracts import normalize
    r=normalize(record); f=r['factors']; m=f['materials']
    if set(m)-{'definitions','applications','definition_reference'} or len(m['definitions'])!=1 or len(m['applications'])!=1:
        raise ValueError('当前支持一种材料的一组外表面应用。')
    d=m['definitions'][0]; errors=material_types.validate(d,complete=True)
    if errors:raise ValueError('；'.join(errors))
    a=m['applications'][0]
    if set(a)!={'id','material_id','component','position','target_ids','placement_basis'} or a['position']!='exterior' or a['component']!='opaque_exterior' or a['placement_basis']!='fixed_surface_material_v1' or a['material_id']!=d['id']:
        raise ValueError('此入口只支持不透明墙面／屋面的外表面。')
    if not a['target_ids'] or len(a['target_ids'])!=len(set(a['target_ids'])):raise ValueError('请选择不重复的外墙或屋面。')
    controls=f['condition']['controls']
    if f['condition']['reference_runs'] or len(controls)!=2 or any(c.get('mode')!='fixed' for c in controls):
        raise ValueError('新实体材料当前支持固定状态计算；表面光学切换或动态热阻需相应材料专项校准，不能沿用 ECA 控制。')
    states={s['id']:s for s in d['states']}; chosen={}
    for c in controls:
        channel=c.get('channel');key='state_id' if channel=='thermal' else 'face_id'
        if channel not in ('thermal','orientation') or channel in chosen or set(c)!={'application_id','channel','mode','target_ids',key} or c['application_id']!=a['id'] or set(c['target_ids'])!=set(a['target_ids']):raise ValueError('请为全部应用表面指定唯一的固定状态和外表面光学参数组。')
        chosen[channel]=c[key]
    if chosen.get('thermal') not in states or chosen.get('orientation') not in d['faces']:raise ValueError('材料状态或表面不存在。')
    state=states[chosen['thermal']];key=chosen['orientation']+'_'+(chosen['thermal'] if d['optics_depend_on_state'] else 'R')
    optics=d['optics'].get(key,{})
    if any(optics.get(k) is None for k in ('solar_absorptance','emissivity')):raise ValueError('请补齐所选光学参数组的有效太阳吸收率和长波发射率。')
    return dict(definition=d, state=state, optics=optics, targets=a['target_ids'], face=chosen['orientation'])


def target_rows(model):
    return [dict(id=k, type=v['surface_type'], zone=v['zone_name']) for k,v in model.get('BuildingSurface:Detailed',{}).items()
        if v.get('surface_type') in ('Wall','Roof') and v.get('outside_boundary_condition')=='Outdoors']


def apply(model, record):
    spec=specification(record); d=spec['definition']; optical_only=d['model']=='optical_surface_v1'
    eligible={r['id'] for r in target_rows(model)}
    if not set(spec['targets'])<=eligible:raise ValueError('应用范围包含非不透明外墙／屋面。')
    changed=[]
    for target in spec['targets']:
        if any(x.get('surface_name')==target for x in model.get('SurfaceControl:MovableInsulation',{}).values()):raise ValueError('目标表面已有活动保温层，需先核对组合。')
        surface=model['BuildingSurface:Detailed'][target];old=surface['construction_name'];c=model['Construction'][old]
        layers=[c['outside_layer']]+[c[k] for k in sorted((k for k in c if k.startswith('layer_')),key=lambda k:int(k.split('_')[1]))]
        if set(c)!={'outside_layer',*('layer_'+str(i) for i in range(2,len(layers)+1))}:raise ValueError('原构造含未支持字段。')
        kinds=[k for k in ('Material','Material:NoMass') if layers[0] in model.get(k,{})]
        if len(kinds)!=1:raise ValueError('外表面须为已核对的不透明实体层或无蓄热层。')
        base=copy.deepcopy(model[kinds[0]][layers[0]])
        explicit_visible=spec['optics'].get('visible_absorptance')
        visible=dict(value=explicit_visible if explicit_visible is not None else base.get('visible_absorptance',.7),
            source='user_override' if explicit_visible is not None else 'target_outer_layer' if 'visible_absorptance' in base else 'engine_default',
            original_material=layers[0],original_kind=kinds[0],original_value=base.get('visible_absorptance'),default_value=.7)
        name='NX_Surface_'+digest([target,spec])[:24]
        if optical_only:
            kind=kinds[0];values=base
            if len(layers)==1:
                # The pinned EP 26.2 schema supports independent inside-face fields
                # for Material and Material:NoMass. Preserve effective inner optics
                # before changing the bulk values used on the outside face.
                for field,default in (('solar_absorptance',.7),('thermal_absorptance',.9),('visible_absorptance',.7)):
                    values.setdefault(field+'_inside_face',base.get(field,default))
        else:
            if len(layers)>=10:raise ValueError('原构造层数已达上限。')
            kind='Material';s=spec['state']
            values=dict(roughness='MediumSmooth',thickness=s['thickness_mm']/1000,conductivity=s['conductivity_W_mK'],
                density=s['density_kg_m3'],specific_heat=s['specific_heat_J_kgK'],visible_absorptance=base.get('visible_absorptance',.7))
        values.update(solar_absorptance=spec['optics']['solar_absorptance'],thermal_absorptance=spec['optics']['emissivity'])
        if spec['optics'].get('visible_absorptance') is not None:values['visible_absorptance']=spec['optics']['visible_absorptance']
        if name in model.get(kind,{}):raise ValueError('新表面材料名称冲突。')
        model.setdefault(kind,{})[name]=values
        after=[name]+(layers[1:] if optical_only else layers)
        cname=name+'_Construction'
        if cname in model['Construction']:raise ValueError('新构造名称冲突。')
        model['Construction'][cname]=dict(outside_layer=after[0],**{'layer_'+str(i+1):v for i,v in enumerate(after[1:],1)})
        surface['construction_name']=cname
        changed.append(dict(surface=target,original=old,construction=cname,layers_before=layers,layers_after=after,visible_absorptance=visible,
            preserved_inside_optics={key:values[key+'_inside_face'] for key in ('solar_absorptance','thermal_absorptance','visible_absorptance')} if optical_only and len(layers)==1 else None))
    return dict(model=d['model'],state=spec['state']['id'],state_name=spec['state']['name'],face=spec['face'],surfaces=changed,
        physical=material_types.state_summary(spec['state']),
        note='仅替换覆盖后的表面光学；原层厚度、导热率、密度、比热保持' if optical_only else '增加固定实体层；使用真实厚度、导热率、密度及比热，无运行中切换')


def capability(record,catalog):
    from model_adapter import capability as base_capability, compile_case, VerifiedReader
    from contracts import validate
    try:
        errors=validate(record,catalog['sites'])
        if errors:raise ValueError('；'.join(errors))
        import surface_controls
        if surface_controls.active(record):
            compile_case(record,record['factors']['scope']['site_ids'][0],catalog,operation_mode='controlled')
            return dict(supported=True,reasons=[],case='CONTROLLED_PHYSICAL_SURFACE')
        specification(record)
        base=baseline(record);cap=base_capability(base,catalog)
        if not cap['supported']:return cap
        reader=VerifiedReader(catalog);m,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
        apply(m,record);reader.unchanged()
        return dict(supported=True,reasons=[],case='FIXED_PHYSICAL_SURFACE')
    except (ValueError,KeyError,TypeError,AttributeError,OSError) as e:return dict(supported=False,reasons=[str(e)])


def compile_case(record,site_id,catalog,reader=None,operation_mode=None):
    from model_adapter import compile_case as base_compile, changes, VerifiedReader
    from contracts import validate
    errors=validate(record,catalog['sites'])
    if errors:raise ValueError('；'.join(errors))
    import surface_controls
    dynamic=surface_controls.active(record)
    if dynamic:surface_controls.controls(record)
    else:specification(record)
    reader=reader or VerifiedReader(catalog)
    model,report=base_compile(baseline(record),site_id,catalog,reader,operation_mode)
    before=copy.deepcopy(model)
    if dynamic:
        from calendar_library import active_references, verify_for_site, bound
        refs=active_references(record);calendar=None
        if refs:
            verify_for_site(record,catalog,site_id,reader)
            row=bound(record,catalog,refs[0])[site_id]
            calendar=row['calendar']
            report['calendar_binding']=dict(site_id=site_id,calendar_sha256=row['calendar_sha256'],weather_sha256=row['weather_sha256'])
        report['material_application']=surface_controls.apply(model,record,calendar)
        report['step_minutes']=record['numerics']['step_minutes']
        reader.unchanged()
    else:report['material_application']=apply(model,record)
    from drawing_wall_scope import available, generated
    if available(record) and all(before['BuildingSurface:Detailed'][t]['surface_type']=='Wall' for t in record['factors']['materials']['applications'][0]['target_ids']):
        source = catalog.get('ordinary_buildings', {}).get(record['factors']['building']['id'])
        conditioned = {r['zone']:r['conditioned'] for r in source['usage']['rooms']} if source else None
        report['drawing_wall_scope']=generated(record,before,model,report['material_application'],conditioned)
    report['differences']=report.get('differences',[])+changes(before,model)
    report.update(generated_model_digest=digest(model),exact_input_match=False,untouched_fields_match=True,
        numerical_equivalence='physical_control_requires_result_review' if dynamic else 'fixed_physical_material_requires_result_review',
        material_adapter='controlled_surface_material_v1' if dynamic else 'fixed_surface_material_v1')
    return model,report


def adoption(record,row,catalog,state_id='R',face='A',targets=None):
    from contracts import normalize,validate
    from model_adapter import compile_case,VerifiedReader,changes
    if record['factors']['condition']['reference_runs'] or any(c.get('mode')!='fixed' for c in record['factors']['condition']['controls']):raise ValueError('当前方案有反馈或光学切换日历；请先另存并明确改为固定工况，再采用新类别材料。')
    base=baseline(record);reader=VerifiedReader(catalog)
    model,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
    rows=target_rows(model);targets=targets if targets is not None else [r['id'] for r in rows if r['type']=='Wall']
    out=copy.deepcopy(record);f=out['factors'];d=copy.deepcopy(row['content'])
    f['materials']=dict(definitions=[d],definition_reference=copy.deepcopy(row),applications=[dict(id='surface_material',material_id=d['id'],component='opaque_exterior',position='exterior',target_ids=targets,placement_basis='fixed_surface_material_v1')])
    f['condition']['controls']=[dict(application_id='surface_material',channel='thermal',mode='fixed',target_ids=targets,state_id=state_id),dict(application_id='surface_material',channel='orientation',mode='fixed',target_ids=targets,face_id=face)]
    out=normalize(out);errors=validate(out,catalog['sites'])
    if errors:raise ValueError('；'.join(errors))
    audit=apply(model,out);reader.unchanged()
    return dict(target=row,materials=out['factors']['materials'],controls=out['factors']['condition']['controls'],
        differences=changes(record['factors']['materials'],out['factors']['materials']),
        control_differences=changes(record['factors']['condition']['controls'],out['factors']['condition']['controls']),
        notes=['按固定状态 '+audit['state_name']+'、固定 '+face+' 的预览；'+audit['note'], '可选外表面 '+str(len(rows))+' 个，本次明确采用 '+str(len(targets))+' 个。'],
        available_targets=rows,audit=audit,record_sha256=digest(record),generation=dict(supported=True,reasons=[]))
