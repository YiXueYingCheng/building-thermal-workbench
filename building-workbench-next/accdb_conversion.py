"""Convert inspected snapshots, normalize bindings and publish no implicit calculation."""
import copy,csv,math,os,shutil,tempfile,uuid,zipfile
from pathlib import Path
from foundation import read_json,write_json,sha,digest,now,config,owned
from accdb_import import ref,verify_inspection,validate_request,backend,table_data,index,schedules,pair,source_rule,run_command,check_cancel,inspect_doors,door_mapper,folder,CHANNELS,TEMPS


def validation_workspace(root,p):
 """Keep unpublished import checks isolated without repeating deep directory trees."""
 root=Path(root).resolve();p=Path(p).resolve()
 if folder(root,p.name)!=p:raise ValueError('导入核对目录不属于当前工作区。')
 for attempt in range(32):
  target=owned(root/'data/checks'/('c_'+uuid.uuid4().hex[:12]),root)
  if not target.exists():break
 else:raise ValueError('无法分配独立的核对目录，请稍后重试。')
 # Include both the staging and published names, plus a small random-name
 # margin. Names are aliases; origin.json/manifest.json retain full bindings.
 longest=target/'data/model-inputs'/('i_'+'0'*12)/('t-'+'0'*16+'.tmp')
 length=len(str(longest).encode('utf-16-le'))//2
 if os.name=='nt' and length>=260:
  # Do not reject an existing installation which already supports long paths.
  # Probe this process without changing any Windows policy or source file.
  try:
   with tempfile.TemporaryDirectory(prefix='.import-path-',dir=root/'data') as temporary:
    probe=owned(temporary,root)
    name='p'*max(1,length-len(str(probe).encode('utf-16-le'))//2-1)
    with (probe/name).open('xb') as stream:stream.write(b'')
  except OSError as error:
   if isinstance(error,FileNotFoundError) or getattr(error,'winerror',None)==206 or error.errno==36:
    raise ValueError('工作区路径过长，当前 Windows 无法保存导入核对临时文件。请在较短目录（例如 D:\\WB）使用独立工作区重新导入；保留原工作区和已有资料。当前工作区：'+str(root)) from error
   raise
 return target

def building_weather_site(ident, site, weather):
 from weather_quality import station_geography
 frozen=ref(weather)
 return dict(id=ident+'_weather',name=site['name'],eligible=True,climate=site.get('climate'),
             weather=frozen,source_kind='checked_accdb_import',**station_geography(weather,frozen['sha256']))


def normalise(models,d,request,donors,out,checkpoint=lambda:None):
 from usage_schedules import expanded,actual_pair,apply_gains
 seq=schedules(d);groups=index(d['ROOM_GROUP'],'ROOM_GROUP_ID');types=index(d['ROOM_TYPE_DATA'],'ID')
 profiles=[];sources={};verified=0
 for r in d['ROOM']:
  checkpoint()
  rid='R'+str(r['ID']);g=groups[r['OF_ROOM_GROUP']];choice=request['mapping'][str(r['TYPE'])];selected=donors.get(str(r['TYPE']))
  rules={ch:source_rule(d,seq,r,ch) for ch in CHANNELS} if choice=='source' else copy.deepcopy(selected['rules'])
  hvac=None
  if g['IS_AC_ROOM']:
   if request['temperature']=='source':
    hvac={}
    for key,field in TEMPS.items():
     values=seq[g[field]]
     if len(set(values))!=1:raise ValueError(r['NAME']+'温控阈值含全年变化，不能默默替换。')
     hvac[key]=values[0]
   else:hvac=copy.deepcopy(request['thresholds'])
   hvac['available']=pair(seq[g['AC_SCHEDULE_ID']],r['NAME']+'空调可用',True) if request['availability']=='source' else dict(weekday=[1]*24,weekend=[1]*24)
  profile=dict(id=rid,zone=r['NAME'],area_m2=r['AREA'],conditioned=bool(g['IS_AC_ROOM']),loads=rules,hvac=hvac)
  if selected:profile['gain_settings']=copy.deepcopy(selected['gains'])
  profiles.append(profile)
  sources[rid]=dict(use=types[r['TYPE']]['NAME'],room_type_id=str(r['TYPE']),basis='保留数据库配置' if choice=='source' else '明确选用配置：'+selected.get('source_label','既有建筑房间原配置'),channels={ch:dict(rule=rules[ch],verified=True,weekday_name='源工作日',weekend_name='源周末') for ch in CHANNELS},selection=choice)
  for mode,m in models.items():
   def put(name,values,old=None,check=False):
    nonlocal verified
    if check:
     file=Path(m['Schedule:File'][old]['file_name']);actual=[float(x) for x in file.read_text('utf-8-sig').splitlines() if x.strip()]
     if len(actual)!=8760 or any(not math.isclose(x,y,rel_tol=1e-12,abs_tol=1e-9) for x,y in zip(actual,values)):raise ValueError('转换模型实际输入与源上下限/单位/计划不一致：'+name)
     verified+=len(values)
    target=out/'schedules'/(name+'.txt');target.parent.mkdir(exist_ok=True)
    target.write_text('\n'.join(format(v,'.17g') for v in values)+'\n','ascii')
    m.setdefault('Schedule:File',{})[name]=dict(schedule_type_limits_name='Any Number',file_name=str(target),column_number=1,rows_to_skip_at_top=0,number_of_hours_of_data=8760,column_separator='Comma',interpolate_to_timestep='No',minutes_per_item=60,adjust_schedule_for_daylight_savings='No')
   for ch,table in CHANNELS.items():
    rows=[x for x in d[table] if x['OF_ROOM']==r['ID']]
    if len(rows)!=1:raise ValueError('房间得热对象不能唯一映射。')
    key=f"{table}_{rows[0]['GAIN_ID']}";obj=m['People' if ch=='people' else 'ElectricEquipment'][key]
    field='number_of_people_schedule_name' if ch=='people' else 'schedule_name';name='Input_'+rid+'_'+ch
    put(name,expanded(rules[ch],r['AREA']),obj[field],choice=='source');obj[field]=name
   if hvac and mode=='controlled':
    for ch in (*TEMPS,'available'):
     name='Input_'+rid+'_'+ch;values=expanded(hvac[ch]) if ch=='available' else [hvac[ch]]*8760
     sensor=m['EnergyManagementSystem:Sensor'][rid+'_'+ch];old=sensor['output_variable_or_output_meter_index_key_name']
     put(name,values,old,(request['availability']=='source' if ch=='available' else request['temperature']=='source'))
     sensor['output_variable_or_output_meter_index_key_name']=name
     if ch in ('heat','cool'):
      m['ThermostatSetpoint:SingleHeating' if ch=='heat' else 'ThermostatSetpoint:SingleCooling'][rid+('_heating' if ch=='heat' else '_cooling')]['setpoint_temperature_schedule_name']=name
 for m in models.values():apply_gains(m,profiles)
 return profiles,sources,verified

def convert(p,request,catalog,root):
 check_cancel(p)
 from workspace_setup import import_numerics
 import_numerics(catalog)
 review=verify_inspection(p);donors,site=validate_request(request,review,catalog,root);code=backend(root);py=config(root)['python']
 validation_root=validation_workspace(root,p)
 if (p/'model').exists():raise ValueError('本次导入已有转换目录，请新建导入记录，避免覆盖证据。')
 if shutil.disk_usage(root).free<2*2**30:raise ValueError('转换前需至少保留 2 GiB 磁盘。')
 door_models,door_errors=inspect_doors(table_data(p),root)
 if door_errors:raise ValueError('；'.join(door_errors))
 door_mapper(root).validate_confirmation(request,door_models)
 door_choices=dict(door_confirmations={m['type_id']:m['confirmation_sha256'] for m in door_models},models=door_models)
 write_json(p/'door-mappings.json',door_choices,root)
 write_json(p/'choices.json',dict(request=request,door_models=door_models,donor_snapshots=donors,weather=site['weather']),root)
 # Preserve the scripts used without copying or mutating their external source tree.
 tool_files=[x for x in code.glob('*.py') if x.is_file()]
 tool_refs=[ref(x) for x in tool_files]
 with zipfile.ZipFile(p/'converter-source.zip','x',zipfile.ZIP_DEFLATED) as z:
  for x in tool_files:z.write(x,x.name)
 source=p/'source';model=p/'model';model.mkdir();(model/'conversion').mkdir();(model/'weather').mkdir()
 weather=model/'weather'/Path(site['weather']['path']).name;shutil.copy2(site['weather']['path'],weather)
 if sha(weather)!=site['weather']['sha256']:raise ValueError('复制期间气象已变化。')
 ident='accdb_'+p.name.removeprefix('import_')
 args=[py,code/'convert_drawing26.py','--tables',p/'tables','--source',source,'--source-original',source,'--output',model/'source-mapped','--project-id',ident,'--confirmed-door-mappings',p/'door-mappings.json','--align-world-north']
 if config(root)['converter_interface']=='portable':args += ['--reference-tables',config(root)['import_reference_tables'],'--destep-source',code/'destep-source.zip']
 if request['shading']=='ignore':args.append('--ignore-shading')
 run_command(args,p/'convert.log',p)
 run_command([py,code/'check_source_openings.py','--tables',p/'tables','--output',model/'conversion'],p/'openings.log',p)
 opening=read_json(model/'conversion/physical-opening-check.json')
 if opening['out_of_boundary_count']:raise ValueError('门窗超出实体边界，未加入建筑列表；请核对 physical-opening-check.json。')
 run_command([py,code/'build_drawing26_models.py','--source',p,'--output',model,'--project-id',ident,'--city',site['name'],'--weather',weather,'--weather-source-url','已登记气象快照，见 choices.json'],p/'assemble.log',p)
 for r in tool_refs:
  if sha(r['path'])!=r['sha256']:raise ValueError('转换期间后端程序已变化，不能登记此次模型。')
 verify_inspection(p)
 d=table_data(p);models={mode:read_json(model/('model-'+mode+'.epJSON')) for mode in ('controlled','natural')}
 for m in models.values():
  for item in m['Schedule:File'].values():item['file_name']=str((model/item['file_name']).resolve())
 profiles,sources,verified=normalise(models,d,request,donors,model,checkpoint=lambda:check_cancel(p))
 from building_configuration import extract,validate_content
 from model_adapter import VerifiedReader,build_bundle
 from ordinary_envelope import inventory
 deps=list({v['file_name']:ref(v['file_name']) for m in models.values() for v in m['Schedule:File'].values()}.values())
 usage=extract(models['controlled'],VerifiedReader(),deps);usage['building_id']=ident;usage['baseline_sha256']=digest(usage)
 envelope=inventory(models['controlled'])
 if envelope!=inventory(models['natural']) or models['controlled']['Zone']!=models['natural']['Zone'] or models['natural'].get('ZoneHVAC:IdealLoadsAirSystem'):raise ValueError('自然/温控建筑实体不一致。')
 if len(usage['rooms'])!=review['rooms'] or sum(r['conditioned'] for r in usage['rooms'])!=review['conditioned'] or not math.isclose(sum(r['area_m2'] for r in usage['rooms']),review['area_m2'],abs_tol=1e-8):raise ValueError('房间、面积或空调归属与数据库不一致。')
 # Extracted defaults, not inferred presets, are the binding identity of this imported building.
 validate_content(usage,usage)
 for mode,m in models.items():write_json(model/('configured-'+mode+'.epJSON'),m,root)
 model_refs={mode:ref(model/('configured-'+mode+'.epJSON')) for mode in models}
 from workspace_setup import import_numerics
 numerics=import_numerics(catalog)
 building=dict(id=ident,name=request['name'].strip(),zones=review['rooms'],floors=review['storeys'],area_m2=review['area_m2'],conditioned_area_m2=sum(r['area_m2'] for r in usage['rooms'] if r['conditioned']),definition_status='checked_accdb_import',source_project_id=ident,model_snapshot=model_refs['controlled'],input_snapshot=ref(p/'choices.json'))
 registered_site=building_weather_site(ident,site,weather)
 audits=[p/'inspection.json',p/'door-mappings.json',p/'choices.json',p/'extraction.json',p/'converter-source.zip',model/'conversion/physical-opening-check.json',model/'conversion/model-audit.json',model/'source-mapped/conversion-audit.json',model/'source-mapped/orientation-verification.json']
 refs=[review['snapshot'],*review['table_refs'],*[ref(x) for x in audits]]
 audit=read_json(model/'conversion/model-audit.json')
 notes=['ACCDB 来源快照和转换输入已核对；尚未进行本建筑的 EnergyPlus 试算。',f"保留源 {review['conditioned']} 间空调房、{review['rooms']-review['conditioned']} 间非空调房。",
  '当前使用 '+site['name']+'、5 min、周一元旦日历、直接接地 Kiva 和已确认默认土壤。',
  '配置来源按房间类型明确选择；借用配置按其已声明单位换算到目标面积，人员潜热保持源库。',
  '动态材料、其他气象地点及更多层位需另行适配。']
 payload=dict(building=building,usage=usage,models=model_refs,dependencies=deps,source_refs=refs,weather=ref(weather),numerics=numerics,site=registered_site,envelope=envelope,usage_sources=sources,notes=notes,
  source_limitations=audit['assumptions'],evidence=dict(source_annual_values_checked=verified,engine_run=False,geometric_checks=True,source_sha256=review['source']['sha256'],conversion_programs=tool_refs))
 payload['snapshot_id']=digest(payload)
 from legacy_import import base_record
 record=base_record(ident+'_reference',building['name']+' · 导入原配置',payload['snapshot_id'],'ordinary_building_v1')
 record['factors']=dict(building=building,materials=dict(definitions=[],applications=[]),condition=dict(operation=dict(mode='controlled',settings='ordinary_usage',load_basis='sensible_demand'),controls=[],reference_runs=[]),scope=dict(site_ids=[registered_site['id']],period=[1,1,12,31],aggregation=dict(kind='site_results')))
 record['numerics']=numerics;record['provenance'].update(source_refs=refs,notes=notes);payload['record']=record
 # Exercise the same model-input route used by future saved schemes, in an isolated staging root.
 probe=copy.deepcopy(catalog);probe.setdefault('ordinary_buildings',{})[ident]=payload;probe['records'][record['id']]=record;probe['sites'][registered_site['id']]=registered_site
 test=copy.deepcopy(record);test['factors']['condition']['operation']['mode']='both'
 validation_root.mkdir(parents=True,exist_ok=False)
 write_json(validation_root/'config.json',config(root),validation_root)
 write_json(validation_root/'origin.json',dict(kind='building_import_input_check_v1',import_id=p.name,import_path=str(p.resolve()),created=now()),validation_root)
 bundle=build_bundle(test,probe,validation_root,compact_check=True)
 check_cancel(p)
 if bundle['case_count']!=2:raise ValueError('自然/温控输入核对未完成。')
 validation=dict(root=str(validation_root),manifest=ref(validation_root/'data/model-inputs'/bundle['id']/'manifest.json'),case_count=bundle['case_count'])
 write_json(p/'input-validation.json',validation,root)
 write_json(p/'source-record.json',payload,root)
 acceptance=dict(passed=True,created=now(),sha256=digest(payload),building=building,source_sha256=review['source']['sha256'],
  rooms=review['rooms'],conditioned=review['conditioned'],area_m2=review['area_m2'],surfaces=len(envelope),source_annual_values_checked=verified,
  geometry=dict(openings_outside=0,orientation=read_json(model/'source-mapped/orientation-verification.json')),bundle_id=bundle['id'],input_cases=2,
  choices=request,door_models=door_models,input_validation=validation,notes=notes,engine_run=False,new_simulations=0)
 write_json(p/'acceptance.json',acceptance,root);return acceptance
