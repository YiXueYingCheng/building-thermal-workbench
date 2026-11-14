"""Conservative dependency inspection and cleanup of failed local run bulk outputs.

Accepted, reviewed, reused, unknown and external attempts are never deleted here.
All original JSON, model inputs and diagnostic logs stay in place.
"""
from pathlib import Path
from contextlib import contextmanager, ExitStack, closing
import json,os,re,sqlite3,time,uuid,shutil,stat,threading
from foundation import now,read_json,write_json,digest,sha
import output_storage
from storage_management import safe_child,link,blockers,public_preview

ATTEMPT=re.compile(r'attempt_[a-f0-9]{32}')
BULK={'run/eplusout.sql','run/eplusout.csv','run/eplusout.eso','run/eplusout.mtr'}

@contextmanager
def maintenance(root):
 """Cross-process exclusion shared with backup creation; no stale lock tokens."""
 p=safe_child(root,Path(root)/'data/storage-management/maintenance.lock');p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a+b') as f:
  if not p.stat().st_size:f.write(b'0');f.flush()
  f.seek(0)
  try:
   if os.name=='nt':
    import msvcrt
    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl
    fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:raise ValueError('正在备份或清理，请等待该操作结束。')
  try:yield
  finally:
   f.seek(0)
   if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
   else:fcntl.flock(f,fcntl.LOCK_UN)

class Requests:
 """Normal requests overlap; destructive requests require an idle HTTP service."""
 def __init__(self):self.lock=threading.RLock();self.count=0;self.exclusive=False
 @contextmanager
 def enter(self,exclusive=False):
  with self.lock:
   if self.exclusive or exclusive and self.count:raise ValueError('另有页面操作正在进行，请稍后重新预览清理。')
   self.count+=1;self.exclusive=exclusive
  try:yield
  finally:
   with self.lock:self.count-=1;self.exclusive=False

def strings(value):
 if isinstance(value,str):yield value
 elif isinstance(value,dict):
  for k,v in value.items():yield k;yield from strings(v)
 elif isinstance(value,list):
  for v in value:yield from strings(v)

def documents(root,issues,include_all_databases=False):
 """All managed JSON evidence and JSON-bearing database rows, not file contents of SQL/CSV.
 Unreadable/reparse/oversize metadata blocks cleanup rather than implying no reference.
 """
 root=Path(root);bases=[root/'data',root/'runs',root/'verification']
 try:
  for item in output_storage.entries(root)[1:]:
   try:output_storage.inspect(item,root);bases.append(Path(item['path']))
   except (OSError,ValueError) as e:issues.append('外置位置未能核对：'+str(e))
 except (OSError,ValueError) as e:issues.append('保存位置登记异常：'+str(e))
 for base in bases:
  if not base.exists():continue
  stack=[base]
  while stack:
   folder=stack.pop()
   try:
    safe_child(base,folder)
    for p in folder.iterdir():
     s=p.lstat()
     if link(s):issues.append('资料路径为链接，未扫描：'+str(p));continue
     if p==root/'data/navigation-cache' or p==root/'data/storage-management':continue
     if stat.S_ISDIR(s.st_mode):stack.append(p);continue
     if p.suffix=='.sqlite' and (base==root/'data' or include_all_databases):
      with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
       db.row_factory=sqlite3.Row;db.execute('BEGIN')
       for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if p.name=='queue.sqlite' and not include_all_databases:continue # separately interpreted job/cache/event semantics
        quoted='"'+table.replace('"','""')+'"'
        for row in db.execute('SELECT * FROM '+quoted):
         row=dict(row)
         for k,v in list(row.items()):
          if isinstance(v,str) and v.startswith(('{','[')):row[k]=json.loads(v)
         yield str(p)+'#'+table,dict(row,_storage_table=table)
     elif p.suffix.lower()=='.json':
      if s.st_size>16*2**20:raise ValueError('资料超过本次核对上限：'+str(p))
      # JSON metadata only, never follow paths contained in it.
      yield str(p),read_json(p)
   except (OSError,ValueError,sqlite3.Error) as e:issues.append(str(e))

def label_for(path,value):
 t=value.get('_storage_table','') if isinstance(value,dict) else ''
 if t=='components' and value.get('kind')=='calendar':return '日历参考'
 if t=='comparisons':return '保存的两两比较'
 if t=='research_sets':return '对比集及结果绑定'
 if t=='versions':return '方案保存版本'
 if 'scientific-review' in path:return '结果复核证据'
 if 'export' in path:return '已导出资料'
 if 'model-inputs' in path:return '已生成输入'
 if 'calendar' in path:return '日历核对'
 if 'preparation' in path or '/reviews/' in path.replace('\\','/'):return '计算准备与核对'
 return '登记或结果证据'

def inspect(root,attempt):
 root=Path(root).resolve()
 if not ATTEMPT.fullmatch(str(attempt)):raise ValueError('运行尝试编号不正确。')
 issues=[];refs=[];owners=[];jobs=[];events=[];cache=[]
 q=safe_child(root,root/'data/execution/queue.sqlite')
 try:
  with closing(sqlite3.connect(q.as_uri()+'?mode=ro',uri=True)) as db:
   db.row_factory=sqlite3.Row;db.execute('BEGIN')
   jobs=[dict(r) for r in db.execute('SELECT j.*,b.plan FROM jobs j JOIN batches b ON b.id=j.batch')]
   cache=[dict(r) for r in db.execute('SELECT * FROM cache')]
   events=[dict(r) for r in db.execute('SELECT * FROM events')]
 except (OSError,ValueError,sqlite3.Error) as e:issues.append('任务登记不完整：'+str(e))
 owners=[j for j in jobs if j.get('attempt')==attempt]
 batches={j['batch'] for j in owners};record_ids=set();plans={}
 for j in owners:
  try:
   plans[j['batch']]=json.loads(j['plan']);record_ids.add(plans[j['batch']]['record_id'])
  except (ValueError,KeyError,TypeError):issues.append('任务方案绑定不完整。')
 try:folder=output_storage.attempt_folder(root,attempt);safe_child(folder,folder)
 except (OSError,ValueError,KeyError) as e:folder=root/'runs'/attempt[8:];issues.append('保存位置未核实：'+str(e))
 local=folder.absolute()==(root/'runs'/attempt[8:]).absolute()
 prefix=os.path.normcase(str(folder.absolute())).replace('\\','/').rstrip('/')+'/'
 def match(value,plan=False):
  tokens=set(strings(value))
  if attempt in tokens or any(os.path.normcase(s).replace('\\','/').startswith(prefix) for s in tokens):return '直接文件／运行引用'
  if batches&tokens:return '批次引用（保守保留）'
  if plan and record_ids&tokens:return '关联方案版本（需进一步核对具体结果）'
  return None
 for j in jobs:
  if j in owners:continue
  reason=match({k:v for k,v in j.items() if k!='plan'})
  if reason:refs.append(dict(kind='其他任务／复用',label=j['batch']+' · 算例 '+str(j['idx']+1),source='queue.sqlite/jobs',relation=reason))
 for c in cache:
  if match(c):refs.append(dict(kind='结果复用索引',label=c['identity'],source='queue.sqlite/cache',relation='直接文件引用'))
 for e in events:
  try:
   d=json.loads(e['details'])
   if not isinstance(d,dict):raise ValueError('历史详情不是对象。')
  except (ValueError,TypeError):issues.append('任务历史记录格式异常。');continue
  if d.get('attempt')==attempt and e['action'] in ('passed','review','reused'):
   refs.append(dict(kind='历史完成／复核',label=e['action'],source='queue.sqlite/events',relation='曾登记为完成或待复核，保留'))
 for path,value in documents(root,issues):
  # Self metadata is preserved; completed/review summaries still protect a run.
  if os.path.normcase(path).replace('\\','/').startswith(prefix):
   if isinstance(value,dict) and (value.get('status') in ('passed','review','reused') or value.get('artifacts')):
    refs.append(dict(kind='原始结果摘要',label=Path(path).name,source=path,relation='存在结果／复核依据'))
   continue
  kind=label_for(path,value);relation=match(value,kind in ('保存的两两比较','对比集及结果绑定','已导出资料'))
  if relation:
   payload=value.get('payload',value) if isinstance(value,dict) else {}
   name=(payload.get('name') if isinstance(payload,dict) else None) or (value.get('id') if isinstance(value,dict) else None) or Path(path).name
   rev=value.get('revision') if isinstance(value,dict) else None
   refs.append(dict(kind=kind,label=str(name)+(f' · v{rev}' if rev else ''),source=path,relation=relation))
 unique={digest(r):r for r in refs};refs=sorted(unique.values(),key=lambda r:(r['kind'],r['source'],r['label']))
 reasons=list(dict.fromkeys(issues))
 if not local:reasons.append('外置结果目前仅查看关联；本轮不提供外置文件清理。')
 if len(owners)!=1:reasons.append('没有唯一的当前任务归属，保留历史或未登记目录。')
 elif owners[0]['status'] not in ('failed','cancelled') or owners[0].get('result') or owners[0].get('pid'):
  reasons.append('仅允许已失败／已取消、没有结果登记且无运行进程的当前尝试。')
 if refs:reasons.append('仍存在上述引用或研究依据，保留全部原始文件。')
 owner=[dict(batch=j['batch'],index=j['idx'],status=j['status'],record_id=plans.get(j['batch'],{}).get('record_id') if isinstance(plans.get(j['batch']),dict) else None) for j in owners]
 result=dict(attempt=attempt,path=str(folder),local=local,owners=owner,references=refs,issues=list(dict.fromkeys(issues)),blocked=reasons,
  scope='核对本工作区数据库、受管 JSON 记录、已登记外置结果元数据；批次或方案关联按保守引用保留。外部手工复制的资料无法自动追踪。',
  impact='仅可清理未被使用的失败／取消尝试的 SQL、CSV、ESO、MTR 大文件。保留方案与版本、任务状态及报错、模型输入、JSON 摘要、诊断日志、日历、比较和导出。清理后不能再检查已删文件中的逐时明细；需要时须明确重试计算，不会自动重跑。')
 result['fingerprint']=digest(result)
 return result

def candidates(root,info):
 rows=[];retained=[];folder=Path(info['path'])
 for rel in sorted(BULK):
  p=folder/rel
  try:
   safe_child(root,p)
   if not p.exists():continue
   s=p.lstat()
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ValueError('非普通文件或有共享硬链接，保留。')
   checksum=sha(p);a=p.lstat();stamp=[s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev]
   if stamp!=[a.st_size,a.st_mtime_ns,a.st_ino,a.st_dev]:raise ValueError('读取期间文件变化。')
   rows.append(dict(relative=p.relative_to(root).as_posix(),bytes=s.st_size,stamp=stamp,sha256=checksum))
  except (OSError,ValueError) as e:retained.append(dict(path=str(p),reason=str(e)))
 return rows,retained

def preview(root,attempt,active=False):
 root=Path(root).resolve();info=inspect(root,attempt)
 files,retained=candidates(root,info) if info['local'] else ([],[])
 value=dict(id='cleanup_'+uuid.uuid4().hex,kind='failed_attempt',root=str(root),created=now(),expires_epoch=time.time()+900,attempt=attempt,impact=info['impact'],dependencies=info,files=files,retained=retained,
  blocked=list(dict.fromkeys(info['blocked']+blockers(root,active))),estimated_file_bytes=sum(r['bytes'] for r in files),disk_note='预计为列出文件的内容长度，不等于磁盘实际释放量。保留所有日志与登记；不移入同盘回收区。')
 if value['blocked']:value['estimated_file_bytes']=0
 write_json(safe_child(root,root/'data/storage-management/previews'/(value['id']+'.json')),value,root)
 return public_preview(value)

@contextmanager
def databases_locked(root,exclude=()):
 # Locks only while actually executing; readers remain available. No DB edits.
 with ExitStack() as stack:
  paths=sorted((Path(root)/'data').rglob('*.sqlite'))
  for path in paths:
   if path.resolve() in {Path(p).resolve() for p in exclude}:continue
   safe_child(root,path)
   db=stack.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=.2)))
   try:db.execute('BEGIN IMMEDIATE')
   except sqlite3.Error:raise ValueError('资料正在保存／调度，请稍后重新预览。')
  yield

def execute(root,ident,checksum,confirmed,active=False):
 root=Path(root).resolve()
 if not re.fullmatch('cleanup_[a-f0-9]{32}',str(ident)) or confirmed is not True:raise ValueError('请先预览并勾选确认本次文件清理。')
 with maintenance(root),databases_locked(root):
  value=read_json(safe_child(root,root/'data/storage-management/previews'/(ident+'.json')))
  if digest(value)!=checksum or value.get('root')!=str(root) or value.get('kind')!='failed_attempt':raise ValueError('预览校验不一致。')
  dest=safe_child(root,root/'data/storage-management/receipts'/(ident+'.json'))
  if dest.exists():return read_json(dest)
  if time.time()>value['expires_epoch']:raise ValueError('预览已过期，请重新预览。')
  fresh=inspect(root,value['attempt']);reasons=blockers(root,active)+fresh['blocked']
  if reasons:raise ValueError('；'.join(reasons))
  if fresh['fingerprint']!=value['dependencies']['fingerprint']:raise ValueError('引用或任务状态已变化，请重新预览。')
  # Never trust paths from the stored preview, even if a local file was altered.
  actual,_=candidates(root,fresh);by_path={r['relative']:r for r in actual}
  free=shutil.disk_usage(root).free
  receipt=dict(id=ident,kind='failed_attempt',attempt=value['attempt'],completed=now(),state='executing',preview_sha256=checksum,files=[],removed=0,retained=0,removed_file_bytes=0,observed_disk_free_change=None,
   note='保留原任务状态、报错和诊断日志；已删明细不可恢复，需要时明确重试。若记录显示未完成／未确认，请重新统计并核对文件，不据此认定已释放空间。')
  write_json(dest,receipt,root)
  for row in value['files']:
   item=dict(relative=row['relative'],bytes=row['bytes'],status='retained',reason='')
   try:
    if by_path.get(row['relative'])!=row:raise ValueError('预览后文件已变化或不在本次允许范围内，保留。')
    p=safe_child(root,root/row['relative']);s=p.lstat()
    if s.st_nlink!=1 or [s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev]!=row['stamp'] or sha(p)!=row['sha256']:raise ValueError('执行前文件变化，保留。')
    item.update(status='pending',reason='删除操作尚未确认');receipt['files'].append(item);write_json(dest,receipt,root)
    p.unlink();item.update(status='removed',reason='已清理失败尝试的大文件')
   except (OSError,ValueError) as e:item.update(status='retained',reason=str(e))
   if item not in receipt['files']:receipt['files'].append(item)
   receipt.update(removed=sum(r['status']=='removed' for r in receipt['files']),retained=sum(r['status']!='removed' for r in receipt['files']),removed_file_bytes=sum(r['bytes'] for r in receipt['files'] if r['status']=='removed'))
   write_json(dest,receipt,root)
  receipt.update(state='complete',completed=now(),observed_disk_free_change=shutil.disk_usage(root).free-free);write_json(dest,receipt,root)
  return receipt
