"""Apply a selected equivalent-resistance material to verified exterior walls."""
import copy,math,re
from foundation import digest,now

BUILDING='building2_5f_verified'
PLACEMENT='ordinary_exterior_nomass_v1'
SURFACE_DEFAULTS=dict(roughness='MediumSmooth',visible_absorptance=.55)

def targets(source):
 return sorted(k for k,v in source['envelope'].items() if v['kind']=='BuildingSurface:Detailed' and v['type']=='Wall' and v['boundary']=='Outdoors')

def vertices(surface):
 if 'vertices' in surface:return [tuple(v['vertex_'+k+'_coordinate'] for k in 'xyz') for v in surface['vertices']]
 return [tuple(surface[f'vertex_{i}_{k}_coordinate'] for k in 'xyz') for i in range(1,int(surface['number_of_vertices'])+1)]

def measure(surface):
 p=vertices(surface)
 if len(p)<3 or any(not math.isfinite(x) for v in p for x in v):raise ValueError('构件顶点不完整。')
 vector=[sum(a[(k+1)%3]*b[(k+2)%3]-a[(k+2)%3]*b[(k+1)%3] for a,b in zip(p,p[1:]+p[:1]))/2 for k in range(3)]
 area=math.sqrt(sum(v*v for v in vector))
 if area<=0:raise ValueError('构件面积必须大于零。')
 return area,vector

def inventory(model,source,overrides=None):
 from ordinary_envelope import validate_overrides
 overrides=overrides or {};validate_overrides(overrides,source['envelope'])
 rules=list(model['GlobalGeometryRules'].values());buildings=list(model['Building'].values())
 if len(rules)!=1 or rules[0].get('coordinate_system')!='World' or rules[0].get('vertex_entry_direction')!='Counterclockwise' or len(buildings)!=1 or buildings[0].get('north_axis',0)!=0:raise ValueError('本建筑坐标约定已变化，需重新核对外墙朝向。')
 room_by_zone={r['zone']:r for r in source['usage']['rooms']};rows=[]
 for ident in targets(source):
  surface=model['BuildingSurface:Detailed'][ident];area,n=measure(surface);zone=surface['zone_name'];room=room_by_zone[zone]
  if abs(n[2])>1e-8 or model['Zone'][zone].get('multiplier',1)!=1:raise ValueError('倾斜墙或重复热区需单独核对面积。')
  openings=[]
  for key,item in model.get('FenestrationSurface:Detailed',{}).items():
   if item['building_surface_name']==ident:
    value,_=measure(item);openings.append(dict(id=key,type=item['surface_type'],area_m2=value*item.get('multiplier',1)))
  opened=sum(v['area_m2'] for v in openings);net=area-opened
  if net<=0:raise ValueError('洞口面积与外墙面积不匹配。')
  azimuth=math.degrees(math.atan2(n[0],n[1]))%360;floor_match=re.fullmatch(r'R(\d+)-\d+',zone)
  original=source['envelope'][ident]['layers'];effective=overrides.get(ident,{}).get('layers',original)
  rows.append(dict(id=ident,zone=zone,room_id=room['id'],use=source['usage_sources'][room['id']]['use'],conditioned=room['conditioned'],
                   floor=int(floor_match[1]) if floor_match else None,azimuth=azimuth,direction=('北','东','南','西')[int((azimuth+45)//90)%4],
                   gross_m2=area,opening_m2=opened,net_m2=net,openings=openings,layers=copy.deepcopy(effective),original_layers=copy.deepcopy(original),
                   construction=surface['construction_name'],locally_edited=ident in overrides and any(a['values']!=b['values'] for a,b in zip(effective,original))))
 totals=dict(walls=len(rows),gross_m2=sum(r['gross_m2'] for r in rows),opening_m2=sum(r['opening_m2'] for r in rows),net_m2=sum(r['net_m2'] for r in rows))
 def groups(key):
  return [dict(value=k,walls=len(subset),net_m2=sum(r['net_m2'] for r in subset)) for k in sorted({r[key] for r in rows},key=str) if (subset:=[r for r in rows if r[key]==k])]
 return dict(totals=totals,rows=rows,by_direction=groups('direction'),by_conditioned=groups('conditioned'),by_floor=groups('floor'))

def preset(source,catalog,state_id='R',*,definition=None,selected=None,face='A'):
 if state_id not in ('R','C'):raise ValueError('请选择固定蓬松 R 或固定压缩 C。')
 if definition is None:
  from starter_library import eca_preset
  definition=eca_preset()['content']
 definition=copy.deepcopy(definition)
 ids=targets(source) if selected is None else selected
 if not isinstance(ids,list) or not ids or not all(isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)) or not set(ids)<=set(targets(source)):
  raise ValueError('请选择本建筑中不重复的室外墙。')
 ids=sorted(ids)
 from solid_eca import MODEL,PLACEMENT as solid_placement
 placement=solid_placement if definition.get('model')==MODEL else PLACEMENT
 app=dict(id='eca_walls',material_id=definition['id'],component='wall',position='exterior',target_ids=ids,
          orientation={'A':'cooling_face','B':'other_face'},placement_basis=placement,surface_model=copy.deepcopy(SURFACE_DEFAULTS))
 controls=[dict(application_id=app['id'],channel='thermal',mode='fixed',target_ids=ids,state_id=state_id),
           dict(application_id=app['id'],channel='orientation',mode='fixed',target_ids=ids,face_id=face)]
 return dict(definitions=[definition],applications=[app]),controls

def validate(record,source):
 from solid_eca import enabled,validate as solid_validate
 if enabled(record):return solid_validate(record,source)
 f=record['factors'];m=f['materials'];controls=f['condition']['controls'];refs=f['condition']['reference_runs']
 if m=={'definitions':[],'applications':[]} and not controls and not refs:return None
 if set(m)-{'definitions','applications','definition_reference'} or len(m['definitions'])!=1 or len(m['applications'])!=1:raise ValueError('本轮支持单层 ECA，不使用多材料叠层。')
 d=m['definitions'][0];a=m['applications'][0];ids=sorted(a['target_ids'])
 if not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(targets(source)):raise ValueError('当前铺设范围含重复墙或非本建筑室外墙。')
 if set(d)-{'id','name','kind','model','state_identity','states','optics','optics_depend_on_state','source_note'}:raise ValueError('材料包含本轮未表达的参数。')
 if d['kind']!='single_layer' or d['model']!='equivalent_resistance_no_layer_storage' or d.get('state_identity')!='independent':raise ValueError('本轮仅支持无独立层蓄热的 ECA 等效热阻。')
 states={s['id']:s for s in d['states']}
 if set(states)!={'R','C'}:raise ValueError('ECA 需保留 R/C 独立状态定义。')
 for state in states.values():
  if set(state)-{'id','name','thermal_input','resistance_m2K_W','thickness_mm','conductivity_W_mK'}:raise ValueError('本轮不额外推断材料层热容。')
 expected=dict(id=a['id'],material_id=d['id'],component='wall',position='exterior',target_ids=ids,orientation={'A':'cooling_face','B':'other_face'},placement_basis=PLACEMENT,surface_model=SURFACE_DEFAULTS)
 actual=copy.deepcopy(a);actual['target_ids']=sorted(actual.get('target_ids',[]))
 if actual!=expected:raise ValueError('请核对已选外墙、材料编号和室外附加层定义。')
 if len(controls)!=2:raise ValueError('请为所选外墙指定热阻状态及朝外面。')
 thermal=[c for c in controls if c.get('channel')=='thermal']
 state_id=thermal[0].get('state_id') if len(thermal)==1 else None
 if state_id not in ('R','C'):raise ValueError('请选择固定蓬松 R 或固定压缩 C。')
 orientation=[c for c in controls if c.get('channel')=='orientation']
 face=orientation[0].get('face_id') if len(orientation)==1 else None
 if face not in ('A','B'):raise ValueError('请选择朝外的光学参数组。')
 want=[dict(application_id=a['id'],channel='thermal',mode='fixed',target_ids=ids,state_id=state_id),dict(application_id=a['id'],channel='orientation',mode='fixed',target_ids=ids,face_id=face)]
 if refs:
  from calendar_library import verify_reference
  if len(refs)!=1 or state_id!='R':raise ValueError('此等效热阻层按日历翻面时须固定蓬松 R，并绑定已核对的逐日日历版本。')
  snapshot=verify_reference(refs[0])
  if snapshot['content']['schema_version']!=2 or snapshot['content']['basis']['building']['id']!=source['building']['id']:raise ValueError('请采用本建筑自身的逐日日历。')
  want[1].update(mode='calendar',reference_id=refs[0]['id'])
 observed=copy.deepcopy(controls)
 for item in observed:item['target_ids']=sorted(item.get('target_ids',[]))
 if sorted(observed,key=lambda x:x.get('channel',''))!=sorted(want,key=lambda x:x['channel']):raise ValueError('此建筑支持固定 R/C、固定光学组，或固定 R 并按本建筑日历切换表面光学参数；其他光学选择或反馈分组待适配。')
 r=states[state_id].get('resistance_m2K_W');optical=d['optics'].get(face+'_'+state_id,{})
 if type(r) not in (float,int) or not math.isfinite(r) or r<=0:raise ValueError('所选状态热阻须为有限正数。')
 if set(optical)-{'reflectance','solar_absorptance','emissivity','input_basis'}:raise ValueError('所选朝外面的光学参数含未支持字段。')
 for key in ('solar_absorptance','emissivity'):
  v=optical.get(key)
  if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError('需明确所选朝外面的太阳吸收率与发射率。')
 if optical['emissivity']<=0 or optical['emissivity']>.99999:raise ValueError('本引擎的外侧层发射率须大于 0 且不超过 0.99999。')
 return dict(material_id=d['id'],name=d['name'],state=state_id,face=face,resistance_m2K_W=r,optics=copy.deepcopy(optical),targets=ids,surface_model=copy.deepcopy(SURFACE_DEFAULTS))

def apply(model,record,source):
 from solid_eca import enabled,apply as solid_apply
 if enabled(record):return solid_apply(model,record,source)
 spec=validate(record,source)
 if spec is None:return None
 name='NX_ECA_Exterior_'+digest(spec)[:20];values=dict(**spec['surface_model'],thermal_resistance=spec['resistance_m2K_W'],solar_absorptance=spec['optics']['solar_absorptance'],thermal_absorptance=spec['optics']['emissivity'])
 if name in model.get('Material:NoMass',{}):raise ValueError('研究层名称与原模型冲突。')
 model.setdefault('Material:NoMass',{})[name]=values;rows=[]
 for ident in spec['targets']:
  surface=model['BuildingSurface:Detailed'][ident]
  if surface['surface_type']!='Wall' or surface['outside_boundary_condition']!='Outdoors':raise ValueError('应用对象不再是原外墙。')
  old=surface['construction_name'];c=model['Construction'][old]
  layers=[c['outside_layer']]+[c[k] for k in sorted((k for k in c if k.startswith('layer_')),key=lambda k:int(k.split('_')[1]))]
  if len(layers)>=10:raise ValueError('原构造层数无法再添加研究层。')
  key=name+'_'+digest(dict(original=old,layers=layers))[:12]
  new=dict(outside_layer=name,**{'layer_'+str(i+2):v for i,v in enumerate(layers)})
  if key in model['Construction'] and model['Construction'][key]!=new:raise ValueError('新构造名称冲突。')
  model['Construction'][key]=new;surface['construction_name']=key
  rows.append(dict(surface=ident,original=old,construction=key,layers_before=layers,layers_after=[name]+layers))
 return dict(**spec,object_name=name,object_values=values,surfaces=rows,model='Material:NoMass 外侧附加层；原墙体层序保留')

def preview(record,catalog,action='adopt',state_id='R'):
 from ordinary_building import source,model,capability
 from model_adapter import VerifiedReader
 from contracts import normalize
 s=source(catalog,record['factors']['building']['id']);reader=VerifiedReader(catalog);m=model(s,reader);data=inventory(m,s,record['factors']['building'].get('envelope_overrides'))
 out=copy.deepcopy(record)
 if action=='adopt':
  if state_id not in ('R','C'):raise ValueError('请选择固定蓬松 R 或固定压缩 C。')
  if record['factors']['materials']['definitions']:
   validate(normalize(record),s)
   # Switching operating state must retain the user's material values and library pin.
   for control in out['factors']['condition']['controls']:
    if control['channel']=='thermal':control['state_id']=state_id
  else:out['factors']['materials'],out['factors']['condition']['controls']=preset(s,catalog,state_id)
 elif action=='remove':
  validate(normalize(record),s);out['factors']['materials']={'definitions':[],'applications':[]};out['factors']['condition']['controls']=[]
 elif action!='inspect':raise ValueError('未知材料核对操作。')
 if action!='inspect' and record['factors']['condition']['reference_runs']:raise ValueError('请先核对已有参考日历，不能直接替换。')
 out=normalize(out);cap=capability(out,catalog)
 if not cap['supported'] and action!='inspect':raise ValueError('；'.join(cap['reasons']))
 current=validate(normalize(record),s);planned=validate(out,s);reader.unchanged()
 result=dict(action=action,inventory=data,current=current,planned=planned,materials=out['factors']['materials'],controls=out['factors']['condition']['controls'],
             record_sha256=digest(record),changed=out['factors']['materials']!=record['factors']['materials'] or out['factors']['condition']['controls']!=record['factors']['condition']['controls'],
             source=s['models']['controlled'],generation=cap)
 result['orientation_mode']='calendar' if any(c.get('channel')=='orientation' and c.get('mode')=='calendar' for c in record['factors']['condition']['controls']) else 'fixed'
 result['preview_sha256']=digest(result);result['checked_at']=now();return result
