"""Verified ordinary building sources. No legacy executors or dynamic defaults."""
import copy,csv,datetime as dt,math
from pathlib import Path
from foundation import digest,read_json
from contracts import normalize,validate

ADAPTER='ordinary_building_v1'

def supported_source(record):return record.get('provenance',{}).get('adapter')==ADAPTER

def source(catalog,building_id):
 value=catalog.get('ordinary_buildings',{}).get(building_id)
 if not value:raise ValueError('该普通建筑尚未登记已核实的项目包。')
 return value

def model(source,reader,mode='controlled'):
 ref=source['models'][mode];result=reader.json(ref)
 for item in result.get('Schedule:File',{}).values():
  p=Path(item['file_name'])
  if not p.is_absolute():item['file_name']=str((Path(ref['path']).parent/p).resolve())
 return result

def baseline(catalog,building_id,reader=None):
 from model_adapter import VerifiedReader
 s=source(catalog,building_id);reader=reader or VerifiedReader(catalog)
 m=model(s,reader)
 return copy.deepcopy(s['usage']),m,dict(model=s['models']['controlled'],dependencies=s['dependencies'],weather=s['weather'])

def resolve(record,catalog,base):
 from building_configuration import validate_content,validate_hvac,TEMPERATURES
 from component_library import verify
 from usage_schedules import actual_pair
 s=source(catalog,base['building_id']);f=record['factors'];b=copy.deepcopy(f['building'])
 profile=b.pop('usage_profile',None);b.pop('envelope_overrides',None)
 if b!=s['building']:raise ValueError('建筑几何、身份或来源已改变；请重新登记来源。')
 content=copy.deepcopy(verify(profile,'usage')['content'] if profile else base);validate_content(content,base)
 op=f['condition']['operation']
 if set(op)-{'mode','settings','load_basis','overrides'} or op.get('settings')!='ordinary_usage' or op.get('load_basis')!='sensible_demand':raise ValueError('普通建筑运行字段尚未适配。')
 if op.get('mode') not in ('controlled','natural','both'):raise ValueError('请选择自然室温、温控或两种模式。')
 overrides=op.get('overrides',{})
 if not isinstance(overrides,dict) or set(overrides)-{r['id'] for r in base['rooms'] if r['conditioned']}:raise ValueError('运行覆盖只作用于本建筑原空调房。')
 for room in content['rooms']:
  room['loads']={k:actual_pair(v,room['area_m2']) for k,v in room['loads'].items()}
  override=overrides.get(room['id'],{})
  if not isinstance(override,dict) or set(override)-{*TEMPERATURES,'available'}:raise ValueError('运行覆盖仅支持四个启停温度与可用时段。')
  if override:room['hvac'].update(copy.deepcopy(override));validate_hvac(room['hvac'])
 return record,content

def capability(record,catalog):
 try:
  r=normalize(record);errors=validate(r,catalog['sites'])
  if errors:return dict(supported=False,reasons=errors)
  f=r['factors'];s=source(catalog,f['building']['id'])
  if set(f['condition'])!={'operation','controls','reference_runs'}:raise ValueError('工况包含未适配字段，不能忽略。')
  if not supported_source(r) or r['provenance']['snapshot_id']!=s['snapshot_id']:raise ValueError('建筑来源版本不匹配。')
  from ordinary_materials import validate as validate_materials
  material=validate_materials(r,s)
  if f['condition']['reference_runs']:
   from ordinary_orientation import validate_binding
   validate_binding(r,catalog)
  if r['numerics']!=s['numerics']:raise ValueError('此建筑首轮沿用已验证的 5 min 步长与原计算引擎。')
  if set(f['scope'])-{'site_ids','period','aggregation'}:raise ValueError('范围包含未支持字段。')
  if any(i!=s['site']['id'] and (catalog['sites'][i].get('source_kind') not in ('reviewed_global','imported_epw_v1') or not catalog['sites'][i].get('eligible')) for i in f['scope']['site_ids']):raise ValueError('所选地点没有可用的登记气象。')
  resolve(r,catalog,s['usage'])
  if f['building'].get('envelope_overrides'):
   from ordinary_envelope import validate_overrides
   validate_overrides(f['building']['envelope_overrides'],s['envelope'])
  return dict(supported=True,reasons=[],case='ORDINARY_ECA_'+material['state']+'_A' if material else 'ORDINARY')
 except (KeyError,ValueError,TypeError,AttributeError) as exc:return dict(supported=False,reasons=[str(exc)])

def preview(record,catalog):
 from model_adapter import VerifiedReader
 from usage_schedules import gain_defaults
 s=source(catalog,record['factors']['building']['id']);base,m,job=baseline(catalog,s['building']['id'])
 return dict(base=base,selected=record['factors']['building'].get('usage_profile',{}).get('content',base),walls=[],
  source_model=job['model'],eligible=True,material_template=None,controls_template=[],usage_sources=s['usage_sources'],
  gain_defaults=gain_defaults(m),envelope=s['envelope'],source_notes=s['notes'])

def compile_case(record,site_id,catalog,reader,operation_mode=None):
 from model_adapter import NotSupported,changes
 from building_configuration import apply_configuration
 from ordinary_envelope import apply_overrides
 cap=capability(record,catalog)
 if not cap['supported']:raise NotSupported('；'.join(cap['reasons']))
 if record['factors']['condition']['reference_runs']:
  from ordinary_orientation import compile_bound
  return compile_bound(record,site_id,catalog,reader,operation_mode)
 s=source(catalog,record['factors']['building']['id'])
 if site_id not in record['factors']['scope']['site_ids']:raise ValueError('地点不在当前方案范围。')
 mode=operation_mode or record['factors']['condition']['operation']['mode']
 if mode not in ('controlled','natural'):raise ValueError('两种模式需分别生成。')
 for ref in s['source_refs']:reader.check(ref)
 for ref in s['dependencies']:reader.check(ref)
 original=model(s,reader,mode);m=copy.deepcopy(original);site=catalog['sites'][site_id];weather=reader.check(site['weather'])
 expected={str(Path(d['path']).resolve()) for d in s['dependencies']}
 if any(str(Path(v['file_name']).resolve()) not in expected for v in m.get('Schedule:File',{}).values()):raise ValueError('存在未登记的作息文件。')
 with weather.open(encoding='utf-8-sig') as stream:header=next(csv.reader(stream))
 loc=next(iter(m['Site:Location'].values()))
 location=dict(zip(('latitude','longitude','time_zone','elevation'),map(float,header[6:10])));adaptation=None
 if header[0]!='LOCATION' or len(location)!=4 or not all(math.isfinite(v) for v in location.values()):raise ValueError('气象位置表头无效。')
 if site_id!=s['site']['id']:
  from weather_import import apply_location
  adaptation=apply_location(m,site,location)
 elif any(not math.isclose(location[k],loc[k],abs_tol=1e-10) for k in location):raise ValueError('建筑地点与原气象位置不匹配。')
 period=record['factors']['scope']['period'];rp=next(iter(m['RunPeriod'].values()))
 for k,v in zip(('begin_month','begin_day_of_month','end_month','end_day_of_month'),period):rp[k]=v
 days=(dt.date(2025,*period[:2])-dt.date(2025,1,1)).days
 rp['day_of_week_for_start_day']=('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')[days%7]
 effective=resolve(record,catalog,s['usage'])[1]
 report=dict(adapter=ADAPTER,site_id=site_id,city=site['name'],mode=mode,period=period,step_minutes=5,
  source_model=s['models'][mode],weather=site['weather'],dependencies=s['dependencies'],source_notes=s['notes'])
 report['time_basis']=dict(statistics_period=copy.deepcopy(period),statistics_days=(dt.date(2025,*period[2:])-dt.date(2025,*period[:2])).days+1,
  weather_prehistory_days=0,warmup_strategy='source_model',warmup_parameters={k:v for k,v in next(iter(original['Building'].values())).items() if 'warmup' in k or 'convergence' in k},
  start_day_of_week=rp['day_of_week_for_start_day'],statistics_basis='实际天气运行时段；不含求解器预热',continuous_weather_prehistory=False)
 if adaptation:report['weather_adaptation']=adaptation
 m,report=apply_configuration(m,report,record,effective,reader,mode,source=original)
 applied=apply_overrides(m,record['factors']['building'].get('envelope_overrides',{}),s['envelope'])
 from ordinary_materials import apply as apply_material
 material=apply_material(m,record,s)
 if material:report['material_application']=material
 report.update(adapter=ADAPTER,envelope_changes=applied,differences=changes(original,m),generated_model_digest=digest(m),exact_input_match=m==original)
 return m,report
