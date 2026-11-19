"""Drawing26 usage defaults and explicit operation overlays, on verified templates."""
import copy,math,re
from pathlib import Path
from foundation import digest
from component_library import verify

CHANNELS=('people','lighting','equipment')
TEMPERATURES=('low','heat','cool','high')
HVAC_KINDS=('Schedule:Constant','EnergyManagementSystem:Sensor','EnergyManagementSystem:Actuator','EnergyManagementSystem:Program','ThermostatSetpoint:SingleHeating','ThermostatSetpoint:SingleCooling','ZoneControl:Thermostat','ZoneHVAC:IdealLoadsAirSystem','ZoneHVAC:EquipmentList','ZoneHVAC:EquipmentConnections')
def has_configuration(record):
 return bool(record['factors']['building'].get('usage_profile') or record['factors']['condition']['operation'].get('overrides') or record['factors']['condition']['operation'].get('settings')=='drawing26_usage')

def schedule_values(model,name,reader,dependencies):
 from inspection_io import current,resolve_path
 if name in model.get('Schedule:Constant',{}):return [model['Schedule:Constant'][name]['hourly_value']]*8760
 obj=model['Schedule:File'][name]
 if obj['number_of_hours_of_data']!=8760 or obj.get('minutes_per_item',60)!=60 or obj.get('column_number',1)!=1 or obj.get('rows_to_skip_at_top',0)!=0:raise ValueError('原计划不是已核实的逐小时单列全年数据。')
 index=getattr(reader,'schedule_reference_index',None)
 if index is None or index[0] is not dependencies:
  index=(dependencies,{resolve_path(d['path']):d for d in dependencies});reader.schedule_reference_index=index
 path=resolve_path(obj['file_name']);ref=index[1].get(path)
 if not ref:raise ValueError('原作息没有登记来源：'+name)
 checked=reader.check(ref);scope=current();key=('hourly_values',ref.get('expected_sha256') or ref['sha256'])
 if scope and key in scope.memo:return list(scope.memo[key])
 values=[float(x.strip()) for x in checked.read_text('utf-8-sig').splitlines() if x.strip()]
 if len(values)!=8760 or any(not math.isfinite(x) for x in values):raise ValueError('原计划不是完整有效的 8760 小时：'+name)
 if scope:scope.memo[key]=tuple(values)
 return values

def extract(model,reader,dependencies):
 rp=next(iter(model['RunPeriod'].values()))
 if rp.get('day_of_week_for_start_day')!='Monday' or [rp['begin_month'],rp['begin_day_of_month']]!=[1,1]:raise ValueError('建筑配置来源需要原全年周一锚定模板。')
 def pair(name):
  v=schedule_values(model,name,reader,dependencies);a,b=v[:24],v[5*24:6*24]
  if any(v[d*24:(d+1)*24]!=(a if d%7<5 else b) for d in range(365)):raise ValueError('原计划含季节或特殊日变化，不能压缩为普通工作日/周末：'+name)
  return dict(weekday=a,weekend=b)
 rooms=[]
 for obj in model['People'].values():
  prefix=obj['number_of_people_schedule_name'].removeprefix('Input_').removesuffix('_people');zone=obj['zone_or_zonelist_or_space_or_spacelist_name']
  if not re.fullmatch(r'R\d+',prefix) or obj['number_of_people']!=1 or obj['number_of_people_calculation_method']!='People':raise ValueError('房间人数接法待适配。')
  for kind in ('lighting','equipment'):
   equipment=[v for v in model['ElectricEquipment'].values() if v['schedule_name']=='Input_'+prefix+'_'+kind]
   if len(equipment)!=1 or equipment[0]['zone_or_zonelist_or_space_or_spacelist_name']!=zone or equipment[0]['design_level_calculation_method']!='EquipmentLevel' or equipment[0]['design_level']!=1:raise ValueError('照明/设备输入并非已核实的每间实际功率接法。')
  conditioned=prefix+'_ideal' in model.get('ZoneHVAC:IdealLoadsAirSystem',{})
  loads={k:pair('Input_'+prefix+'_'+k) for k in CHANNELS}
  hvac=None
  if conditioned:
   hvac={k:schedule_values(model,'Input_'+prefix+'_'+k,reader,dependencies) for k in TEMPERATURES}
   if any(len(set(v))!=1 for v in hvac.values()):raise ValueError('原温控参数含全年变化，不能简化为单一阈值。')
   hvac={k:v[0] for k,v in hvac.items()};hvac['available']=pair('Input_'+prefix+'_available')
  rooms.append(dict(id=prefix,zone=zone,area_m2=model['Zone'][zone]['floor_area'],conditioned=conditioned,loads=loads,hvac=hvac))
 return dict(schema_version=1,building_id='drawing26_global_frozen',calendar_basis='source_Monday_Jan1',rooms=rooms)

def baseline(catalog,reader=None,building_id=None):
 if building_id and building_id!='drawing26_global_frozen':
  from ordinary_building import baseline as ordinary_baseline
  return ordinary_baseline(catalog,building_id,reader)
 from model_adapter import VerifiedReader
 reader=reader or VerifiedReader(catalog);job=next(j for k,j in catalog['global_bundle']['jobs'].items() if k.endswith('|W00'))
 model=reader.json(job['model']);content=extract(model,reader,job['dependencies']);content['baseline_sha256']=digest(content)
 return content,model,job

def number(x):return type(x) in (int,float) and math.isfinite(x)
def validate_hvac(hvac):
 if not isinstance(hvac,dict) or set(hvac)!={*TEMPERATURES,'available'}:raise ValueError('温控需保留四个启停温度与独立可用计划。')
 if any(not number(hvac[k]) or not -50<=hvac[k]<=80 for k in TEMPERATURES) or not hvac['low']<=hvac['heat']<hvac['cool']<=hvac['high']:raise ValueError('温控顺序须为供暖启动 ≤ 供暖停止 < 制冷停止 ≤ 制冷启动。')
 validate_pair(hvac['available'],True)
def validate_pair(value,binary=False):
 if binary:
  from usage_schedules import available
  return available(value)
 if not isinstance(value,dict) or set(value)!={'weekday','weekend'}:raise ValueError('作息需保留工作日和周末。')
 for a in value.values():
  if not isinstance(a,list) or len(a)!=24 or any(not number(x) or x<0 or (binary and x not in (0,1)) for x in a):raise ValueError('每天需 24 个非负数值；空调可用计划仅为 0/1。')
def validate_content(content,base):
 from usage_schedules import validate_load,validate_gains
 if not isinstance(content,dict) or set(content)!=set(base) or type(content['schema_version']) is not int or content['schema_version'] not in (1,2) or any(content[k]!=base[k] for k in ('building_id','calendar_basis','baseline_sha256')):raise ValueError('建筑配置来源不符。')
 if not isinstance(content['rooms'],list) or len(content['rooms'])!=len(base['rooms']):raise ValueError('房间清单不完整。')
 for row,original in zip(content['rooms'],base['rooms']):
  allowed=set(original)|({'gain_settings'} if content['schema_version']==2 else set())
  if not set(original)<=set(row) or set(row)-allowed or any(row[k]!=original[k] for k in ('id','zone','area_m2')):raise ValueError('房间身份、面积或顺序不能由使用配置改变。')
  if type(row['conditioned']) is not bool:raise ValueError('请明确房间空调归属。')
  if row['conditioned']!=original['conditioned']:
   count=sum(r['conditioned'] for r in base['rooms'])
   raise ValueError(f'本轮按约定保持原 {count} 间空调房、{len(base["rooms"])-count} 间非空调房归属。')
  if set(row['loads'])!=set(CHANNELS):raise ValueError('人员、照明、设备计划不完整。')
  for channel,value in row['loads'].items():
   if content['schema_version']==1:validate_pair(value)
   else:validate_load(value,channel,row['area_m2'])
  if 'gain_settings' in row:validate_gains(row['gain_settings'])
  if original['hvac'] is None:
   if row['hvac'] is not None:raise ValueError('原非空调房不添加隐含温控参数。')
  else:validate_hvac(row['hvac'])
 return content

def resolve(record,catalog,base):
 f=record['factors'];b=copy.deepcopy(f['building']);profile=b.pop('usage_profile',None);b.pop('library_constructions',None)
 if record['provenance']['adapter']!='global_frozen_v011' or b!=catalog['records']['global_fixed']['factors']['building']:raise ValueError('本轮建筑配置适配限于已核实的 Drawing26 全球来源。')
 content=copy.deepcopy(verify(profile,'usage')['content'] if profile else base);validate_content(content,base)
 op=f['condition']['operation'];original_op=catalog['records']['global_fixed']['factors']['condition']['operation']
 if set(op)-{'mode','settings','load_basis','overrides'} or op.get('settings') not in (original_op['settings'],'drawing26_usage') or op.get('load_basis')!=original_op['load_basis']:raise ValueError('建筑运行含未适配字段，不能忽略后继续生成。')
 overrides=op.get('overrides',{})
 if not isinstance(overrides,dict) or set(overrides)-{r['id'] for r in content['rooms'] if r['conditioned']}:raise ValueError('工况覆盖只作用于本建筑配置已接入空调的房间。')
 effective=copy.deepcopy(content)
 from usage_schedules import actual_pair
 for room in effective['rooms']:
  room['loads']={channel:actual_pair(value,room['area_m2']) for channel,value in room['loads'].items()}
 for room in effective['rooms']:
  override=overrides.get(room['id'],{})
  if not isinstance(override,dict) or set(override)-{*TEMPERATURES,'available'}:raise ValueError('工况仅覆盖启停温度及空调可用计划。')
  if override:room['hvac'].update(copy.deepcopy(override));validate_hvac(room['hvac'])
 changed=content!=base or bool(overrides)
 references={x['id']:x for x in f['condition'].get('reference_runs',[])}
 if changed and any(c['channel']=='orientation' and c['mode']=='calendar' and references.get(c.get('reference_id'),{}).get('kind')!='workspace_daily_calendar_v1' for c in f['condition']['controls']):raise ValueError('建筑使用或温控已改变，原表面光学切换参考需重新核对；请先使用固定光学参数组，未自动生成新日历。')
 if op['mode'] not in ('controlled','natural','both'):raise ValueError('请选择明确运行模式。')
 shim=copy.deepcopy(record);shim['factors']['building']=b;shim['factors']['condition']['operation']=copy.deepcopy(catalog['records']['global_fixed']['factors']['condition']['operation'])
 return shim,effective

def preview(record,catalog,root=None):
 from ordinary_building import supported_source,preview as ordinary_preview
 if supported_source(record):return ordinary_preview(record,catalog)
 base,model,job=baseline(catalog)
 if record['factors']['building'].get('library_constructions'):
  from construction_library import apply
  apply(model,record)
 walls=[]
 for ident in catalog['records']['global_fixed']['factors']['building']['wall_ids']:
  surface=model['BuildingSurface:Detailed'][ident];construction=model['Construction'][surface['construction_name']]
  layers=[construction['outside_layer']]+[construction[k] for k in sorted(construction,key=lambda k:int(k[6:]) if k.startswith('layer_') else 0) if k.startswith('layer_')]
  details=[]
  for name in layers:
   matches=[k for k in ('Material','Material:NoMass','Material:AirGap') if name in model.get(k,{})]
   details.append(dict(name=name,kind=matches[0] if len(matches)==1 else 'unavailable',values=copy.deepcopy(model[matches[0]][name]) if len(matches)==1 else {}))
  walls.append(dict(id=ident,zone=surface['zone_name'],construction=surface['construction_name'],layers=layers,layer_details=details,feedback_eligible=ident in catalog['records']['global_fixed']['factors']['condition']['controls'][0]['target_ids']))
 profile=record['factors']['building'].get('usage_profile');content=profile['content'] if profile else base
 from usage_schedules import source_snapshot,gain_defaults
 from foundation import ROOT
 sources=source_snapshot(root or ROOT)
 if sources.get('baseline_sha256',base['baseline_sha256'])!=base['baseline_sha256']:raise ValueError('房间说明与当前建筑配置来源不匹配。')
 return dict(base=base,selected=content,walls=walls,source_model=job['model'],eligible=record['provenance']['adapter']=='global_frozen_v011',material_template=catalog['records']['global_fixed']['factors']['materials'],controls_template=catalog['records']['global_fixed']['factors']['condition']['controls'],usage_sources=sources['rooms'],gain_defaults=gain_defaults(model))

def compile_configured(record,site,catalog,reader,operation_mode=None):
 from model_adapter import compile_base_case,changes,VerifiedReader
 reader=reader or VerifiedReader(catalog);base,_,_=baseline(catalog,reader);shim,effective=resolve(record,catalog,base)
 model,report=compile_base_case(shim,site,catalog,reader,'controlled',reference_context=record);before=copy.deepcopy(model)
 source=reader.json(report['source_model'])
 if digest(extract(source,reader,report['dependencies']))!=base['baseline_sha256']:raise ValueError('本地点模板的建筑使用条件与配置来源不同，需先核对。')
 return apply_configuration(model,report,record,effective,reader,operation_mode,source)

def apply_configuration(model,report,record,effective,reader,operation_mode=None,source=None):
 from model_adapter import changes
 before=copy.deepcopy(model)
 source=source if source is not None else reader.json(report['source_model'])
 mode=operation_mode or record['factors']['condition']['operation']['mode']
 if mode not in ('natural','controlled'):raise ValueError('两种模式需分别展开。')
 def put(name,pair):
  if name not in model.get('Schedule:File',{}):raise ValueError('未找到应覆盖的原计划：'+name)
  obj=model['Schedule:File'][name];old=schedule_values(model,name,reader,report['dependencies'])
  values=[v for day in range(365) for v in pair['weekday' if day%7<5 else 'weekend']]
  if values==old:return
  # Compact AllDays with explicit date groups preserves the source Jan-1 Monday calendar even for short periods.
  data=[];start=0
  import datetime as dt
  while start<365:
   is_weekday=start%7<5;end=start
   while end+1<365 and ((end+1)%7<5)==is_weekday:end+=1
   date=dt.date(2025,1,1)+dt.timedelta(days=end)
   data += [dict(field=f'Through: {date.month}/{date.day}'),dict(field='For: AllDays')]
   for hour,value in enumerate(pair['weekday' if is_weekday else 'weekend'],1):data += [dict(field=f'Until: {hour:02d}:00'),dict(field=value)]
   start=end+1
  del model['Schedule:File'][name]
  model.setdefault('Schedule:Compact',{})[name]=dict(schedule_type_limits_name=obj['schedule_type_limits_name'],data=data)
 has_hvac=bool(model.get('ZoneHVAC:IdealLoadsAirSystem'))
 for room in effective['rooms']:
  prefix='Input_'+room['id']+'_'
  for kind in CHANNELS:put(prefix+kind,room['loads'][kind])
  if room['hvac'] and (mode=='controlled' or has_hvac):
   for kind in TEMPERATURES:put(prefix+kind,dict(weekday=[room['hvac'][kind]]*24,weekend=[room['hvac'][kind]]*24))
   available=room['hvac']['available'] if room['conditioned'] and mode=='controlled' else dict(weekday=[0]*24,weekend=[0]*24)
   put(prefix+'available',available)
 from usage_schedules import apply_gains
 gain_parameters=apply_gains(model,effective['rooms'])
 if mode=='natural':
  for kind in list(model):
   if kind.startswith(('ZoneHVAC:','ZoneControl:Thermostat','ThermostatSetpoint:')):del model[kind]
  model['Output:Variable']={k:v for k,v in model.get('Output:Variable',{}).items() if not v['variable_name'].startswith(('Zone Ideal Loads','System Node'))}
 report.update(adapter='drawing26_usage_v2',mode=mode,usage_configuration=effective,usage_version=record['factors']['building'].get('usage_profile'),gain_parameters=gain_parameters,operation_overrides=record['factors']['condition']['operation'].get('overrides',{}),usage_differences=changes(before,model),differences=changes(source,model),generated_model_digest=digest(model),exact_input_match=(source==model))
 return model,report
