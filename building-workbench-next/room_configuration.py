"""Validated, side-effect-free room reuse and effective-value comparisons.

Returns ordinary usage configuration data consumed by the existing compiler.
No room geometry, HVAC membership, source libraries or saved schemes are changed.
"""
import copy,math
from foundation import digest
from building_configuration import baseline,validate_content,CHANNELS,TEMPERATURES,validate_hvac
from usage_schedules import actual_pair,gain_defaults

GROUPS={'people':'人员','lighting':'照明','equipment':'设备','sensible':'人员显热',
        'lighting_heat':'照明入室得热比例','available':'空调可用时段','temperatures':'四个启停温度'}
GAIN_KEYS={'sensible':'sensible_W_person','lighting_heat':'lighting_heat_fraction'}
DAYS=('weekday','weekend')

def close(a,b):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
def gain_values(room,defaults):
 return {k:room.get('gain_settings',{}).get(k,defaults[room['id']][k]) for k in GAIN_KEYS.values()}
def group_value(room,group,defaults):
 if group in CHANNELS:return room['loads'][group]
 if group in GAIN_KEYS:return gain_values(room,defaults)[GAIN_KEYS[group]]
 if not room['hvac']:return None
 if group=='available':return room['hvac']['available']
 return {key:room['hvac'][key] for key in TEMPERATURES}
def actual(value,group,area):
 if group in CHANNELS:return actual_pair(value,area)
 if group=='available':return {day:value[day] for day in DAYS}
 return value

def differences(before,after,base,defaults):
 validate_content(before,base);validate_content(after,base);rows=[];changed=0;actual_changes=0
 for old,new in zip(before['rooms'],after['rooms']):
  items=[]
  for group,label in GROUPS.items():
   a=group_value(old,group,defaults);b=group_value(new,group,defaults)
   if a==b:continue
   item=dict(group=group,label=label,before=copy.deepcopy(a),after=copy.deepcopy(b))
   if group in (*CHANNELS,'available'):
    p=actual(a,group,old['area_m2']);q=actual(b,group,new['area_m2'])
    hours=[dict(day=day,hour=h,before=p[day][h],after=q[day][h]) for day in DAYS for h in range(24) if not close(p[day][h],q[day][h])]
    annual=lambda pair:261*sum(pair['weekday'])+104*sum(pair['weekend'])
    divisor=1000 if group in ('lighting','equipment') else 1
    item.update(actual_before=p,actual_after=q,hours=hours,actual_changed=bool(hours),
     annual_before=annual(p)/divisor,annual_after=annual(q)/divisor,
     annual_unit='人·时' if group=='people' else '可用小时' if group=='available' else 'kWh 输入电量')
   elif group=='temperatures':item['actual_changed']=any(not close(a[k],b[k]) for k in TEMPERATURES)
   else:item['actual_changed']=not close(a,b)
   items.append(item);changed+=1;actual_changes+=int(item['actual_changed'])
  if items:rows.append(dict(id=new['id'],zone=new['zone'],area_m2=new['area_m2'],conditioned=new['conditioned'],changes=items))
 return dict(rooms=rows,room_count=len(rows),changed_groups=changed,actual_changed_groups=actual_changes,
             expression_only_groups=changed-actual_changes,before_sha256=digest(before),after_sha256=digest(after))

def context_notes(changes,content,overrides,mode):
 if not isinstance(overrides,dict):raise ValueError('运行覆盖格式不正确。')
 rooms={r['id']:r for r in content['rooms']}
 for ident,override in overrides.items():
  if ident not in rooms or not rooms[ident]['hvac'] or not isinstance(override,dict) or set(override)-{*TEMPERATURES,'available'}:raise ValueError('运行覆盖超出原空调房或字段范围。')
  validate_hvac({**rooms[ident]['hvac'],**override})
 if mode not in ('controlled','natural','both'):raise ValueError('运行模式不正确。')
 notes=[]
 for row in changes['rooms']:
  groups={c['group'] for c in row['changes']}
  masked=[];override=overrides.get(row['id'],{})
  if 'available' in groups and 'available' in override:masked.append('空调可用时段')
  if 'temperatures' in groups and any(k in override for k in TEMPERATURES):masked.append('部分或全部启停温度')
  if masked:notes.append(row['zone']+' 的'+'、'.join(masked)+'仍使用本方案工况覆盖；本次只修改建筑默认配置。')
  if groups&{'available','temperatures'} and mode in ('natural','both'):
   notes.append(row['zone']+' 的空调默认值不作用于自然室温算例；自然模式仍不启用空调。')
 return notes

def reuse(content,source,source_id,targets,groups,basis,base,defaults,overrides=None,mode='controlled'):
 validate_content(content,base);validate_content(source,base)
 if not isinstance(targets,list) or not targets or any(not isinstance(x,str) for x in targets) or len(set(targets))!=len(targets):raise ValueError('请明确选择一个或多个不同的目标房间。')
 if not isinstance(groups,list) or not groups or any(not isinstance(x,str) for x in groups) or len(set(groups))!=len(groups) or set(groups)-set(GROUPS):raise ValueError('请选择有效且不重复的复用内容。')
 if basis not in ('source_units','room_totals'):raise ValueError('请明确保留原单位或每间实际值。')
 origin=next((r for r in source['rooms'] if r['id']==source_id),None)
 if not origin:raise ValueError('来源房间不存在。')
 current={r['id']:r for r in content['rooms']}
 if set(targets)-set(current):raise ValueError('目标房间不属于当前建筑。')
 if {'available','temperatures'}&set(groups):
  if not origin['hvac']:raise ValueError('来源是非空调房，不能复用空调参数。')
  incompatible=[current[i]['zone'] for i in targets if not current[i]['hvac']]
  if incompatible:raise ValueError('以下目标是非空调房，未应用任何修改：'+'、'.join(incompatible)+'。请取消空调内容或调整目标。')
 result=copy.deepcopy(content)
 for room in result['rooms']:
  if room['id'] not in targets:continue
  for group in groups:
   if group in CHANNELS:
    rule=copy.deepcopy(origin['loads'][group])
    if basis=='room_totals' and rule.get('kind')=='scaled' and rule['unit'].endswith('/m2'):
     rule['minimum']*=origin['area_m2'];rule['maximum']*=origin['area_m2']
     rule['unit']='people' if group=='people' else 'W'
     rule['basis']='按来源房间 '+origin['zone']+' 的每间实际值复用；原密度已乘来源面积。'
    room['loads'][group]=rule
   elif group in GAIN_KEYS:
    gains=gain_values(room,defaults);key=GAIN_KEYS[group];chosen=gain_values(origin,defaults)[key]
    if gains[key]!=chosen:gains[key]=chosen;room['gain_settings']=gains
   elif group=='available':room['hvac']['available']=copy.deepcopy(origin['hvac']['available'])
   else:
    for key in TEMPERATURES:room['hvac'][key]=origin['hvac'][key]
 if result!=content:result['schema_version']=2
 validate_content(result,base)
 changes=differences(content,result,base,defaults);patches=[]
 for i,(old,new) in enumerate(zip(content['rooms'],result['rooms'])):
  paths=[['loads',c] for c in CHANNELS]+[['gain_settings']]
  if old['hvac']:paths += [['hvac',key] for key in (*TEMPERATURES,'available')]
  for path in paths:
   left=old if len(path)==1 else old[path[0]];right=new if len(path)==1 else new[path[0]];key=path[-1]
   if left.get(key)!=right.get(key):patches.append(dict(room=i,path=path,before_present=key in left,before=copy.deepcopy(left.get(key)),after=copy.deepcopy(right[key])))
 return dict(content=result,differences=changes,notes=context_notes(changes,result,overrides or {},mode),
  source_room=dict(id=origin['id'],zone=origin['zone'],area_m2=origin['area_m2']),targets=targets,groups=groups,basis=basis,
  undo=dict(before_sha256=digest(content),after_sha256=digest(result),schema_before=content['schema_version'],patches=patches))

def undo(content,receipt,base,defaults):
 validate_content(content,base)
 if not isinstance(receipt,dict) or not isinstance(receipt.get('patches'),list):raise ValueError('没有可撤销的复用记录。')
 result=copy.deepcopy(content);seen=set()
 for patch in receipt['patches']:
  i=patch.get('room');path=patch.get('path');allowed=[['loads',c] for c in CHANNELS]+[['gain_settings']]+[['hvac',k] for k in (*TEMPERATURES,'available')]
  if type(i) is not int or not 0<=i<len(result['rooms']) or path not in allowed:raise ValueError('复用撤销记录无效。')
  key=(i,*path)
  if key in seen:raise ValueError('复用撤销记录含重复字段。')
  seen.add(key);room=result['rooms'][i];parent=room if len(path)==1 else room[path[0]]
  if not isinstance(parent,dict) or parent.get(path[-1])!=patch.get('after'):raise ValueError(room['zone']+' 的复用字段已被再次编辑；未撤销任何修改，请通过差异核对后调整。')
  if patch.get('before_present'):parent[path[-1]]=copy.deepcopy(patch['before'])
  else:parent.pop(path[-1],None)
 if digest(content)==receipt.get('after_sha256'):
  result['schema_version']=receipt.get('schema_before');validate_content(result,base)
  if digest(result)!=receipt.get('before_sha256'):raise ValueError('撤销记录与复用前的配置不匹配。')
 validate_content(result,base)
 return dict(content=result,differences=differences(content,result,base,defaults))

def preview(body,catalog):
 content=body.get('content') or body.get('before') or {}
 base,model,_=baseline(catalog,building_id=content.get('building_id'));defaults=gain_defaults(model);action=body.get('action')
 if action=='reuse':return reuse(body['content'],body['source'],body['source_room'],body['targets'],body['groups'],body['basis'],base,defaults,body.get('overrides'),body.get('mode','controlled'))
 if action=='undo':return undo(body['content'],body['receipt'],base,defaults)
 if action=='compare':
  diff=differences(body['before'],body['after'],base,defaults)
  return dict(differences=diff,notes=context_notes(diff,body['after'],body.get('overrides',{}),body.get('mode','controlled')))
 raise ValueError('房间配置操作不受支持。')
