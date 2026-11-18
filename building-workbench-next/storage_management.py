"""Read-only space ledger and narrowly scoped disposable-navigation-cache cleanup.

No plan, input, export, result, source or backup deletion is exposed here.
File lengths are not allocated disk clusters; free-space observations are separate.
"""
from pathlib import Path
from contextlib import closing
from collections import defaultdict
import os,stat,sqlite3,json,re,hashlib,threading,uuid,time,shutil
from foundation import now,read_json,write_json,digest,sha
import output_storage

CATEGORIES=dict(records='方案、版本与任务登记',inputs='已生成计算输入',preparations='准备与核对证据',results='原始计算结果',exports='汇总与导出',cache='可再生浏览缓存',public='建筑、气象与公共资料',backups='备份',program='程序与其他文件')
CACHE_RE=re.compile(r'view-[a-f0-9]{64}\.json')
_locks=defaultdict(threading.RLock)

def link(info):return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)

def safe_child(root,path):
 root=Path(root).absolute();path=Path(path).absolute()
 if not path.is_relative_to(root) or '..' in path.parts:raise ValueError('文件不在受管目录内。')
 for candidate in [path,*path.parents]:
  try:
   if link(candidate.lstat()):raise ValueError('链接或重定向路径不参与扫描／清理。')
  except FileNotFoundError:pass
  if candidate==root:break
 if not path.resolve().is_relative_to(root.resolve()):raise ValueError('文件实际位置超出受管目录。')
 return path

def queue_metadata(root):
 path=Path(root)/'data/execution/queue.sqlite';batches={};attempts=defaultdict(list);active=[];issues=[]
 if not path.exists():return batches,attempts,active,issues
 try:
  with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
   db.row_factory=sqlite3.Row;db.execute('BEGIN')
   for r in db.execute("SELECT id,review,created,json_extract(plan,'$.record_id') record_id,json_extract(plan,'$.revision') revision,json_extract(plan,'$.record_name') name FROM batches"):
    batches[r['id']]=dict(r)
   for r in db.execute('SELECT batch,idx,status,attempt,result FROM jobs'):
    row=dict(r)
    if row['status'] in ('pending','running','queued','starting'):active.append(dict(batch=row['batch'],status=row['status']))
    if row['attempt']:attempts[row['attempt']].append(dict(batches.get(row['batch'],{}),index=row['idx'],status=row['status']))
    if row['result']:
     for part in Path(row['result']).parts:
      if re.fullmatch('[a-f0-9]{32}',part):
       key='attempt_'+part
       if not any(x.get('id')==row['batch'] and x.get('index')==row['idx'] for x in attempts[key]):attempts[key].append(dict(batches.get(row['batch'],{}),index=row['idx'],status=row['status']))
   if db.execute("SELECT 1 FROM sqlite_master WHERE name='attempt_storage'").fetchone():
    for r in db.execute('SELECT attempt,batch FROM attempt_storage'):
     if not any(x.get('id')==r['batch'] for x in attempts[r['attempt']]):attempts[r['attempt']].append(dict(batches.get(r['batch'],{}),status='历史尝试'))
 except (OSError,sqlite3.Error,ValueError) as exc:issues.append('任务登记未能完整读取：'+str(exc))
 return batches,attempts,active,issues

def plan_names(root):
 path=Path(root)/'data/drafts.sqlite';out={}
 if path.exists():
  try:
   with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
    for ident,revision,name in db.execute("SELECT id,revision,json_extract(payload,'$.name') FROM versions"):out[(ident,revision)]=name
  except (sqlite3.Error,OSError):pass
 return out

def category(rel,public=False,external=False):
 p=rel.parts
 if public:return 'public',p[0] if p else 'public'
 if external:return 'results',p[0] if p else 'results'
 if p[0]=='runs':return 'results','/'.join(p[:2])
 if p[0]=='backups':return 'backups','/'.join(p[:2])
 if p[0]=='data' and len(p)>1:
  if p[1]=='navigation-cache':return 'cache','data/navigation-cache'
  if p[1]=='model-inputs':return 'inputs','/'.join(p[:3])
  if p[1] in ('input-preparations','research-set-preparations','calendar-inspections','result-reviews','checks'):return 'preparations','/'.join(p[:3])
  if p[1]=='execution' and len(p)>2 and p[2] in ('reviews','artifacts'):return 'preparations','/'.join(p[:4])
  if 'export' in p[1] or p[1] in ('analysis','comparison-results'):return 'exports','/'.join(p[:3])
  if p[1] in ('weather-files','weather-registry','imports','imported-buildings','building-imports','import-checks','examples'):return 'public','/'.join(p[:2])
  return 'records','data/登记与其他记录'
 return 'program','程序与其他文件'

def inventory(root):
 root=Path(root).resolve();started=time.monotonic();batches,attempts,active,issues=queue_metadata(root);names=plan_names(root)
 locations=[dict(id='workspace',label='工作区',path=str(root),public=False,external=False)]
 for name in ('resources','examples','dependencies','docs'):
  p=root.parent/name
  if p.exists():locations.append(dict(id='package-'+name,label='随平台资源 · '+name,path=str(p),public=True,external=False))
 try:external=output_storage.entries(root)[1:]
 except (OSError,ValueError,KeyError) as exc:external=[];issues.append('保存位置登记未能读取：'+str(exc))
 for item in external:locations.append(dict(item,public=False,external=True))
 groups={};seen={};skipped=[];files=0;unique_bytes=0
 for loc in locations:
  base=Path(loc['path']);loc.update(status='known',bytes=0,unique_bytes=0,files=0,issues=[])
  try:
   safe_child(base,base)
   if loc['external']:output_storage.inspect(loc,root)
   if not base.is_dir():raise OSError('目录不存在或不可访问，不能据此认定零占用。')
  except (OSError,ValueError) as exc:
   loc.update(status='unknown',bytes=None,unique_bytes=None,error=str(exc));continue
  stack=[base]
  while stack:
   directory=stack.pop()
   try:
    safe_child(base,directory)
    with os.scandir(directory) as entries:
     for entry in entries:
      p=Path(entry.path)
      try:
       # Windows DirEntry.stat can omit file IDs; lstat is needed for hardlink accounting.
       info=p.lstat()
       if link(info):skipped.append(dict(path=str(p),reason='链接／重定向，未跟随'));loc['status']='partial';continue
       if stat.S_ISDIR(info.st_mode):stack.append(p);continue
       if not stat.S_ISREG(info.st_mode):continue
       rel=p.relative_to(base);kind,key=category(rel,loc['public'],loc['external']);gid=loc['id']+':'+key
       group=groups.setdefault(gid,dict(id=gid,category=kind,label=key,path=str(base/key) if key not in ('程序与其他文件','data/登记与其他记录') else str(base),location=loc['label'],files=0,bytes=0,unique_bytes=0,shared_files=0,updated_epoch=0,references=[],registered='保留',cleanup_allowed=False))
       group['files']+=1;group['bytes']+=info.st_size;group['updated_epoch']=max(group['updated_epoch'],info.st_mtime)
       loc['files']+=1;loc['bytes']+=info.st_size;files+=1
       identity=(info.st_dev,info.st_ino) if info.st_ino else ('path',os.path.normcase(str(p.absolute())))
       if identity not in seen:seen[identity]=gid;group['unique_bytes']+=info.st_size;loc['unique_bytes']+=info.st_size;unique_bytes+=info.st_size
       else:
        group['shared_files']+=1
        if seen[identity]!=gid:groups[seen[identity]]['shared_files']+=1
      except OSError as exc:loc['status']='partial';loc['issues'].append(dict(path=str(p),error=str(exc)))
   except (OSError,ValueError) as exc:loc['status']='partial';loc['issues'].append(dict(path=str(directory),error=str(exc)))
 for g in groups.values():
  p=Path(g['path']);kind=g['category']
  if kind=='cache':g.update(label='浏览与列表缓存',cleanup_allowed=True,registered='可再生；不作为计算或结果接受依据')
  elif kind=='results':
   ident='attempt_'+p.name;g['attempt']=ident if re.fullmatch('attempt_[a-f0-9]{32}',ident) else None;g['references']=attempts.get(ident,[]);g['registered']='已有任务登记' if g['references'] else '未匹配任务登记，保留待核对'
   for r in g['references']:r['name']=names.get((r.get('record_id'),r.get('revision')),r.get('name') or r.get('record_id') or '来源记录')
  elif kind in ('inputs','preparations'):
   for filename in ('record.json','plan.json'):
    try:
     candidate=safe_child(root,p/filename)
     if candidate.is_file() and candidate.stat().st_size<16*2**20:
      d=read_json(candidate);ident=d.get('record_id',d.get('id'));revision=d.get('revision')
      if ident and revision:g['references']=[dict(record_id=ident,revision=revision,name=d.get('name') or names.get((ident,revision),ident))];break
    except (OSError,ValueError,KeyError):pass
  g['category_name']=CATEGORIES[kind]
 summaries=[]
 for key,label in CATEGORIES.items():
  rows=[g for g in groups.values() if g['category']==key];summaries.append(dict(id=key,label=label,bytes=sum(g['bytes'] for g in rows),unique_bytes=sum(g['unique_bytes'] for g in rows),files=sum(g['files'] for g in rows),groups=len(rows)))
 return dict(created=now(),seconds=round(time.monotonic()-started,3),locations=locations,categories=summaries,groups=sorted(groups.values(),key=lambda g:(g['category'],-g['bytes'],g['id'])),known_unique_file_bytes=unique_bytes,files=files,complete=all(x['status']=='known' for x in locations),links_not_followed=skipped,active_tasks=active,issues=issues,
  note='统计文件内容长度；同一文件或硬链接只在去重合计中计一次，不等于磁盘分配簇。不可访问位置为未知；共享引用列来自任务登记，不代替删除原始结果所需的完整依赖核对。')

def blockers(root,active=False):
 _,_,jobs,issues=queue_metadata(root);reasons=list(issues)
 if jobs:reasons.append('仍有排队或运行任务，先完成或明确暂停／处理任务。')
 if active:reasons.append('输入准备、结果核对或其他后台操作仍在进行。')
 if any((Path(root)/'backups').glob('*.incomplete')):reasons.append('有尚未结束的备份临时包。')
 return reasons

def cache_files(root):
 root=Path(root).resolve();folder=safe_child(root,root/'data/navigation-cache');rows=[];retained=[]
 if not folder.exists():return rows,retained
 for p in sorted(folder.iterdir()):
  try:
   safe_child(root,p);s=p.lstat()
   if not stat.S_ISREG(s.st_mode) or not CACHE_RE.fullmatch(p.name) or s.st_nlink>1:
    retained.append(dict(path=str(p),reason='非标准缓存、目录或共享硬链接，保留'));continue
   value=read_json(p)
   if not isinstance(value,dict) or not {'key','value','sha256','created'}<=set(value) or digest(value['value'])!=value['sha256']:
    retained.append(dict(path=str(p),reason='缓存结构或校验异常，保留核对'));continue
   checksum=sha(p);after=p.stat()
   stamp=[s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev]
   if stamp!=[after.st_size,after.st_mtime_ns,after.st_ino,after.st_dev]:raise ValueError('查看期间文件变化')
   rows.append(dict(path=str(p),relative=p.relative_to(root).as_posix(),bytes=s.st_size,stamp=stamp,sha256=checksum))
  except (OSError,ValueError,KeyError,TypeError) as exc:retained.append(dict(path=str(p),reason=str(exc)))
 return rows,retained

def public_preview(value):
 return {k:v for k,v in value.items() if k!='files'}|dict(files=[{k:r[k] for k in ('relative','bytes','sha256')} for r in value['files']],sha256=digest(value))

def preview(root,active=False):
 root=Path(root).resolve()
 with _locks[str(root)]:
  files,retained=cache_files(root);reasons=blockers(root,active)
  value=dict(id='cleanup_'+uuid.uuid4().hex,root=str(root),created=now(),expires_epoch=time.time()+900,kind='navigation_cache',files=files,retained=retained,blocked=reasons,estimated_file_bytes=sum(f['bytes'] for f in files),
   impact='仅移除上述可再生浏览缓存，下次查看列表、平面或流程时重新读取并生成；首次打开可能稍慢。方案、版本、输入、原始结果、导出、公共资料和备份保留。',disk_note='预计量为待删除文件体积，不保证等于磁盘可用空间增量；不移到同盘回收目录。')
  path=safe_child(root,root/'data/storage-management/previews'/(value['id']+'.json'));write_json(path,value,root)
  return public_preview(value)

def execute(root,ident,checksum,confirmed,active=False):
 root=Path(root).resolve()
 if not re.fullmatch('cleanup_[a-f0-9]{32}',str(ident)) or confirmed is not True:raise ValueError('请预览并明确确认本次缓存清理。')
 with _locks[str(root)]:
  receipt_path=safe_child(root,root/'data/storage-management/receipts'/(ident+'.json'))
  value=read_json(safe_child(root,root/'data/storage-management/previews'/(ident+'.json')))
  if digest(value)!=checksum or value['root']!=str(root) or value['kind']!='navigation_cache':raise ValueError('预览不匹配，请重新核对。')
  if receipt_path.exists():return read_json(receipt_path)
  if time.time()>value['expires_epoch']:raise ValueError('预览已过期，请重新预览。')
  reasons=blockers(root,active)
  if reasons:raise ValueError('；'.join(reasons))
  free_before=shutil.disk_usage(root).free;results=[]
  from navigation_cache import _locks as cache_locks
  for row in value['files']:
   result=dict(relative=row['relative'],bytes=row['bytes'],status='retained',reason='')
   try:
    rel=Path(row['relative'])
    if len(rel.parts)!=3 or rel.parts[:2]!=('data','navigation-cache') or not CACHE_RE.fullmatch(rel.name):raise ValueError('目标不是受管浏览缓存。')
    path=safe_child(root,root/rel)
    with cache_locks[str(path)]:
     safe_child(root,path);s=path.lstat()
     if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ValueError('文件类型或共享关系已有变化')
     if [s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev]!=row['stamp'] or sha(path)!=row['sha256']:raise ValueError('预览后缓存已刷新，保留新文件')
     path.unlink();result.update(status='removed',reason='已删除此缓存文件')
   except (OSError,ValueError) as exc:result['reason']=str(exc)
   results.append(result)
  receipt=dict(id=ident,completed=now(),preview_sha256=checksum,files=results,removed_file_bytes=sum(r['bytes'] for r in results if r['status']=='removed'),removed=sum(r['status']=='removed' for r in results),retained=sum(r['status']!='removed' for r in results),observed_disk_free_change=shutil.disk_usage(root).free-free_before,
   note='删除文件体积与观察到的磁盘可用空间变化分别记录；其他程序写入和文件系统分配也会影响后者。新缓存、异常和共享文件保留，可重新预览剩余项。')
  write_json(receipt_path,receipt,root);return receipt

def history(root):
 folder=Path(root)/'data/storage-management/receipts';rows=[]
 for p in sorted(folder.glob('cleanup_*.json'),reverse=True):
  try:rows.append(read_json(safe_child(root,p)))
  except (OSError,ValueError):pass
 return sorted(rows,key=lambda r:r['completed'],reverse=True)[:20]
