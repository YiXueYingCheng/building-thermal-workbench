"""Staged DeST database import. Source inspection, conversion and publication are separate."""
from pathlib import Path
import base64,collections,copy,csv,json,math,msvcrt,os,re,shutil,struct,subprocess,threading,time,uuid
from contextlib import contextmanager
from foundation import ROOT,config,read_json,write_json,sha,digest,now,owned

JOBS={};LOCK=threading.Lock()
class ImportCancelled(ValueError):pass

def check_cancel(p):
 if (Path(p)/'cancel.json').exists():raise ImportCancelled('导入已撤销；来源快照与已有检查记录保留。')

def cancelled_state(p,root):
 old=read_json(p/'status.json')
 save(p/'status.json',dict(**{k:v for k,v in old.items() if k not in ('stage','message','updated')},stage='cancelled',updated=now(),message='已撤销，不会加入建筑列表。来源快照与已有检查记录保留。'),root)

def cancel(root,ident):
 root=Path(root).resolve();p=folder(root,ident)
 if (root/'.recovery-copy.json').exists():raise ValueError('恢复副本不修改导入记录。')
 with LOCK:
  state=read_json(p/'status.json')
  if state['stage']=='published' or (root/'data/imported-buildings'/(ident+'.json')).exists():raise ValueError('该导入已加入建筑列表，不能按未完成导入撤销。')
  if state['stage']=='cancelled':return dict(id=ident,stage='cancelled')
  active=str(p) in JOBS
  def request():
   if not (p/'cancel.json').exists():save(p/'cancel.json',dict(requested=now(),previous_stage=state['stage'],action='cancel_unpublished_import',files_deleted=0),root)
   if active:save(p/'status.json',dict(**{k:v for k,v in state.items() if k not in ('stage','message','updated')},stage='cancelling',updated=now(),message='正在撤销；停止后续处理并保留已有记录。'),root)
   else:cancelled_state(p,root)
  if active:request()
  else:
   with locked(root):request()
 return dict(id=ident,stage='cancelling' if active else 'cancelled')
REQUIRED=set('ROOM ROOM_GROUP STOREY ROOM_TYPE_DATA SYS_MATERIAL MAIN_ENCLOSURE SURFACE PLANE GEOMETRY POINT LOOP_POINT WINDOW DOOR SCHEDULE_YEAR CLIMATE_DATA OCCUPANT_GAINS LIGHT_GAINS EQUIPMENT_GAINS DIST_MODE ENVIRONMENT SHADING SYS_DOOR WINDOW_TYPE_DATA ROOM_RELATION GROUND_DATA VERSION_CONTROL'.split())
CHANNELS={'people':'OCCUPANT_GAINS','lighting':'LIGHT_GAINS','equipment':'EQUIPMENT_GAINS'}
TEMPS={'low':'AC_T_MIN_SCHEDULE','heat':'SET_T_MIN_SCHEDULE','cool':'SET_T_MAX_SCHEDULE','high':'AC_T_MAX_SCHEDULE'}

def ref(p):return dict(path=str(Path(p).resolve()),sha256=sha(p),status='verified')
def save(p,v,root):write_json(p,v,root)
def folder(root,ident):
 if not isinstance(ident,str) or not re.fullmatch('import_(?:[a-f0-9]{12}|[a-f0-9]{32})',ident):raise ValueError('导入编号无效。')
 return owned(Path(root)/'data/building-imports'/ident,root)

@contextmanager
def locked(root):
 p=owned(Path(root)/'data/.building-import.lock',root);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a+b') as stream:
  if p.stat().st_size==0:stream.write(b'0');stream.flush()
  stream.seek(0)
  try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
  except OSError:raise ValueError('另一个数据库导入操作正在进行，请稍后刷新。')
  try:yield
  finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def backend(root):
 return Path(config(root)['conversion_root'])

def door_mapper(root):
 import importlib.util
 path=backend(root)/'door_mapping.py'
 spec=importlib.util.spec_from_file_location('_accdb_door_mapping',path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

def inspect_doors(d,root):
 reference=Path(config(root)['import_reference_tables'])
 return door_mapper(root).inspect_doors(d,read_json(reference/'SYS_DOOR.json'),read_json(reference/'SYS_MATERIAL.json'))

def table_data(p):return {x.stem:read_json(x) for x in (p/'tables').glob('*.json')}
def index(rows,key):
 result={r[key]:r for r in rows}
 if len(result)!=len(rows):raise ValueError('来源存在重复编号：'+key)
 return result

def schedules(d):
 result={}
 for row in d['SCHEDULE_YEAR']:
  raw=base64.b64decode(row['DATA']['base64'],validate=True)
  if len(raw)!=8760*8:raise ValueError('来源计划不是 8760 小时。')
  values=list(struct.unpack('<8760d',raw))
  if any(not math.isfinite(v) for v in values):raise ValueError('来源计划含无效数值。')
  if row['SCHEDULE_ID'] in result:raise ValueError('全年计划编号重复。')
  result[row['SCHEDULE_ID']]=values
 return result

def pair(values,label,binary=False):
 a,b=values[:24],values[120:144]
 if len(values)!=8760 or any(values[i*24:(i+1)*24]!=(a if i%7<5 else b) for i in range(365)):
  raise ValueError(label+'含季节/特殊日变化，当前每日编辑器不能无损表达；请保留待适配，或明确选用另一份配置。')
 if binary and any(v not in (0,1) for v in values):raise ValueError(label+'不是 0/1 可用计划。')
 return dict(weekday=a,weekend=b)

def source_rule(d,seq,room,channel):
 rows=[g for g in d[CHANNELS[channel]] if g['OF_ROOM']==room['ID']]
 if len(rows)!=1:raise ValueError(room['NAME']+'每个得热通道须恰有一条来源记录。')
 g=rows[0];key='NUMBER' if channel=='people' else 'POWER'
 rule=dict(kind='scaled',unit=('people' if channel=='people' else 'W')+('/m2' if g['PER_AREA'] else ''),
  minimum=g['MIN'+key],maximum=g['MAX'+key],**pair(seq[g['SCHEDULE']],room['NAME']+' '+channel),basis='ACCDB 源上下限、单位及全年计划；无损归并为工作日/周末')
 from usage_schedules import validate_load
 validate_load(rule,channel,room['AREA']);return rule

def analyse(d,root):
 missing=sorted(REQUIRED-set(d))
 if missing:return dict(passed=False,errors=['缺少必要模型表：'+', '.join(missing)],types=[])
 errors=[];rooms=d['ROOM'];types=index(d['ROOM_TYPE_DATA'],'ID');groups=index(d['ROOM_GROUP'],'ROOM_GROUP_ID');seq=schedules(d)
 if not rooms or len(rooms)>1000:errors.append('当前入口要求 1–1000 间房；结果库不能作为建筑模型导入。')
 index(rooms,'ID')
 if len({r['NAME'] for r in rooms})!=len(rooms) or any(not isinstance(r['NAME'],str) or not r['NAME'].startswith('R') or any(c in r['NAME'] for c in '\r\n,;!') for r in rooms):errors.append('房间名称须唯一、以 R 开头且不含模型分隔符；内部绑定使用源房间 ID。')
 if any(not isinstance(r['AREA'],(int,float)) or not math.isfinite(r['AREA']) or r['AREA']<=0 for r in rooms):errors.append('房间面积须为正数。')
 if d['ROOM_RELATION']:errors.append('源库存在房间通风/关联，需要另行适配，当前不忽略。')
 if any(r['FURNITURE_COEF']!=1 for r in rooms):errors.append('源库家具热容系数不为 1，需要另行适配。')
 if len(d['ENVIRONMENT'])!=1:errors.append('需要唯一的建筑环境与南向定义。')
 for room in rooms:
  if room['TYPE'] not in types or room['OF_ROOM_GROUP'] not in groups:errors.append(room['NAME']+'缺少房间类型或运行组。')
 reference=config(root)['import_reference_tables']
 if not reference:raise ValueError('数据库导入缺少经核对的门窗/材料参考表，请配置 import_reference_tables。')
 reference=Path(reference)
 if not all((reference/name).is_file() for name in ('SYS_DOOR.json','SYS_MATERIAL.json')):
  raise ValueError('门窗/材料参考表不完整，需要 SYS_DOOR.json 和 SYS_MATERIAL.json。')
 door_models,door_errors=inspect_doors(d,root);errors.extend(door_errors)
 source_types=[]
 for tid,t in types.items():
  members=[r for r in rooms if r['TYPE']==tid]
  if not members:continue
  problems=[]
  for room in members:
   for ch in CHANNELS:
    try:source_rule(d,seq,room,ch)
    except (ValueError,KeyError) as exc:problems.append(str(exc))
  source_types.append(dict(id=str(tid),name=t['NAME'],count=len(members),source_supported=not problems,source_issues=list(dict.fromkeys(problems))))
 hvac_issues=[]
 for r in rooms:
  if r['OF_ROOM_GROUP'] not in groups:continue
  g=groups[r['OF_ROOM_GROUP']]
  if not g['IS_AC_ROOM']:continue
  try:
   for key,field in TEMPS.items():
    if len(set(seq[g[field]]))!=1:raise ValueError(r['NAME']+'温控阈值含全年变化。')
   pair(seq[g['AC_SCHEDULE_ID']],r['NAME']+'空调可用',True)
  except (ValueError,KeyError) as exc:hvac_issues.append(str(exc))
 return dict(passed=not errors,errors=list(dict.fromkeys(errors)),rooms=len(rooms),storeys=len(d['STOREY']),area_m2=sum(r['AREA'] for r in rooms),
  conditioned=sum(bool(groups.get(r['OF_ROOM_GROUP'],{}).get('IS_AC_ROOM')) for r in rooms),types=source_types,
  source_hvac_supported=not hvac_issues,source_hvac_issues=list(dict.fromkeys(hvac_issues)),
  shading_count=len(d['SHADING']),shaded_windows=sum(bool(w['CURTAIN'] or w['SHADINGID']) for w in d['WINDOW']),
  south_direction=d['ENVIRONMENT'][0]['SOUTH_DIRECTION'] if d['ENVIRONMENT'] else None,
  door_count=len(d['DOOR']),door_models=door_models,window_count=len(d['WINDOW']),table_count=len(d),
  notes=['几何沿用源中面并转为真北；玻璃采用等效 U、SHGC≈0.87×SC；默认土壤及直接接地须明确确认。',
   '人数、功率上下限和比例计划保留单位；当前仅接通可无损表达为每日及工作日/周末的配置。',
   '空调归属保留源库，温控使用四阈值显热需求模型；设备系统、通风、动态材料不随导入自动接通。'])

def run_command(args,log,cwd):
 check_cancel(cwd)
 flags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
 with Path(log).open('w',encoding='utf-8') as out:
  p=subprocess.Popen([str(a) for a in args],cwd=cwd,stdout=out,stderr=subprocess.STDOUT,creationflags=flags,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'))
  start=time.monotonic()
  try:
   while p.poll() is None:
    check_cancel(cwd)
    if time.monotonic()-start>600:raise ValueError('导入步骤超时，已停止当前子进程；检查日志后重建导入记录。')
    time.sleep(.1)
   check_cancel(cwd)
  finally:
   # Only the child handle created above is eligible for termination; no PID from disk is trusted.
   if p.poll() is None:p.terminate()
   p.wait()
 if p.returncode:
  message=Path(log).read_text(encoding='utf-8',errors='replace')
  if Path(log).name=='extract.log' and any(k in message for k in ('PSSecurityException','UnauthorizedAccess','about_Execution_Policies','数字签名')):
   raise ValueError('Windows 阻止了数据库读取脚本，尚未开始读取建筑。这不是建筑文件损坏。确认来自可信下载后，在包根目录的 PowerShell 运行：Unblock-File -LiteralPath ".\\building-workbench-next\\extract_database.ps1"，然后重新检查文件。此操作只解除该文件的下载标记，不修改全局执行策略；若仍提示签名要求，请联系设备管理员核对组织策略。原日志：'+str(log))
  raise ValueError('数据库读取或转换未通过，详见 '+str(log))

def inspect(path,p,root):
 check_cancel(p)
 source=Path(path).expanduser().resolve(strict=True)
 if not source.is_file() or source.suffix.lower() not in ('.accdb','.mdb') or not 0<source.stat().st_size<=1.5*2**30:raise ValueError('请选择不超过 1.5 GiB 的 ACCDB/MDB 模型文件。')
 if shutil.disk_usage(root).free<source.stat().st_size+2*2**30:raise ValueError('数据库快照与提取前需至少额外保留 2 GiB 磁盘。')
 original=ref(source);dest=p/'source'/source.name;dest.parent.mkdir();shutil.copy2(source,dest)
 check_cancel(p)
 if sha(dest)!=original['sha256'] or sha(source)!=original['sha256']:raise ValueError('复制期间源库发生变化，请关闭 DeST 后重新检查。')
 from runtime_settings import powershell_environment
 pwsh=powershell_environment(config(root))
 # Scope the local helper policy to this process; machine/user policies are untouched.
 # RemoteSigned continues to require signatures for scripts marked as downloaded.
 run_command([pwsh,'-NoProfile','-NonInteractive','-ExecutionPolicy','RemoteSigned','-File',ROOT/'extract_database.ps1','-Database',dest,'-Output',p/'tables'],p/'extract.log',p)
 if sha(source)!=original['sha256'] or sha(dest)!=original['sha256']:raise ValueError('读取期间源库发生变化。')
 extraction=read_json(p/'extraction.json')
 if not extraction['passed']:raise ValueError('数据库部分表未能读取。')
 result=analyse(table_data(p),root);result.update(source=original,snapshot=ref(dest),created=now(),extractor=ref(ROOT/'extract_database.ps1'))
 check_cancel(p)
 result['table_refs']=[ref(x) for x in sorted((p/'tables').glob('*.json'))]
 save(p/'inspection.json',result,root);return result

def verify_inspection(p):
 report=read_json(p/'inspection.json')
 for r in [report['snapshot'],*report['table_refs']]:
  if sha(r['path'])!=r['sha256']:raise ValueError('检查后的数据库快照或提取表已变化，请重新检查。')
 if not report['passed']:raise ValueError('源检查未通过。')
 return report

def options(catalog,root):
 from building_configuration import baseline
 from usage_schedules import gain_defaults,source_snapshot
 from starter_library import usage_templates,describe_choice
 choices,donors=usage_templates()
 for bid,label in ([('drawing26_global_frozen','Drawing26')] if 'global_w00' in catalog['records'] else [])+[(k,v['building']['name']) for k,v in catalog.get('ordinary_buildings',{}).items()]:
  base,m,job=baseline(catalog,building_id=bid);gains=gain_defaults(m)
  sources=source_snapshot(root)['rooms'] if bid=='drawing26_global_frozen' else catalog['ordinary_buildings'][bid]['usage_sources']
  for room in base['rooms']:
   key=bid+':'+room['id'];details=sources.get(room['id'],{});rules={ch:copy.deepcopy(details.get('channels',{}).get(ch,{}).get('rule',room['loads'][ch])) for ch in CHANNELS}
   donors[key]=dict(rules=rules,gains={k:gains[room['id']][k] for k in ('sensible_W_person','lighting_heat_fraction')},source_building=bid,source_room=room['id'],baseline_sha256=base['baseline_sha256'],room_type=details.get('use',''))
   choices.append(describe_choice(key,label+(' 示例原配置' if bid=='drawing26_global_frozen' else ' 原配置')+' · '+room['zone']+' · '+(details.get('use') or '用途未标注'),donors[key]))
 weather=[dict(id=k,name=v['name']) for k,v in catalog['sites'].items() if v.get('eligible') and (v.get('weather') or {}).get('sha256')]
 return dict(choices=choices,weather=weather),donors

def validate_request(req,review,catalog,root):
 allowed={'name','weather','mapping','temperature','thresholds','availability','ground','shading','door_mm','door_confirmations','mapping_confirmed'}
 if not isinstance(req,dict) or set(req)-allowed:raise ValueError('导入选择包含未支持字段。')
 if not isinstance(req.get('name'),str) or not 1<=len(req['name'].strip())<=80:raise ValueError('请输入 1–80 字的建筑名称。')
 if req.get('ground')!='slab_default_soil' or req.get('mapping_confirmed') is not True:raise ValueError('请明确确认直接接地、默认土壤和转换模型。')
 if 'door_models' in review:door_mapper(root).validate_confirmation(req,review['door_models'])
 elif review['door_count'] and (type(req.get('door_mm')) not in (int,float) or req['door_mm']!=25.3):raise ValueError('此前木门检查记录需确认 25.3 mm；其他门类型请重新检查来源。')
 if req.get('shading') not in ('reject','ignore'):raise ValueError('请选择附加遮阳处理。')
 if req['shading']=='reject' and (review['shading_count'] or review['shaded_windows']):raise ValueError('存在附加遮阳；当前不能无损转换，未获明确忽略选择。')
 opts,donors=options(catalog,root);mapping=req.get('mapping')
 if not isinstance(mapping,dict) or set(mapping)!={t['id'] for t in review['types']}:raise ValueError('请逐房间类型选择配置来源。')
 for t in review['types']:
  chosen=mapping[t['id']]
  if chosen=='source':
   if not t['source_supported']:raise ValueError(t['name']+'源配置暂不能无损接入每日编辑器。')
  elif chosen not in donors:raise ValueError('房间配置来源不存在。')
 if req.get('temperature') not in ('source','custom') or req.get('availability') not in ('source','always'):raise ValueError('请选择温控及可用计划来源。')
 if req['temperature']=='custom':
  from building_configuration import validate_hvac
  if not isinstance(req.get('thresholds'),dict) or set(req['thresholds'])!=set(TEMPS):raise ValueError('请填写四个温控阈值。')
  validate_hvac(dict(**req['thresholds'],available=dict(weekday=[1]*24,weekend=[1]*24)))
 site=catalog['sites'].get(req.get('weather'))
 if site is None or not site.get('eligible') or not (site.get('weather') or {}).get('sha256'):raise ValueError('请选择已登记气象。')
 from model_adapter import VerifiedReader
 from source_locations import resolve
 site=copy.deepcopy(site);actual,location=resolve(site['weather'],catalog)
 VerifiedReader().check(actual)
 if location:site.update(weather_origin=site['weather'],source_location=location,weather=actual)
 return {k:donors[v] for k,v in mapping.items() if v!='source'},site

def status(root,ident):
 p=folder(root,ident);v=read_json(p/'status.json')
 if v['stage']!='published' and (p/'cancel.json').exists():v=dict(v,stage='cancelling' if str(p) in JOBS else 'cancelled',message='正在撤销，停止后续处理。' if str(p) in JOBS else '已撤销，不会加入建筑列表；已有记录保留。')
 if v['stage'] in ('inspecting','converting') and str(p) not in JOBS:v=dict(v,stage='interrupted',message='页面服务重启，当前步骤完成状态未确认；保留来源及日志，本记录不会发布，可重新创建导入。')
 for k in ('inspection','acceptance'):
  if (p/(k+'.json')).exists():
   item=read_json(p/(k+'.json'));v[k]={x:y for x,y in item.items() if x not in ('table_refs','source_refs')}
 return v

def listing(root):
 return [status(root,p.name) for p in sorted((Path(root)/'data/building-imports').glob('import_*'),reverse=True) if (p/'status.json').is_file()]

def start(root,action,path=None,ident=None,request=None,catalog=None):
 root=Path(root).resolve()
 if (root/'.recovery-copy.json').exists():raise ValueError('恢复副本不启动导入。')
 with LOCK:
  if any(k.startswith(str(root)) for k in JOBS):raise ValueError('已有数据库导入正在处理。')
  if action=='inspect':
   if not isinstance(path,str) or not path.strip():raise ValueError('请填写数据库完整路径。')
   # Keep old 32-character IDs readable; new imports use short random names.
   # Exclusive creation and the registry check prevent accidental ID reuse.
   for attempt in range(32):
    ident='import_'+uuid.uuid4().hex[:12];p=folder(root,ident)
    if (root/'data/imported-buildings'/(ident+'.json')).exists():continue
    try:p.mkdir(parents=True,exist_ok=False)
    except FileExistsError:continue
    break
   else:raise ValueError('无法分配独立的导入目录，请稍后重试。')
  elif action=='convert':
   p=folder(root,ident)
   check_cancel(p)
   if read_json(p/'status.json')['stage']!='inspected':raise ValueError('该记录尚未通过检查，或已提交转换。')
   validate_request(request,verify_inspection(p),catalog,root)
  else:raise ValueError('未知导入操作。')
  stage='inspecting' if action=='inspect' else 'converting'
  save(p/'status.json',dict(id=ident,stage=stage,created=now(),message='正在读取数据库快照' if action=='inspect' else '正在转换并核对模型'),root)
  def work():
   try:
    with locked(root):
     if action=='inspect':result=inspect(path,p,root);end='inspected' if result['passed'] else 'blocked'
     else:
      from accdb_conversion import convert
      convert(p,request,catalog,root);end='review'
     with LOCK:
      check_cancel(p)
      save(p/'status.json',dict(id=ident,stage=end,updated=now(),message='检查完成' if action=='inspect' else '转换与输入核对通过，待确认加入建筑列表'),root)
   except Exception as exc:
    with LOCK:
     if (p/'cancel.json').exists():cancelled_state(p,root)
     else:save(p/'status.json',dict(id=ident,stage='failed',updated=now(),message=str(exc)),root)
   finally:
    with LOCK:JOBS.pop(str(p),None)
  thread=threading.Thread(target=work,daemon=True);JOBS[str(p)]=thread;thread.start()
 return dict(id=ident,stage=stage)

def publish(root,ident,expected):
 p=folder(root,ident)
 with LOCK,locked(root):
  check_cancel(p)
  state=read_json(p/'status.json');accept=read_json(p/'acceptance.json')
  if state['stage'] not in ('review','published') or expected!=accept['sha256']:raise ValueError('导入核对内容已变，请刷新后确认。')
  payload=read_json(p/'source-record.json')
  if digest(payload)!=expected:raise ValueError('转换后的建筑记录校验失败。')
  from model_adapter import VerifiedReader
  reader=VerifiedReader()
  for r in [*payload['models'].values(),payload['weather'],*payload['dependencies'],*payload['source_refs']]:reader.check(r)
  from manage import current
  catalog=current(root);bid=payload['building']['id'];target=Path(root)/'data/imported-buildings'/(ident+'.json')
  if bid in catalog.get('ordinary_buildings',{}):
   if catalog['ordinary_buildings'][bid]!=payload:raise ValueError('已登记建筑与本次转换不同。')
  else:
   value={bid:payload};save(target,dict(data=value,sha256=digest(value)),root)
  save(p/'status.json',dict(id=ident,stage='published',updated=now(),message='已加入建筑列表；尚未提交计算',record_id=payload['record']['id']),root)
  return dict(id=ident,record_id=payload['record']['id'],new_simulations=0)
