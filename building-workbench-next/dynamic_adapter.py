"""Independent state identity and site-bound calendars over the same fixed material adapter."""
import copy
import csv
import datetime as dt
import math
from pathlib import Path
from contracts import normalize,validate
from foundation import digest
from model_adapter import VerifiedReader,NotSupported,compile_fixed_case,changes,fixed_capability

POLICY_KEYS=('cold_C','hot_C','flux_deadband_W_m2','minimum_hold_minutes')
def origin(record):return record['provenance'].get('origin_id',record['id'])

def resolve(record,catalog,site_id=None,reference_context=None):
 r=normalize(record);errors=validate(r,catalog['sites'])
 if errors:raise NotSupported('；'.join(errors))
 registry=catalog.get('dynamic_registry',{});binding=registry.get('records',{}).get(origin(r));f=r['factors']
 original_record=catalog['records'].get(origin(r))
 if not original_record or {k:v for k,v in r['numerics'].items() if k!='step_minutes'}!={k:v for k,v in original_record['numerics'].items() if k!='step_minutes'}:raise NotSupported('来源引擎或数值设置已变化，需重新适配。')
 if r['provenance']['adapter']=='legacy_plan_v011':
  if not binding or f['building']!=binding['building']:raise NotSupported('该旧方案的建筑尚未登记到动态模板。')
  if f['scope']['site_ids']!=[binding['site_id']]:raise NotSupported('地点改变后需重新绑定该地点的气象和参考日历。')
  original=catalog['records'][origin(r)]
  operation=copy.deepcopy(f['condition']['operation']);operation['mode']=original['factors']['condition']['operation']['mode']
  if operation!=original['factors']['condition']['operation']:raise NotSupported('建筑运行参数覆盖尚未接入。')
 elif r['provenance']['adapter']=='global_frozen_v011':
  if any(not catalog['sites'][s].get('eligible') or catalog['sites'][s].get('source_kind') not in ('reviewed_global','imported_epw_v1') for s in f['scope']['site_ids']):raise NotSupported('地点没有可用的气象输入。')
  if f['building']!=catalog['records']['global_fixed']['factors']['building']:raise NotSupported('建筑改变后需要新的动态模板。')
  if f['condition']['operation']!=catalog['records']['global_fixed']['factors']['condition']['operation']:raise NotSupported('全球模板当前支持原温控运行。')
 else:raise NotSupported('来源没有相应动态模板。')
 m=f['materials']
 if len(m['definitions'])!=1 or len(m['applications'])!=1:raise NotSupported('当前动态适配支持一个 ECA 等效层应用。')
 d=m['definitions'][0];app=m['applications'][0];wallmap={w['surface']:w for w in registry.get('walls',[])}
 states={s['id']:s for s in d['states']}
 if set(states)!={'R','C'} or d['model']!='equivalent_resistance_no_layer_storage' or d['kind']!='single_layer':raise NotSupported('当前支持 R/C 独立状态的单层等效热阻材料。')
 if app['position']!='exterior' or app['component']!='wall' or set(app['target_ids'])!=set(wallmap):raise NotSupported('当前动态适配保留原 14 段外墙外侧应用。')
 if any(s.get('resistance_m2K_W') is None for s in states.values()):raise NotSupported('材料两态热阻尚未补全。')
 if app['orientation']!={'A':'cooling_face','B':'other_face'} or app.get('placement_basis')!='legacy_outer_equivalent_model':raise NotSupported('材料方向或应用模型尚未适配。')
 thermal={};orientation={};groups=[]
 for i,c in enumerate(f['condition']['controls']):
  dest=thermal if c['channel']=='thermal' else orientation
  for wall in c['target_ids']:
   if wall in dest:raise NotSupported('同一构件存在重复控制。')
   dest[wall]=c
  if c['channel']=='thermal' and c['mode']=='feedback':
   if c.get('rule') not in ('UNIFIED','GROUPED'):raise NotSupported('反馈预设尚未支持。')
   if any(not wallmap[w]['eligible'] for w in c['target_ids']):raise NotSupported('本阶段反馈作用范围限于原 7 段参与墙。')
   policy=c.get('policy')
   if not isinstance(policy,dict) or any(type(policy.get(k)) not in (int,float) or not math.isfinite(policy[k]) for k in POLICY_KEYS):raise NotSupported('请明确反馈阈值及最短保持时间。')
   if policy['cold_C']>=policy['hot_C'] or policy['flux_deadband_W_m2']<0 or policy['minimum_hold_minutes']<0:raise NotSupported('反馈阈值或保持时间无效。')
   step=r['numerics']['step_minutes'];update=c.get('update',{})
   interval=step if update.get('kind')=='solver_step' else update.get('minutes') if update.get('kind')=='minutes' else None
   if type(interval) not in (int,float) or interval<=0 or interval%step:raise NotSupported('控制更新间隔须为求解步长的正整数倍。')
   roles=c.get('state_roles')
   if roles is None and binding:
    oldstates=catalog['records'][origin(r)]['factors']['materials']['definitions'][0]['states']
    roles=dict(positive=max(oldstates,key=lambda s:s['resistance_m2K_W'])['id'],negative=min(oldstates,key=lambda s:s['resistance_m2K_W'])['id'])
   if not isinstance(roles,dict) or set(roles.values())!={'R','C'}:raise NotSupported('请明确正、负反馈分别选择的材料状态。')
   keys=['ALL'] if c['rule']=='UNIFIED' else sorted({wallmap[w]['group'] for w in c['target_ids']})
   for key in keys:
    targets=[w for w in c['target_ids'] if key=='ALL' or wallmap[w]['group']==key]
    groups.append(dict(id=f'NX_G{i}_{key}',targets=targets,area=sum(wallmap[w]['area_m2'] for w in targets),policy={k:policy[k] for k in POLICY_KEYS},interval=interval,roles=roles))
 if set(thermal)!=set(wallmap) or set(orientation)!=set(wallmap):raise NotSupported('所有应用墙面需要唯一的状态和朝向指定。')
 calendars={};workspace_calendars={}
 for w,c in orientation.items():
  if c['mode']=='calendar':
   ref=next((ref for ref in f['condition']['reference_runs'] if ref['id']==c.get('reference_id')),None)
   if ref and ref.get('kind')=='workspace_daily_calendar_v1':
    from calendar_library import bound
    if ref['id'] not in workspace_calendars:workspace_calendars[ref['id']]=bound(reference_context or r,catalog,ref)
    calendar=workspace_calendars[ref['id']][site_id or f['scope']['site_ids'][0]]['calendar']
   else:
    if not ref or not binding or ref!=binding['reference']:raise NotSupported('日历必须与已登记地点、气象和参考计算一致，不能跨地点套用。')
    calendar=ref['calendar']
    if len(calendar)!=365 or digest(calendar)!=ref['calendar_sha256']:raise NotSupported('逐日日历内容与校验不一致。')
   calendars[w]=calendar
  elif c['mode']!='fixed':raise NotSupported('朝向模式未支持。')
  needed_states=['R','C'] if thermal[w]['mode']=='feedback' else [thermal[w]['state_id']]
  faces=['A','B'] if w in calendars else [c['face_id']]
  for state in needed_states:
   for face in faces:
    optical=d['optics'].get(face+'_'+state,{})
    if any(optical.get(k) is None for k in ('solar_absorptance','emissivity')):raise NotSupported('反馈/翻面使用的 '+face+' 面 '+state+' 态光学参数未补全。')
 return dict(record=r,binding=binding,walls=wallmap,thermal=thermal,orientation=orientation,groups=groups,calendars=calendars)

def capability(record,catalog,reference_context=None):
 try:
  cfg=resolve(record,catalog,reference_context=reference_context)
  return dict(supported=True,reasons=[],case='DYNAMIC' if cfg['groups'] else 'FIXED_WITH_CALENDAR',feedback_groups=len(cfg['groups']),calendar_walls=len(cfg['calendars']))
 except (ValueError,KeyError,TypeError,AttributeError) as e:return dict(supported=False,reasons=[str(e)])

def program(lines):return dict(lines=[dict(program_line=s) for s in lines])
def num(v):return format(v,'.15g')
def state_num(s):return 0 if s=='R' else 1

def compile_dynamic(record,site,catalog,reader=None,operation_mode=None,reference_context=None):
 cfg=resolve(record,catalog,site,reference_context);r=cfg['record'];reader=reader or VerifiedReader(catalog);binding=cfg['binding']
 for ref in catalog.get('dynamic_registry',{}).get('source_refs',[]):reader.check(ref)
 from calendar_library import verify_for_site
 verify_for_site(reference_context or r,catalog,site,reader)
 if site not in r['factors']['scope']['site_ids']:raise ValueError('地点不在方案范围。')
 mode=operation_mode or r['factors']['condition']['operation']['mode']
 if mode=='both':raise NotSupported('两种运行模式需分别生成输入。')
 if binding:
  for ref in binding['sources']:reader.check(ref)
  for ref in catalog['records'][origin(r)]['provenance']['source_refs']:reader.check(ref)
  info=binding['modes'][mode];job=dict(id='legacy_'+site,model=info['model'],weather=binding['weather'],dependencies=info['dependencies'])
 else:
  from weather_import import job as weather_job
  job=weather_job(catalog,site,'FIXED_COOL_LOW7')
 raw=reader.json(job['model']);weather=reader.check(job['weather'])
 with weather.open(encoding='utf-8-sig') as stream:header=next(csv.reader(stream))
 location=dict(zip(('latitude','longitude','time_zone','elevation'),map(float,header[6:10])))
 prepared=copy.deepcopy(raw)
 if binding:
  prepared['Site:Location']={catalog['sites'][site]['name']:location}
  for obj in prepared.get('Schedule:File',{}).values():obj['file_name']=str((Path(job['model']['path']).parent/obj['file_name']).resolve())
 class PreparedReader:
  def check(self,ref):return reader.check(ref)
  def json(self,ref):reader.check(ref);return copy.deepcopy(prepared)
 # Both fixed and feedback paths share the same material parameter compiler.
 shim=copy.deepcopy(r);shim['provenance']['adapter']='global_frozen_v011';shim['factors']['building']=copy.deepcopy(catalog['records']['global_fixed']['factors']['building'])
 shim['factors']['condition']['operation']=copy.deepcopy(catalog['records']['global_fixed']['factors']['condition']['operation']);shim['factors']['condition']['reference_runs']=[]
 shim['numerics']={**catalog['records']['global_fixed']['numerics'],'step_minutes':r['numerics']['step_minutes']}
 startday=(dt.date(2025,*r['factors']['scope']['period'][:2])-dt.date(2025,1,1)).days
 for c in shim['factors']['condition']['controls']:
  c['mode']='fixed'
  if c['channel']=='orientation':c['face_id']='A' if not cfg['calendars'] or next(iter(cfg['calendars'].values()))[startday] else 'B'
 # Preserve individually selected fixed faces.
 for c,old in zip(shim['factors']['condition']['controls'],r['factors']['condition']['controls']):
  if old['channel']=='orientation' and old['mode']=='fixed':c['face_id']=old['face_id']
 local=dict(catalog);local['sites']=dict(catalog['sites']);local['sites'][site]={**catalog['sites'][site],'source_kind':'reviewed_global'}
 local['global_bundle']={**catalog['global_bundle'],'jobs':{**catalog['global_bundle']['jobs'],site+'|FIXED_COOL_LOW7':job}}
 model,base=compile_fixed_case(shim,site,local,PreparedReader());before=copy.deepcopy(model)
 init=model['EnergyManagementSystem:Program']['ECA_Initialize']['lines'];update=['IF WarmupFlag == 0','SET ECA_Step = ECA_Step + 1','ELSE','SET ECA_Step = 0','ENDIF','SET ECA_Vote = 0']+[f'SET JR_Vote_{g} = 0' for g in ('N','E','S','W')];optics=[];variables=[]
 def addvar(name):variables.append(dict(erl_variable_name=name))
 for w in cfg['walls']:
  variable=f'NX_{w}_State';addvar(variable);init.append(dict(program_line=f'SET {variable} = {state_num(cfg["thermal"][w]["state_id"])}'))
 for g in cfg['groups']:
  addvar(g['id']+'_Clock');addvar(g['id']+'_Vote');init.append(dict(program_line=f'SET {g["id"]}_Clock = 0'))
 for w in cfg['walls']:
  p='ECA_'+w;update += [f'SET {p}_UsedT = {p}_LastT',f'SET {p}_UsedQ = {p}_LastQ',f'SET {p}_Age = {p}_Age + {r["numerics"]["step_minutes"]}',f'SET {p}_Changed = 0',f'SET {p}_Phase = 0',f'SET {p}_Vote = 0',f'SET {p}_Want = {p}_R']
  if cfg['thermal'][w]['mode']=='feedback':update.append(f'SET NX_{w}_Want = NX_{w}_State')
 update+=['IF WarmupFlag == 0 && ECA_Ready == 1']
 for g in cfg['groups']:
  clock=g['id']+'_Clock';vote=g['id']+'_Vote';pol=g['policy'];update += [f'SET {clock} = {clock} + {r["numerics"]["step_minutes"]}',f'IF {clock} >= {num(g["interval"])}',f'SET {clock} = 0',f'SET {vote} = 0']
  for w in g['targets']:
   p='ECA_'+w;update += [f'SET {p}_Phase = 0',f'SET {p}_Vote = 0',f'IF {p}_UsedT < {num(pol["cold_C"])}',f'SET {p}_Phase = -1',f'ELSEIF {p}_UsedT > {num(pol["hot_C"])}',f'SET {p}_Phase = 1','ENDIF',f'IF {p}_UsedQ > {num(pol["flux_deadband_W_m2"])} || {p}_UsedQ < (0 - {num(pol["flux_deadband_W_m2"])})',f'SET {p}_Vote = {p}_Phase * {p}_UsedQ','ENDIF',f'SET {vote} = {vote} + ({p}_Vote * {num(cfg["walls"][w]["area_m2"])})']
  for w in g['targets']:
   p='ECA_'+w;s=f'NX_{w}_State';want=f'NX_{w}_Want';addvar(want)
   update += [f'SET {want} = {s}',f'IF {vote} > {num(g["area"]*pol["flux_deadband_W_m2"])}',f'SET {want} = {state_num(g["roles"]["positive"])}',f'ELSEIF {vote} < (0 - {num(g["area"]*pol["flux_deadband_W_m2"])})',f'SET {want} = {state_num(g["roles"]["negative"])}','ENDIF',f'IF {want} <> {s} && {p}_Age >= {num(pol["minimum_hold_minutes"])}',f'SET {s} = {want}',f'SET {p}_Age = 0',f'SET {p}_Changed = 1','ENDIF']
  update+=['ENDIF']
 update+=['ENDIF']
 material=r['factors']['materials']['definitions'][0];states={s['id']:s for s in material['states']};refR=max(s['resistance_m2K_W'] for s in states.values())
 for w in cfg['walls']:
  p='ECA_'+w;s=f'NX_{w}_State';update += [f'IF {s} == 0',f'SET {p}_R = {num(states["R"]["resistance_m2K_W"]/refR)}','ELSE',f'SET {p}_R = {num(states["C"]["resistance_m2K_W"]/refR)}','ENDIF',f'SET {p}_Act = {p}_R']
  if cfg['thermal'][w]['mode']=='feedback':
   update += [f'IF NX_{w}_Want == 0',f'SET {p}_Want = {num(states["R"]["resistance_m2K_W"]/refR)}','ELSE',f'SET {p}_Want = {num(states["C"]["resistance_m2K_W"]/refR)}','ENDIF',f'SET ECA_Vote = ECA_Vote + ({p}_Vote * {num(cfg["walls"][w]["area_m2"])})',f'SET JR_Vote_{cfg["walls"][w]["group"]} = JR_Vote_{cfg["walls"][w]["group"]} + ({p}_Vote * {num(cfg["walls"][w]["area_m2"])})']
  face=f'NX_{w}_Face';addvar(face)
  if w in cfg['calendars']:
   cal=cfg['calendars'][w];switches=[i for i in range(1,365) if cal[i]!=cal[i-1]]
   optics += [f'SET {face} = {int(bool(cal[0]))}']
   for i in switches:optics += [f'IF DayOfYear >= {i+1}',f'SET {face} = {int(bool(cal[i]))}','ENDIF']
  else:optics += [f'SET {face} = {1 if cfg["orientation"][w]["face_id"]=="A" else 0}']
  used_states=['R','C'] if cfg['thermal'][w]['mode']=='feedback' else [cfg['thermal'][w]['state_id']]
  used_faces=['A','B'] if w in cfg['calendars'] else [cfg['orientation'][w]['face_id']]
  for state in used_states:
   for f in used_faces:
    opt=material['optics'][f+'_'+state]
    optics += [f'IF {s} == {state_num(state)} && {face} == {1 if f=="A" else 0}',f'SET JR_{w}_A = {num(opt["solar_absorptance"])}',f'SET JR_{w}_E = {num(opt["emissivity"])}',f'SET JR_{w}_B = {num(opt["solar_absorptance"])}','ENDIF']
 model['EnergyManagementSystem:GlobalVariable']['NX_States']=dict(variables=variables)
 for w in cfg['walls']:
  for tag in ('State','Face'):
   name=f'NX {w} {tag}'
   model.setdefault('EnergyManagementSystem:OutputVariable',{})[name]=dict(ems_variable_name=f'NX_{w}_{tag}',type_of_data_in_variable='Averaged',update_frequency='ZoneTimestep')
   for frequency in ('Monthly','RunPeriod'):
    model['Output:Variable'][f'NX_{w}_{tag}_{frequency}']=dict(key_value='*',variable_name=name,reporting_frequency=frequency)
 model['EnergyManagementSystem:Program']['ECA_Update']=program(update);model['EnergyManagementSystem:Program']['JR_Optics']=program(optics)
 model['EnergyManagementSystem:ProgramCallingManager']['ECA_Control']['programs']=[dict(program_name='ECA_Update'),dict(program_name='JR_Optics')]
 # Keep the original capture at the end of a complete zone timestep.
 managers=model['EnergyManagementSystem:ProgramCallingManager']
 if not any(m['energyplus_model_calling_point']=='EndOfZoneTimestepAfterZoneReporting' and {'program_name':'ECA_Capture'} in m['programs'] for m in managers.values()):raise ValueError('缺少完整步结束后的历史量采集。')
 if not any(m['energyplus_model_calling_point']=='AfterNewEnvironmentWarmUpIsComplete' and {'program_name':'ECA_Initialize'} in m['programs'] for m in managers.values()):raise ValueError('缺少预热结束后的控制复位。')
 for row in changes(before,model):
  p=row['path'];allowed=(p[:2] in [['EnergyManagementSystem:Program',x] for x in ('ECA_Initialize','ECA_Update','JR_Optics')] or p[:2]==['EnergyManagementSystem:GlobalVariable','NX_States'] or p[:3]==['EnergyManagementSystem:ProgramCallingManager','ECA_Control','programs'])
  allowed |= p[0] in ('EnergyManagementSystem:OutputVariable','Output:Variable') and str(p[1]).startswith('NX')
  if not allowed:raise ValueError('动态适配修改了控制范围以外的内容。')
 report={**base,'adapter':'drawing26_state_v1','mode':mode,'source_model_digest':digest(raw),'generated_model_digest':digest(model),'exact_input_match':False,'differences':changes(raw,model),
  'control_groups':cfg['groups'],'wall_assignments_basis':'initial_state_only_see_control_groups_for_transitions','calendar_binding':dict(site_id=site,weather_sha256=job['weather']['sha256'],calendar_sha256=digest(next(iter(cfg['calendars'].values()))) if cfg['calendars'] else None),
  'state_identity':dict(R=0,C=1),'control_order':['previous_complete_step','update_state','apply_current_state_optics'],'new_simulations':0}
 from calendar_library import active_references
 if active_references(r):report['calendar_versions']=[{k:x['snapshot'][k] for k in ('id','revision','name','sha256')} for x in active_references(r)]
 return model,report
