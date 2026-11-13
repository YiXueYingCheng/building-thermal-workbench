"""Explicit daily fractions and actual room inputs. No implicit calendar changes."""
import copy,math
from foundation import ROOT,read_json,digest
from component_library import Library,verify,payload_hash

DAYS=('weekday','weekend')
def finite(x):return type(x) in (int,float) and math.isfinite(x)
def daily(values,fraction=False,binary=False):
 if not isinstance(values,list) or len(values)!=24 or any(not finite(v) or v<0 or (fraction and v>1) or (binary and v not in (0,1)) for v in values):raise ValueError('日计划需 24 个有限非负数；比例须为 0–1，空调可用计划须为 0/1。')
 return values
def pair(value,fraction=False,binary=False):
 if not isinstance(value,dict) or set(value)!=set(DAYS):raise ValueError('请保留工作日和周末两份日计划。')
 for values in value.values():daily(values,fraction,binary)
 return value
def available(value):
 if not isinstance(value,dict) or set(value)-{*DAYS,'references'}:raise ValueError('空调可用计划字段不正确。')
 pair({d:value.get(d) for d in DAYS},binary=True)
 refs=value.get('references',{})
 if not isinstance(refs,dict) or set(refs)-set(DAYS):raise ValueError('日计划引用位置无效。')
 for day,snapshot in refs.items():
  content=validate_profile(verify(snapshot,'daily')['content'])
  if content['values']!=value[day]:raise ValueError('空调可用计划已修改，请解除原日计划绑定。')
 return value
def validate_profile(content):
 if not isinstance(content,dict) or set(content)-{'schema_version','unit','values','notes','provenance'} or not {'schema_version','unit','values','notes'}<=set(content) or content['schema_version']!=1 or content['unit']!='fraction':raise ValueError('日计划应明确为 24 小时比例计划。')
 daily(content['values'],fraction=True)
 if not isinstance(content['notes'],str) or len(content['notes'])>1000:raise ValueError('计划说明不超过 1000 字。')
 return content
def validate_load(value,channel,area):
 if not isinstance(value,dict):raise ValueError('房间计划格式无效。')
 if 'kind' not in value:return pair(value)
 required={'kind','unit','minimum','maximum',*DAYS}
 if value.get('kind')!='scaled' or not required<=set(value) or set(value)-required-{'references','basis'}:raise ValueError('比例作息需要上下限、单位和工作日/周末比例。')
 units=('people','people/m2') if channel=='people' else ('W','W/m2')
 if value['unit'] not in units:raise ValueError('人数/功率单位与当前通道不符。')
 lo,hi=value['minimum'],value['maximum']
 if not finite(lo) or not finite(hi) or not 0<=lo<=hi:raise ValueError('上下限须为有限非负数，且下限不能超过上限。')
 for day in DAYS:daily(value[day],fraction=True)
 refs=value.get('references',{})
 if not isinstance(refs,dict) or set(refs)-set(DAYS):raise ValueError('日计划引用位置无效。')
 for day,snapshot in refs.items():
  content=validate_profile(verify(snapshot,'daily')['content'])
  if content['values']!=value[day]:raise ValueError('日计划数值已变，请解除旧计划绑定或显式选择新版本。')
 if 'basis' in value and (not isinstance(value['basis'],str) or len(value['basis'])>300):raise ValueError('作息取值依据不正确。')
 actual=actual_pair(value,area)
 if any(not finite(v) for d in DAYS for v in actual[d]):raise ValueError('换算后的实际人数/功率超出有效数值范围。')
 return value
def actual_pair(value,area):
 if value.get('kind')!='scaled':return copy.deepcopy(value)
 scale=area if value['unit'].endswith('/m2') else 1
 return {day:[scale*(value['minimum']+f*(value['maximum']-value['minimum'])) for f in value[day]] for day in DAYS}
def expanded(value,area=1):
 p=actual_pair(value,area);return [v for d in range(365) for v in p[DAYS[d%7>=5]]]
def gain_defaults(model):
 result={}
 for name,item in model['People'].items():
  room=item['number_of_people_schedule_name'].removeprefix('Input_').removesuffix('_people')
  activity=model['Schedule:Constant'][item['activity_level_schedule_name']]['hourly_value'];fraction=item['sensible_heat_fraction']
  light=next(v for v in model['ElectricEquipment'].values() if v['schedule_name']=='Input_'+room+'_lighting')
  result[room]=dict(sensible_W_person=activity*fraction,lighting_heat_fraction=1-light['fraction_lost'],latent_W_person=activity*(1-fraction))
 return result
def validate_gains(value):
 if not isinstance(value,dict) or set(value)!={'sensible_W_person','lighting_heat_fraction'}:raise ValueError('房间得热参数不完整。')
 if not finite(value['sensible_W_person']) or not 0<=value['sensible_W_person']<=1000 or not finite(value['lighting_heat_fraction']) or not 0<=value['lighting_heat_fraction']<=1:raise ValueError('人员显热须在 0–1000 W/人，照明入室得热比例须在 0–1。')
def apply_gains(model,rooms):
 defaults=gain_defaults(model)
 for room in rooms:
  chosen=room.get('gain_settings')
  if not chosen:continue
  validate_gains(chosen);ident=room['id'];original=defaults[ident]
  if not math.isclose(chosen['sensible_W_person'],original['sensible_W_person'],abs_tol=1e-12,rel_tol=1e-13):
   item=next(v for v in model['People'].values() if v['number_of_people_schedule_name']=='Input_'+ident+'_people')
   schedule=item['activity_level_schedule_name'];activity=copy.deepcopy(model['Schedule:Constant'][schedule]);total=chosen['sensible_W_person']+original['latent_W_person'];activity['hourly_value']=total
   # A private schedule ensures changes cannot affect another room sharing a source object.
   name='NX_Usage_'+ident+'_activity';model['Schedule:Constant'][name]=activity;item['activity_level_schedule_name']=name;item['sensible_heat_fraction']=chosen['sensible_W_person']/total if total else 0
  if not math.isclose(chosen['lighting_heat_fraction'],original['lighting_heat_fraction'],abs_tol=1e-12,rel_tol=1e-13):
   item=next(v for v in model['ElectricEquipment'].values() if v['schedule_name']=='Input_'+ident+'_lighting');before=1-item['fraction_lost'];ratio=item['fraction_radiant']/before if before else 0
   item['fraction_lost']=1-chosen['lighting_heat_fraction'];item['fraction_radiant']=ratio*chosen['lighting_heat_fraction']
 return gain_defaults(model)
def source_snapshot(root=ROOT):
 path=root/'data/usage-source-details.json'
 if not path.exists():return dict(rooms={},daily=[],sources=[],notes=['尚未补充原配置说明。'])
 data=read_json(path)
 if digest(data['content'])!=data['sha256']:raise ValueError('作息来源快照已改变，请核查。')
 return data['content']
def profiles(root=ROOT):
 source=source_snapshot(root)
 return source['daily']+[dict(snapshot=r,origin='本工作区日计划',aliases=[],binary=all(v in (0,1) for v in r['content']['values'])) for r in Library(root).all('daily')]
def save_profile(root,name,content,parent=None):
 if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('请填写 1–100 字的日计划名称。')
 validate_profile(content)
 if not parent:
  same=next((r for r in profiles(root) if r['snapshot']['content']['values']==content['values']),None)
  if same:return dict(profile=same['snapshot'],reused=True)
 row=Library(root).save('daily',name,content,parent)
 return dict(profile=row,reused=False)
