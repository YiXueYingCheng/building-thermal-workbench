"""Local property edits on existing ordinary layers; preserve geometry/boundaries."""
import copy,math
from foundation import digest

FIELDS={'Material':('thickness','conductivity','density','specific_heat','thermal_absorptance','solar_absorptance','visible_absorptance'),
 'WindowMaterial:SimpleGlazingSystem':('u_factor','solar_heat_gain_coefficient','visible_transmittance')}
LABELS={'thickness':'厚度 / m','conductivity':'导热系数 / W/(m·K)','density':'密度 / kg/m³','specific_heat':'比热 / J/(kg·K)',
 'thermal_absorptance':'热发射率','solar_absorptance':'太阳吸收率','visible_absorptance':'可见光吸收率',
 'u_factor':'U / W/(m²·K)','solar_heat_gain_coefficient':'SHGC','visible_transmittance':'可见光透射率'}

def inventory(m):
 result={}
 for kind in ('BuildingSurface:Detailed','FenestrationSurface:Detailed'):
  for ident,s in m.get(kind,{}).items():
   c=m['Construction'][s['construction_name']]
   names=[c['outside_layer']]+[c[k] for k in sorted(c,key=lambda k:int(k[6:]) if k.startswith('layer_') else 0) if k.startswith('layer_')]
   layers=[]
   for name in names:
    matches=[k for k in FIELDS if name in m.get(k,{})]
    if len(matches)!=1:raise ValueError('普通构造含尚未适配的材料对象：'+name)
    k=matches[0];layers.append(dict(name=name,kind=k,values=copy.deepcopy(m[k][name])))
   parent=m.get('BuildingSurface:Detailed',{}).get(s.get('building_surface_name'),s)
   pair=s.get('outside_boundary_condition_object') if s.get('outside_boundary_condition')=='Surface' or kind=='FenestrationSurface:Detailed' else None
   result[ident]=dict(id=ident,kind=kind,type=s['surface_type'],zone=parent['zone_name'],
    boundary=parent['outside_boundary_condition'],pair=pair or None,construction=s['construction_name'],layers=layers)
 for item in result.values():
  pair=item['pair']
  if pair and (pair not in result or result[pair]['pair']!=item['id']):raise ValueError('相邻面不是相互配对：'+item['id'])
 return result

def validate_overrides(overrides,inventory):
 if not isinstance(overrides,dict) or set(overrides)-set(inventory):raise ValueError('构造修改包含未知表面。')
 for ident,entry in overrides.items():
  base=inventory[ident]
  if base['pair'] in overrides:raise ValueError('同一对相邻表面只从一侧编辑，另一侧同步反向层位。')
  if not isinstance(entry,dict) or set(entry)!={'layers'} or not isinstance(entry['layers'],list) or len(entry['layers'])!=len(base['layers']):raise ValueError('本轮保留原层数和材料类别，只编辑原层参数。')
  for row,old in zip(entry['layers'],base['layers']):
   if set(row)!={'kind','values'} or row['kind']!=old['kind'] or not isinstance(row['values'],dict) or set(row['values'])!=set(old['values']):raise ValueError('层类别或原字段不匹配。')
   for k,v in row['values'].items():
    if k not in FIELDS[row['kind']]:
     if v!=old['values'][k]:raise ValueError('此原字段本轮不编辑：'+k)
     continue
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('构造参数须为有限数值。')
    # Limits from the registered EP26.2 schema; see verification/building2-20261107/schema-fields.json.
    if k=='specific_heat' and v<100:raise ValueError('当前引擎要求比热不低于 100 J/(kg·K)。')
    if k=='thermal_absorptance' and not 0<v<=.99999:raise ValueError('热发射率须大于 0 且不超过 0.99999。')
    if k in ('solar_heat_gain_coefficient','visible_transmittance') and not 0<v<1:raise ValueError('当前等效窗模型要求 SHGC 与可见光透射率大于 0 且小于 1。')
    if k.endswith('absorptance') or k in ('solar_heat_gain_coefficient','visible_transmittance'):
     if not 0<=v<=1:raise ValueError('光学参数应在 0–1。')
    elif v<=0:raise ValueError('厚度及热物性须大于零。')
  if base['pair']:
   other=inventory[base['pair']]['layers']
   if len(other)!=len(base['layers']) or [x['kind'] for x in other]!=[x['kind'] for x in base['layers'][::-1]]:raise ValueError('配对构造的反向层位不匹配，须先核对。')
 return overrides

def apply_overrides(model,overrides,inventory):
 validate_overrides(overrides,inventory);applied=[]
 def put(ident,layers):
  base=inventory[ident];key='NX_Envelope_'+digest(dict(target=ident,layers=layers))[:20]
  construction={}
  for i,layer in enumerate(layers):
   name=key+'_L'+str(i+1);model.setdefault(layer['kind'],{})[name]=copy.deepcopy(layer['values'])
   construction['outside_layer' if i==0 else 'layer_'+str(i+1)]=name
  model['Construction'][key]=construction;model[base['kind']][ident]['construction_name']=key
  applied.append(dict(surface=ident,original=base['construction'],construction=key))
 for ident,entry in overrides.items():
  base=inventory[ident]
  if all(row['values']==old['values'] for row,old in zip(entry['layers'],base['layers'])):continue
  put(ident,entry['layers'])
  if base['pair']:
   other=copy.deepcopy(inventory[base['pair']]['layers'])
   for i,(row,old) in enumerate(zip(entry['layers'],base['layers'])):
    for k,v in row['values'].items():
     if v!=old['values'][k]:other[-1-i]['values'][k]=v
   put(base['pair'],other)
 return applied
