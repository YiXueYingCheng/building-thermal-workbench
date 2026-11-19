"""Fixed-state input adapter over verified Drawing26 model scaffolds; never executes."""
from __future__ import annotations
import copy
import csv
import math
from pathlib import Path
import re
import uuid
import threading
import shutil
import datetime as dt
import os
import tempfile
from contracts import normalize, validate, recipe_digest
from foundation import ROOT, read_json, write_json, digest, sha, now, owned, canonical

ADAPTER='drawing26_fixed_v1'
BUILD_LOCK=threading.Lock()

class NotSupported(ValueError):pass

def close(a,b):return math.isclose(a,b,rel_tol=1e-13,abs_tol=1e-14)

def fixed_capability(record,catalog):
    """Reject unsupported changes instead of silently dropping factor fields."""
    try:
        r=normalize(record);errors=validate(r,catalog['sites'])
        if errors:return dict(supported=False,reasons=errors)
        f=r['factors'];reference=catalog['records']['global_w00']
        if r['provenance']['adapter']!='global_frozen_v011' or f['building']!=reference['factors']['building']:
            raise NotSupported('当前模型生成支持已复核的 Drawing26 全球参考建筑。')
        if f['condition']['operation']!=reference['factors']['condition']['operation']:
            raise NotSupported('当前生成器保留原温控运行、设定点与作息；自然室温及运行覆盖待适配。')
        if any(x.get('kind')!='workspace_daily_calendar_v1' for x in f['condition'].get('reference_runs',[])):
            raise NotSupported('带参考日历的表面光学控制将在动态适配阶段开放。')
        if {k:v for k,v in r['numerics'].items() if k!='step_minutes'}!={k:v for k,v in reference['numerics'].items() if k!='step_minutes'}:
            raise NotSupported('计算引擎设置已改变，不能沿用本适配。')
        if any(not catalog['sites'][s].get('eligible') or catalog['sites'][s]['source_kind'] not in ('reviewed_global','imported_epw_v1') for s in f['scope']['site_ids']):
            raise NotSupported('当前仅生成已接受全球地点的输入；暂缓地点不会补为有效。')
        materials=f['materials'];defs=materials['definitions'];apps=materials['applications'];controls=f['condition']['controls']
        if materials.get('legacy_construction_overrides'):
            raise NotSupported('旧构造修改尚未接入本模型生成器。')
        if not defs and not apps and not controls:return dict(supported=True,reasons=[],case='W00')
        if len(defs)!=1 or len(apps)!=1:raise NotSupported('当前支持一个 ECA 等效层应用，或不添加材料的 W00。')
        d=defs[0];app=apps[0]
        if d['kind']!='single_layer' or d['model']!='equivalent_resistance_no_layer_storage' or {s['id'] for s in d['states']}!={'R','C'}:
            raise NotSupported('当前支持 R/C 独立状态的单层 ECA 等效热阻模型。')
        if app['position']!='exterior' or app['component']!='wall' or set(app['target_ids'])!=set(f['building']['wall_ids']):
            raise NotSupported('当前支持原 14 段外墙的外侧应用；其他构件、层位与安装范围待适配。')
        if app['orientation']!={'A':'cooling_face','B':'other_face'} or app['placement_basis']!='legacy_outer_equivalent_model':
            raise NotSupported('材料方向或应用模型已改变，需相应适配。')
        states={s['id']:s for s in d['states']}
        if any(s.get('resistance_m2K_W') is None for s in states.values()):raise NotSupported('请补全两个状态的热阻或厚度与导热系数。')
        maps={'thermal':{},'orientation':{}}
        for control in controls:
            if control['mode']!='fixed':raise NotSupported('当前只生成固定状态与固定光学参数组；反馈和日历控制待适配。')
            channel=control['channel']
            for target in control['target_ids']:
                if target in maps[channel]:raise NotSupported('同一构件存在重复控制指定。')
                maps[channel][target]=control['state_id'] if channel=='thermal' else control['face_id']
        if any(set(v)!=set(app['target_ids']) for v in maps.values()):raise NotSupported('每个应用构件都需要唯一的固定状态与光学参数组。')
        for target,state in maps['thermal'].items():
            optical=d['optics'].get(maps['orientation'][target]+'_'+state,{})
            if any(optical.get(k) is None for k in ('solar_absorptance','emissivity')):raise NotSupported('所选状态与外表面所选的光学参数尚未补全。')
        return dict(supported=True,reasons=[],case='FIXED_COOL_LOW7',assignments=maps)
    except (ValueError,KeyError,TypeError,AttributeError) as error:return dict(supported=False,reasons=[str(error)])

class VerifiedReader:
    """One generation request owns its verification cache. No cross-request trust cache."""
    def __init__(self,catalog=None):self.checked={};self.catalog=catalog;self.location_uses={}
    def check(self,ref):
        from source_locations import resolve
        actual,location=resolve(ref,self.catalog) if self.catalog else (ref,None)
        if location:self.location_uses[location['key']]=location
        p=Path(actual['path']);expected=ref.get('expected_sha256') or ref['sha256'];key=(str(p),expected)
        if key not in self.checked:
            if sha(p)!=expected:raise ValueError('来源内容已变化：'+str(p))
            self.checked[key]=dict(path=str(p),sha256=expected)
        return p
    def json(self,ref):
        p=self.check(ref);value=read_json(p)
        if sha(p)!=(ref.get('expected_sha256') or ref['sha256']):raise ValueError('来源读取期间发生变化。')
        return value
    def unchanged(self):
        for ref in self.checked.values():
            if sha(ref['path'])!=ref['sha256']:raise ValueError('生成期间来源发生变化：'+ref['path'])

def changes(before,after,path=()):
    if isinstance(before,dict) and isinstance(after,dict):
        rows=[]
        for key in sorted(set(before)|set(after)):
            if key not in before or key not in after:rows.append(dict(path=list(path+(key,)),before=before.get(key),after=after.get(key)))
            else:rows.extend(changes(before[key],after[key],path+(key,)))
        return rows
    if isinstance(before,list) and isinstance(after,list) and len(before)==len(after):
        return [r for i,(a,b) in enumerate(zip(before,after)) for r in changes(a,b,path+(i,))]
    return [] if before==after else [dict(path=list(path),before=before,after=after)]

def constant(lines,variable,value):
    prefix='SET '+variable+' = '
    found=[l for l in lines if l['program_line'].startswith(prefix)]
    if len(found)!=1:raise ValueError('固定模板赋值不唯一：'+variable)
    old=found[0]['program_line'][len(prefix):]
    if not close(float(old),value):found[0]['program_line']=prefix+format(value,'.15g')

def number(obj,key,value):
    if not close(obj[key],value):obj[key]=value

def compile_fixed_case(record,site_id,catalog,reader=None):
    r=normalize(record);cap=fixed_capability(r,catalog)
    if not cap['supported']:raise NotSupported('；'.join(cap['reasons']))
    if site_id not in r['factors']['scope']['site_ids']:raise ValueError('地点不在当前方案范围内。')
    from weather_import import job as weather_job,apply_location
    reader=reader or VerifiedReader(catalog);job=weather_job(catalog,site_id,cap['case'])
    original=reader.json(job['model']);model=copy.deepcopy(original)
    weather=reader.check(job['weather'])
    for ref in job['dependencies']:reader.check(ref)
    refs={str(Path(d['path']).resolve()) for d in job['dependencies']}
    for schedule in model.get('Schedule:File',{}).values():
        if str(Path(schedule['file_name']).resolve()) not in refs:raise ValueError('模型作息文件未在来源清单登记。')
    with weather.open(encoding='utf-8-sig') as stream:header=next(csv.reader(stream))
    location=dict(zip(('latitude','longitude','time_zone','elevation'),map(float,header[6:10])))
    if header[0]!='LOCATION' or len(location)!=4 or any(not math.isfinite(v) for v in location.values()):raise ValueError('气象位置头无效。')
    source_location=next(iter(model['Site:Location'].values()))
    adaptation=None
    if job.get('weather_adaptation'):adaptation=apply_location(model,catalog['sites'][site_id],location)
    elif any(not close(location[k],source_location[k]) for k in location):raise ValueError('气象位置或时区与冻结模型不一致。')
    if len(model['Timestep'])!=1 or len(model['RunPeriod'])!=1:raise ValueError('计算步长或运行时段不唯一。')
    step=r['numerics']['step_minutes'];next(iter(model['Timestep'].values()))['number_of_timesteps_per_hour']=60//step
    period=r['factors']['scope']['period'];rp=next(iter(model['RunPeriod'].values()))
    for key,value in zip(('begin_month','begin_day_of_month','end_month','end_day_of_month'),period):rp[key]=value
    weekdays=('Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday')
    old_rp=next(iter(original['RunPeriod'].values()))
    shift=(dt.date(2025,*period[:2])-dt.date(2025,old_rp['begin_month'],old_rp['begin_day_of_month'])).days
    if shift:
        anchor=old_rp.get('day_of_week_for_start_day')
        if anchor not in weekdays:raise NotSupported('来源时段缺少可延续的起始星期，需先明确日历。')
        rp['day_of_week_for_start_day']=weekdays[(weekdays.index(anchor)+shift)%7]
    walls=[];allowed={('Timestep',next(iter(model['Timestep'])),'number_of_timesteps_per_hour')}
    allowed.update(('RunPeriod',next(iter(model['RunPeriod'])),k) for k in ('begin_month','begin_day_of_month','end_month','end_day_of_month'))
    allowed.add(('RunPeriod',next(iter(model['RunPeriod'])),'day_of_week_for_start_day'))
    if adaptation:allowed.update(('Site:Location',next(iter(model['Site:Location'])),k) for k in location)
    if cap['case']!='W00':
        d=r['factors']['materials']['definitions'][0];states={s['id']:s for s in d['states']}
        reference=max(s['resistance_m2K_W'] for s in states.values());low=min(s['resistance_m2K_W'] for s in states.values())/reference
        programs=model['EnergyManagementSystem:Program'];init=programs['ECA_Initialize']['lines'];update=programs['ECA_Update']['lines']
        protocol=catalog['global_bundle']['protocol'];optics_unchanged=True;optical_lines=[]
        for surface in r['factors']['building']['wall_ids']:
            state=cap['assignments']['thermal'][surface];face=cap['assignments']['orientation'][surface]
            optical=d['optics'][face+'_'+state];resistance=states[state]['resistance_m2K_W'];factor=resistance/reference
            mi=next(v for v in model['SurfaceControl:MovableInsulation'].values() if v['surface_name']==surface)
            if mi['insulation_type']!='Outside':raise ValueError('模板材料位置不一致。')
            material=mi['material_name'];schedule=mi['schedule_name'];material_obj=model['Material:NoMass'][material]
            construction=model['BuildingSurface:Detailed'][surface]['construction_name'];substrate=model['Construction'][construction]['outside_layer']
            for key,value in [('thermal_resistance',reference),('solar_absorptance',optical['solar_absorptance']),('thermal_absorptance',optical['emissivity'])]:
                number(material_obj,key,value);allowed.add(('Material:NoMass',material,key))
            number(model['Material'][substrate],'solar_absorptance',optical['solar_absorptance']);allowed.add(('Material',substrate,'solar_absorptance'))
            number(model['Schedule:Constant'][schedule],'hourly_value',low);allowed.add(('Schedule:Constant',schedule,'hourly_value'))
            for suffix,value in [('R',factor),('Act',factor),('Want',low)]:constant(init,f'ECA_{surface}_{suffix}',value)
            if any(re.match(rf'SET ECA_{surface}_R = ',l['program_line']) for l in update):raise ValueError('模板包含非固定热学状态更新。')
            if not any(l['program_line']==f'SET ECA_{surface}_Act = ECA_{surface}_R' for l in update):raise ValueError('模板固定状态未绑定控制输出。')
            age=f'SET ECA_{surface}_Age = ECA_{surface}_Age + '
            for line in update:
                if line['program_line'].startswith(age):line['program_line']=age+str(step)
            for suffix,key in [('A','solar_absorptance'),('E','emissivity'),('B','solar_absorptance')]:
                actuator=model['EnergyManagementSystem:Actuator'][f'JR_{surface}_{suffix}']
                expected=substrate if suffix=='B' else material
                if actuator['actuated_component_unique_name']!=expected:raise ValueError('模板光学控制对象不一致。')
                optical_lines.append(dict(program_line=f'SET JR_{surface}_{suffix} = '+format(optical[key],'.15g')))
            optics_unchanged &= close(optical['solar_absorptance'],1-protocol['reflectance']) and close(optical['emissivity'],protocol['emissivity'])
            walls.append(dict(surface=surface,state_id=state,face_id=face,material=material,substrate=substrate,schedule=schedule,
                reference_R=reference,factor=factor,effective_R=resistance,solar_absorptance=optical['solar_absorptance'],emissivity=optical['emissivity']))
        if not optics_unchanged:programs['JR_Optics']['lines']=optical_lines
        for name in ('ECA_Initialize','ECA_Update','JR_Optics'):
            allowed.update(('EnergyManagementSystem:Program',name,'lines',i,'program_line') for i in range(len(programs[name]['lines'])))
    diff=changes(original,model)
    if any(tuple(row['path']) not in allowed for row in diff):raise ValueError('模型生成改变了允许范围以外的字段。')
    report=dict(adapter=ADAPTER,site_id=site_id,city=catalog['sites'][site_id]['name'],template_case=cap['case'],
        source_model=job['model'],weather=job['weather'],dependencies=job['dependencies'],
        source_model_digest=digest(original),generated_model_digest=digest(model),exact_input_match=not diff,
        differences=diff,wall_assignments=walls,step_minutes=step,period=period,untouched_fields_match=True,
        execution_enabled=False,numerical_equivalence='not_tested_no_simulation')
    if adaptation:report['weather_adaptation']={**adaptation,**job['weather_adaptation']}
    return model,report

def build_bundle(record,catalog,root=ROOT,site_ids=None,*,compact_check=False):
    with BUILD_LOCK:return _build_bundle(record,catalog,root,site_ids,compact_check=compact_check)

def _build_bundle(record,catalog,root,site_ids=None,*,compact_check=False):
    """Unique bundle, all supported cases; only small epJSON files and receipts are written."""
    root=Path(root).resolve();reader=VerifiedReader(catalog);compiled=[]
    scope_sites=record['factors']['scope']['site_ids']
    if site_ids is None:selected=scope_sites
    else:
        if not isinstance(site_ids,list) or not site_ids or any(not isinstance(s,str) for s in site_ids) or len(set(site_ids))!=len(site_ids) or not set(site_ids)<=set(scope_sites):
            raise ValueError('本批地点必须是已保存方案范围内的非重复子集。')
        selected=[s for s in scope_sites if s in site_ids]
    from workspace_setup import engine_files as bound_engine_files
    engine_files=bound_engine_files(record,catalog)
    for path,checksum in engine_files.items():reader.check(dict(path=path,sha256=checksum))
    modes=['controlled','natural'] if record['factors']['condition']['operation']['mode']=='both' else [None]
    for site in selected:
        for mode in modes:
            from source_locations import prepare_case
            compiled.append(prepare_case(*compile_case(record,site,catalog,reader,operation_mode=mode),reader))
    reader.unchanged()
    identity=dict(recipe=recipe_digest(normalize(record)),record=digest(record),adapter_sha256=digest({p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('construction_library.py'),Path(__file__).with_name('material_types.py'),Path(__file__).with_name('surface_materials.py'),Path(__file__).with_name('surface_controls.py'),Path(__file__).with_name('dynamic_adapter.py'),Path(__file__).with_name('calendar_library.py'),Path(__file__).with_name('calendar_preview.py'),Path(__file__).with_name('weather_import.py'),Path(__file__).with_name('source_locations.py')]+([Path(__file__).with_name('building_configuration.py'),Path(__file__).with_name('component_library.py'),Path(__file__).with_name('usage_schedules.py')] if __import__('building_configuration').has_configuration(record) else [])+([Path(__file__).with_name(n) for n in ('ordinary_building.py','ordinary_envelope.py','ordinary_materials.py','ordinary_orientation.py','solid_eca.py','solid_feedback.py','queue_calendar.py','transition_confirmation.py','building_configuration.py','component_library.py','usage_schedules.py')] if record['provenance']['adapter']=='ordinary_building_v1' else [])}))
    if reader.location_uses:identity['source_locations']=digest(reader.location_uses)
    if selected!=scope_sites:identity['selected_site_ids']=selected
    # Only private import checks use a short alias. Formal input IDs stay stable;
    # the complete identity and SHA-256 checks remain in either manifest.
    ident=('i_'+digest(identity)[:12]) if compact_check else ('inputs_'+digest(identity)[:32])
    folder=owned(root/'data/model-inputs'/ident,root)
    if folder.exists():
        saved=read_json(folder/'manifest.json')
        if saved.get('identity')!=identity or saved['case_count']!=len(compiled):raise ValueError('已有输入包清单不一致。')
        if read_json(folder/'record.json')!=record:raise ValueError('已有输入包绑定的方案快照发生变化。')
        for row,(model,report) in zip(saved['cases'],compiled):
            path=owned(folder/row['model_file'],folder)
            if sha(path)!=row['model_sha256'] or read_json(path)!=model:raise ValueError('已有输入包内容变化，请保留并核查。')
            if any(row.get(k)!=v for k,v in report.items()):raise ValueError('已有输入包差异清单发生变化。')
        return {**saved,'reused':True}
    estimated=sum(len(str(model).encode('utf-8')) for model,_ in compiled)*3
    if shutil.disk_usage(root).free<estimated+100*1024*1024:raise ValueError('可用空间不足以保存本批输入并保留 100 MB 余量。')
    final_folder=folder
    final_folder.parent.mkdir(parents=True,exist_ok=True)
    folder=owned(tempfile.mkdtemp(prefix='.p-',dir=final_folder.parent),root)
    rows=[]
    for index,(model,report) in enumerate(compiled,1):
        name=f'{index:03d}.epJSON';write_json(folder/name,model,root)
        rows.append(dict(**report,model_file=name,model_sha256=sha(folder/name)))
    manifest=dict(id=ident,created=now(),adapter='ordinary_building_v1' if record['provenance']['adapter']=='ordinary_building_v1' else ('drawing26_state_v1' if uses_dynamic_adapter(record) else ADAPTER),identity=identity,record_id=record['id'],revision=record['revision'],record_name=record['name'],
        recipe_sha256=recipe_digest(normalize(record)),cases=rows,case_count=len(rows),exact_matches=sum(r['exact_input_match'] for r in rows),
        generated_bytes=sum(p.stat().st_size for p in folder.iterdir() if p.is_file()),source_checks=len(reader.checked),verified_sources=list(reader.checked.values()),engine_files=engine_files,execution_enabled=False,new_simulations=0)
    if reader.location_uses:manifest['source_locations']=list(reader.location_uses.values())
    if selected!=scope_sites:manifest.update(selected_site_ids=selected,scope_site_count=len(scope_sites),partial_scope=True)
    write_json(folder/'record.json',record,root)
    # Full-building schedule diffs contain long arrays. Keep every audit value,
    # but avoid indentation pushing an otherwise readable manifest above 32 MiB.
    # The staging folder is unpublished until the atomic rename below.
    manifest_bytes=canonical(manifest).encode('utf-8')
    if len(manifest_bytes)>32*1024*1024:
        raise ValueError('输入清单超过 32 MiB；请缩小本批地点范围或分别生成运行模式，已有输入保留。')
    with (folder/'manifest.json').open('xb') as stream:
        stream.write(manifest_bytes);stream.flush();os.fsync(stream.fileno())
    # Both absolute paths are verified inside the same owned workspace before moving.
    owned(folder,root);owned(final_folder,root);folder.rename(final_folder)
    return manifest

def uses_dynamic_adapter(record):
    return record['provenance']['adapter']=='legacy_plan_v011' or any(c['mode']!='fixed' for c in record['factors']['condition']['controls'])

def base_capability(record,catalog,reference_context=None):
    if uses_dynamic_adapter(record):
        from dynamic_adapter import capability as dynamic_capability
        return dynamic_capability(record,catalog,reference_context)
    return fixed_capability(record,catalog)

def compile_base_case(record,site_id,catalog,reader=None,operation_mode=None,reference_context=None):
    if uses_dynamic_adapter(record):
        from dynamic_adapter import compile_dynamic
        return compile_dynamic(record,site_id,catalog,reader,operation_mode,reference_context)
    return compile_fixed_case(record,site_id,catalog,reader)


def capability(record,catalog):
    import surface_materials
    if surface_materials.enabled(record):return surface_materials.capability(record,catalog)
    import construction_library
    if construction_library.enabled(record):return construction_library.capability(record,catalog)
    from calendar_library import check_active
    try:check_active(record,catalog)
    except (ValueError,KeyError,TypeError,OSError) as error:return dict(supported=False,reasons=[str(error)])
    from ordinary_building import supported_source,capability as ordinary_capability
    if supported_source(record):return ordinary_capability(record,catalog)
    from building_configuration import has_configuration,baseline,resolve
    if not has_configuration(record):return base_capability(record,catalog)
    try:
        base,_,_=baseline(catalog);shim,_=resolve(record,catalog,base)
        return base_capability(shim,catalog,reference_context=record)
    except (ValueError,KeyError,TypeError,AttributeError,OSError) as error:return dict(supported=False,reasons=[str(error)])

def compile_case(record,site_id,catalog,reader=None,operation_mode=None):
    import surface_materials
    if surface_materials.enabled(record):return surface_materials.compile_case(record,site_id,catalog,reader,operation_mode)
    import construction_library
    if construction_library.enabled(record):return construction_library.compile_case(record,site_id,catalog,reader,operation_mode)
    from calendar_library import check_active
    check_active(record,catalog)
    from ordinary_building import supported_source,compile_case as ordinary_compile
    if supported_source(record):return ordinary_compile(record,site_id,catalog,reader or VerifiedReader(catalog),operation_mode)
    from building_configuration import has_configuration,compile_configured
    if has_configuration(record):return compile_configured(record,site_id,catalog,reader,operation_mode)
    return compile_base_case(record,site_id,catalog,reader,operation_mode)
