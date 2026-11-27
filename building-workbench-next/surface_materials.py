"""Fixed physical layers and effective surface optics on opaque exterior surfaces.

Uses the original wall construction. It never reuses the ECA movable-insulation
scaffold, and never switches physical thickness or storage during a run.
"""
import copy
import math
from foundation import digest
import material_types
import research_materials as research
import composite_materials as stack

FIXED_MOVABLE='fixed_exterior_movable_v1'

def enabled(record):
    m = record['factors']['materials']
    return any(material_types.supported(d) for d in m.get('definitions',[])) or any(
        d.get('model')=='equivalent_resistance_no_layer_storage' and a.get('material_id')==d.get('id')
        and a.get('placement_basis') in ('fixed_surface_material_v1',FIXED_MOVABLE)
        for d in m.get('definitions',[]) for a in m.get('applications',[]))


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
    d=m['definitions'][0]
    equivalent=d['model']=='equivalent_resistance_no_layer_storage'
    from contracts import validate_definitions
    errors=validate_definitions([d])[1] if equivalent else material_types.validate(d,complete=True)
    if errors:raise ValueError('；'.join(errors))
    a=m['applications'][0]
    placements=('fixed_surface_material_v1',FIXED_MOVABLE) if equivalent else ('fixed_surface_material_v1',)
    if d['model'] == stack.MODEL:
        extra = {'after_layer'} if a['position']=='between' else set()
        if (set(a) != {'id','material_id','component','position','target_ids','placement_basis'} | extra
                or a['component']!='opaque_exterior' or a['material_id']!=d['id'] or a['placement_basis']!=stack.MODEL
                or a['position'] not in ('exterior','interior','between')
                or (extra and (type(a['after_layer']) is not int or a['after_layer']<1))):
            raise ValueError('请核对组合材料的构件与安装层位。')
    elif set(a)!={'id','material_id','component','position','target_ids','placement_basis'} or a['position']!='exterior' or a['component']!='opaque_exterior' or a['placement_basis'] not in placements or a['material_id']!=d['id']:
        raise ValueError('此入口只支持不透明墙面／屋面的外表面。')
    if not a['target_ids'] or len(a['target_ids'])!=len(set(a['target_ids'])):raise ValueError('请选择不重复的外墙或屋面。')
    controls=f['condition']['controls']
    if f['condition']['reference_runs'] or len(controls)!=2 or any(c.get('mode')!='fixed' for c in controls):
        raise ValueError('新实体材料当前支持固定状态计算；表面光学切换或动态热阻需相应材料专项校准，不能沿用 ECA 控制。')
    states={s['id']:s for s in d['states']}; chosen={}; outer_face=None
    for c in controls:
        channel=c.get('channel');key='state_id' if channel=='thermal' else 'face_id'
        fields={'application_id','channel','mode','target_ids',key}
        if d['model']==stack.MODEL and channel=='orientation' and 'calendar_step_minutes' in c:
            stack.calendar_step(c)
            fields.add('calendar_step_minutes')
        if d['model']==stack.MODEL and channel=='orientation' and c.get('face_basis')=='exposed_layer':
            fields.add('face_basis')
            outer_face=c.get('face_id')
            if a['position']!='exterior':
                raise ValueError('只有位于原构造外侧的组合才能指定室外表面光学组。')
        if channel not in ('thermal','orientation') or channel in chosen or set(c)!=fields or c['application_id']!=a['id'] or set(c['target_ids'])!=set(a['target_ids']):raise ValueError('请为全部应用表面指定唯一的固定状态和外表面光学参数组。')
        chosen[channel]=c[key]
    faces=('A','B') if equivalent else d['faces']
    if outer_face is not None:
        outer=stack.unpack(d)[0]
        faces=outer['leaf']['faces']
    if chosen.get('thermal') not in states or chosen.get('orientation') not in faces:raise ValueError('材料状态或表面不存在。')
    state=states[chosen['thermal']]
    if equivalent:
        resistance=state.get('resistance_m2K_W')
        if type(resistance) not in (float,int) or not math.isfinite(resistance) or resistance<=0:
            raise ValueError('该固定状态需要有效的正热阻。')
        if a['placement_basis']==FIXED_MOVABLE and any(
                type(s.get('resistance_m2K_W')) not in (float,int) or
                not math.isfinite(s['resistance_m2K_W']) or s['resistance_m2K_W']<=0 for s in states.values()):
            raise ValueError('活动保温层需用完整的状态热阻确定参考值及展开比例。')
    key=chosen['orientation']+'_'+(chosen['thermal'] if equivalent or d['optics_depend_on_state'] else 'R')
    optics=d['optics'].get(key,{})
    if outer_face is not None:
        optics=stack.outer_optics(outer,outer_face)
    if d['model']==research.SPECTRAL:
        from spectral_boundary import NATIVE_EPS
        p=d['spectral']
        alpha=1-p['emitter_sw_reflectance'] if p['variant']=='bare' else sum(research.solar_split(p))
        optics=dict(solar_absorptance=alpha,emissivity=NATIVE_EPS)
    if d['model']!=stack.MODEL and any(optics.get(k) is None for k in ('solar_absorptance','emissivity')):raise ValueError('请补齐所选光学参数组的有效太阳吸收率和长波发射率。')
    spec=dict(definition=d, state=state, optics=optics, targets=a['target_ids'], face=chosen['orientation'])
    if outer_face is not None:spec['outer_face']=outer_face
    return spec


def target_rows(model):
    return [dict(id=k, type=v['surface_type'], zone=v['zone_name']) for k,v in model.get('BuildingSurface:Detailed',{}).items()
        if v.get('surface_type') in ('Wall','Roof') and v.get('outside_boundary_condition')=='Outdoors']

def fixed_assignments(record):
    f=record['factors'];app=f['materials']['applications'][0]
    targets=app['target_ids']; assignments={}
    for channel,key in (('thermal','state_id'),('orientation','face_id')):
        values={}
        for c in f['condition']['controls']:
            if c['channel']!=channel:continue
            if (set(c)!={'channel','mode','application_id','target_ids',key} or c['mode']!='fixed'
                    or c['application_id']!=app['id'] or not c['target_ids']):
                raise ValueError('固定铺设需明确逐墙状态与朝外面。')
            for wall in c['target_ids']:
                if wall in values:raise ValueError('同一墙面重复分配了控制。')
                values[wall]=c[key]
        if set(values)!=set(targets):raise ValueError('铺设范围与控制墙号不一致。')
        assignments[channel]=values
    if any(c['channel'] not in assignments for c in f['condition']['controls']):
        raise ValueError('发现未识别的控制通道。')
    return {w:(assignments['thermal'][w],assignments['orientation'][w]) for w in targets}

def fixed_parts(record):
    f=record['factors']
    if (len(f['materials']['applications'])!=1 or len(f['materials']['definitions'])!=1 or
            f['materials']['definitions'][0]['model']!='equivalent_resistance_no_layer_storage' or
            len(f['condition']['controls'])<=2):
        return [record]
    groups={}
    for wall,pair in fixed_assignments(record).items():
        groups.setdefault(pair,[]).append(wall)
    parts=[]
    for (state,face),targets in groups.items():
        part=copy.deepcopy(record)
        app=part['factors']['materials']['applications'][0]
        app['target_ids']=targets
        part['factors']['condition']['controls']=[
            dict(application_id=app['id'],channel='thermal',mode='fixed',target_ids=targets,state_id=state),
            dict(application_id=app['id'],channel='orientation',mode='fixed',target_ids=targets,face_id=face)]
        parts.append(part)
    return parts

def apply_fixed(model, record):
    audits=[apply(model,part) for part in fixed_parts(record)]
    if len(audits)==1:return audits[0]
    return dict(model=audits[0]['model'],
        groups=[{k:v for k,v in a.items() if k!='surfaces'} for a in audits],
        surfaces=[dict(s,state=a['state'],face=a['face']) for a in audits for s in a['surfaces']])


def apply(model, record):
    spec=specification(record); d=spec['definition']; optical_only=d['model']=='optical_surface_v1'
    movable=record['factors']['materials']['applications'][0]['placement_basis']==FIXED_MOVABLE
    eligible={r['id'] for r in target_rows(model)}
    if not set(spec['targets'])<=eligible:raise ValueError('应用范围包含非不透明外墙／屋面。')
    if d['model']==stack.MODEL:
        return stack.install(model,spec,record['factors']['materials']['applications'][0])
    advanced=d['model'] in research.TYPES
    if advanced and any(model['BuildingSurface:Detailed'][k]['surface_type']!='Wall' for k in spec['targets']):
        raise ValueError('此材料接法适用于室外不透明墙，请核对选面。')
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
        if movable:
            # A fixed movable-insulation schedule uses the same reference R and
            # deployed fraction as the original exterior-insulation calculation.
            resistance=max(s['resistance_m2K_W'] for s in d['states'])
            fraction=spec['state']['resistance_m2K_W']/resistance
            layer=name+'_Insulation';schedule=name+'_Fraction';cname=name+'_Construction'
            limits=model.setdefault('ScheduleTypeLimits',{})
            fraction_limits=dict(lower_limit_value=0.,upper_limit_value=1.,numeric_type='Continuous')
            limit_name='NX_Insulation_Fraction'
            if limits.setdefault(limit_name,fraction_limits)!=fraction_limits:raise ValueError('保温层比例日程名称冲突。')
            entries=[(kinds[0],name,{**base,'solar_absorptance':spec['optics']['solar_absorptance']}),
                ('Construction',cname,{**c,'outside_layer':name}),
                ('Material:NoMass',layer,dict(roughness='MediumSmooth',thermal_resistance=resistance,
                    solar_absorptance=spec['optics']['solar_absorptance'],thermal_absorptance=spec['optics']['emissivity'],
                    visible_absorptance=visible['value'])),
                ('Schedule:Constant',schedule,dict(hourly_value=fraction,schedule_type_limits_name=limit_name)),
                ('SurfaceControl:MovableInsulation',name,dict(insulation_type='Outside',surface_name=target,
                    material_name=layer,schedule_name=schedule))]
            for kind,key,value in entries:
                if key in model.setdefault(kind,{}):raise ValueError('材料名称与原模型冲突。')
                model[kind][key]=value
            surface['construction_name']=cname
            changed.append(dict(surface=target,original=old,construction=cname,layers_before=layers,
                layers_after=[name,*layers[1:]],movable_material=layer,reference_R=resistance,
                factor=fraction,effective_R=spec['state']['resistance_m2K_W'],visible_absorptance=visible))
            continue
        if optical_only:
            kind=kinds[0];values=base
            if len(layers)==1:
                # The pinned EP 26.2 schema supports independent inside-face fields
                # for Material and Material:NoMass. Preserve effective inner optics
                # before changing the bulk values used on the outside face.
                for field,default in (('solar_absorptance',.7),('thermal_absorptance',.9),('visible_absorptance',.7)):
                    values.setdefault(field+'_inside_face',base.get(field,default))
        elif d['model']=='equivalent_resistance_no_layer_storage':
            if len(layers)>=10:raise ValueError('原构造层数已达上限。')
            kind='Material:NoMass'
            values=dict(roughness='MediumSmooth',thermal_resistance=spec['state']['resistance_m2K_W'],
                        visible_absorptance=visible['value'])
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
        if d['model']==research.PCM:
            research.pcm_layer(model,name,cname,spec['state'],d)
        surface['construction_name']=cname
        changed.append(dict(surface=target,original=old,construction=cname,layers_before=layers,layers_after=after,visible_absorptance=visible,
            preserved_inside_optics={key:values[key+'_inside_face'] for key in ('solar_absorptance','thermal_absorptance','visible_absorptance')} if optical_only and len(layers)==1 else None))
    if advanced:
        from spectral_boundary import request
        from ordinary_materials import measure
        for row in changed:
            wall=row['surface']
            gross,_=measure(model['BuildingSurface:Detailed'][wall])
            apertures=[(k,v) for k,v in model.get('FenestrationSurface:Detailed',{}).items() if v['building_surface_name']==wall]
            row.update(net_m2=gross-sum(measure(v)[0]*v.get('multiplier',1) for _,v in apertures),apertures=[k for k,_ in apertures])
            if row['net_m2']<=0:raise ValueError('外墙扣除洞口后的面积须为正。')
            for var in ('Surface Inside Face Conduction Heat Transfer Rate per Area','Surface Outside Face Conduction Heat Transfer Rate per Area','Surface Outside Face Temperature','Surface Outside Face Incident Solar Radiation Rate per Area'):
                request(model,wall,var)
            if d['model']==research.PCM:
                import math
                s=spec['state']
                delta=3600/next(iter(model['Timestep'].values()))['number_of_timesteps_per_hour']
                fd=next(iter(model['HeatBalanceSettings:ConductionFiniteDifference'].values()))
                dx=math.sqrt(fd.get('space_discretization_constant',3)*delta*s['conductivity_W_mK']/s['density_kg_m3']/s['specific_heat_J_kgK'])
                row['pcm_elements']=max(1,int((s['thickness_mm']/1000)/dx))
                for node in range(1,row['pcm_elements']+2):request(model,wall,'CondFD Surface Temperature Node '+str(node))
        if d['model']==research.SPECTRAL:
            import spectral_boundary
            spectral_boundary.apply(model,spec,changed)
        else:
            diagnostics=model.setdefault('Output:Diagnostics',{'WB diagnostics':{'diagnostics':[]}})
            keys=next(iter(diagnostics.values())).setdefault('diagnostics',[])
            if not any(x.get('key')=='DisplayAdvancedReportVariables' for x in keys):keys.append(dict(key='DisplayAdvancedReportVariables'))
    return dict(model=d['model'],state=spec['state']['id'],state_name=spec['state']['name'],face=spec['face'],surfaces=changed,
        physical=dict(resistance_m2K_W=spec['state']['resistance_m2K_W']) if d['model']=='equivalent_resistance_no_layer_storage' else material_types.state_summary(spec['state']),
        **({'research_parameters':d['phase_change'] if d['model']==research.PCM else d['spectral'],'net_m2':sum(x['net_m2'] for x in changed)} if advanced else {}),
        note='在所选表面外侧增加固定无蓄热层，采用所选状态的热阻与朝外面的光学参数。' if d['model']=='equivalent_resistance_no_layer_storage' else '在原墙外侧增加相变层，按焓温曲线计算储放热。' if d['model']==research.PCM else '在原墙外侧增加发射载体，按所选结构计算太阳吸收及分波段长波换热。' if d['model']==research.SPECTRAL else '仅替换覆盖后的表面光学；原层厚度、导热率、密度、比热保持' if optical_only else '增加固定实体层；使用真实厚度、导热率、密度及比热，无运行中切换')


def check_step(record):
    if any(d.get('model')==research.PCM or stack.has_pcm(d) for d in record['factors']['materials']['definitions']) and record['numerics']['step_minutes']>3:
        raise ValueError('EnergyPlus 相变有限差分需要每小时至少 20 步。请在计算安排中选择 1 或 2 分钟。')


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
        check_step(record)
        for part in fixed_parts(record):specification(part)
        base=baseline(record);cap=base_capability(base,catalog)
        if not cap['supported']:return cap
        reader=VerifiedReader(catalog);m,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
        apply_fixed(m,record);reader.unchanged()
        return dict(supported=True,reasons=[],case='FIXED_PHYSICAL_SURFACE')
    except (ValueError,KeyError,TypeError,AttributeError,OSError) as e:return dict(supported=False,reasons=[str(e)])


def compile_case(record,site_id,catalog,reader=None,operation_mode=None):
    from model_adapter import compile_case as base_compile, changes, VerifiedReader
    from contracts import validate
    errors=validate(record,catalog['sites'])
    if errors:raise ValueError('；'.join(errors))
    import surface_controls
    check_step(record)
    dynamic=surface_controls.active(record)
    if dynamic:surface_controls.controls(record)
    else:
        for part in fixed_parts(record):specification(part)
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
    else:report['material_application']=apply_fixed(model,record)
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


def adoption(record,row,catalog,state_id='R',face='A',targets=None,position='exterior',after_layer=None):
    from contracts import normalize,validate
    from model_adapter import compile_case,VerifiedReader,changes
    if record['factors']['condition']['reference_runs'] or any(c.get('mode')!='fixed' for c in record['factors']['condition']['controls']):raise ValueError('当前方案有反馈或光学切换日历；请先另存并明确改为固定工况，再采用新类别材料。')
    base=baseline(record);reader=VerifiedReader(catalog)
    model,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
    rows=target_rows(model);targets=targets if targets is not None else [r['id'] for r in rows if r['type']=='Wall']
    out=copy.deepcopy(record);f=out['factors'];d=copy.deepcopy(row['content'])
    f['materials']=dict(definitions=[d],definition_reference=copy.deepcopy(row),applications=[dict(id='surface_material',material_id=d['id'],component='opaque_exterior',position='exterior',target_ids=targets,placement_basis='fixed_surface_material_v1')])
    app=f['materials']['applications'][0]
    if d['model']==stack.MODEL:
        app.update(position=position,placement_basis=stack.MODEL)
        if after_layer is not None:app['after_layer']=after_layer
    elif position!='exterior' or after_layer is not None:
        raise ValueError('所选材料接法仅支持外侧。')
    f['condition']['controls']=[dict(application_id='surface_material',channel='thermal',mode='fixed',target_ids=targets,state_id=state_id),dict(application_id='surface_material',channel='orientation',mode='fixed',target_ids=targets,face_id=face)]
    out=normalize(out);errors=validate(out,catalog['sites'])
    if errors:raise ValueError('；'.join(errors))
    audit=apply(model,out);reader.unchanged()
    return dict(target=row,materials=out['factors']['materials'],controls=out['factors']['condition']['controls'],
        differences=changes(record['factors']['materials'],out['factors']['materials']),
        control_differences=changes(record['factors']['condition']['controls'],out['factors']['condition']['controls']),
        notes=['按固定状态 '+audit['state_name']+'、固定 '+face+' 的预览；'+audit['note'], '可选外表面 '+str(len(rows))+' 个，本次明确采用 '+str(len(targets))+' 个。'],
        available_targets=rows,audit=audit,record_sha256=digest(record),generation=dict(supported=True,reasons=[]))
