"""Per-site preparations grouped under one pinned research-set version.

Every case uses the existing generator, frozen preparation and persistent queue.
The set runner only coordinates; it never edits inputs or accepts result warnings.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from pathlib import Path
import copy,re,uuid,shutil,os,ctypes,time
from foundation import ROOT,read_json,write_json,digest,now,owned
import output_storage
from research_sets import Sets,ALL_ROLES as ROLES,LABELS,require,compatible,ref
from execution_inputs import load_review,OUTPUT_CONTRACT
from daily_reference import CONTRACT,require_baseline
from execution_queue import Queue,ensure_worker
import resources
from preparation_gate import slot,PreparationPaused

def baseline_contract(record):
 require(record['factors']['condition']['operation']['mode']=='controlled','对比集负荷计算需要温控运行。')
 if record['factors']['scope']['period']==[1,1,12,31]:
  require_baseline(record)
  return CONTRACT
 return OUTPUT_CONTRACT

def owner_alive(pid):
 if not isinstance(pid,int) or pid<=0:return False
 if pid==os.getpid():return True
 from ctypes import wintypes as w
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
 k.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)];k.CloseHandle.argtypes=[w.HANDLE]
 h=k.OpenProcess(0x1000,False,pid)
 if not h:return ctypes.get_last_error()==5
 try:
  code=w.DWORD();return bool(k.GetExitCodeProcess(h,ctypes.byref(code)) and code.value==259)
 finally:k.CloseHandle(h)

def members_match(snapshot,plan):
 return snapshot['id']==plan['id'] and all(snapshot['members'][role]['record']==plan['members'][role] for role in plan['roles'])

class Runs:
 def __init__(self,root,catalog,workers=True):
  self.root=Path(root).resolve();self.catalog=catalog;self.workers=workers
  self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='research-set');self.lock=RLock();self.futures={}
 def folder(self,ident):
  require(bool(re.fullmatch(r'setprep_[a-f0-9]{32}',str(ident))),'组计算记录编号无效。')
  return owned(self.root/'data/research-set-preparations'/ident,self.root)
 def write(self,s,clear_pause=False):
  with self.lock:
   path=self.folder(s['id'])/'state.json'
   if path.exists() and not clear_pause:s['pause_requested']=s.get('pause_requested',False) or read_json(path).get('pause_requested',False)
   s['updated']=now()
   if s['state']!='preparing':s['finished_epoch']=time.time()
   write_json(path,s,self.root)
 def raw(self,ident):return read_json(self.folder(ident)/'state.json')
 def policy(self):return Queue(self.root).policy()
 def preflight(self,ident,revision,roles,destination=None):
  require(type(revision) is int and isinstance(roles,list) and roles and all(k in ROLES for k in roles) and len(set(roles))==len(roles),'请明确选择本组成员。')
  roles=[role for role in ROLES if role in roles]
  catalog=self.catalog();sets=Sets(catalog,self.root);s=sets.get(ident);require(s['revision']==revision,'对比集已更新，请重新核对。')
  records=sets.records(s);require(set(roles)<=set(records),'所选成员不属于本组。');audit=compatible(records);require(audit['consistent'],'共同条件尚未一致：'+'；'.join(audit['issues']))
  baseline=records['baseline'];baseline_contract(baseline)
  from model_adapter import capability
  for role in roles:
   cap=capability(records[role],catalog);require(cap['supported'],LABELS[role]+'：'+'；'.join(cap['reasons']))
  sites=baseline['factors']['scope']['site_ids'];policy=self.policy()
  destination=destination or output_storage.capture(root=self.root)
  storage=output_storage.planning(self.root,destination,len(sites)*len(roles),policy['disk_reserve_gib'])
  return dict(id=ident,revision=revision,set_sha256=s['sha256'],roles=roles,site_ids=sites,
   members={k:ref(records[k]) for k in roles},cases=len(sites)*len(roles),policy=policy,
   storage=storage,destination=destination,
   note='按地点准备小清单，进度集中显示。全年 W00 同时保留逐日参考；短时段仅计算所选日期，不能代替全年日历参考。表面光学切换另需匹配日历。')
 def start(self,ident,revision,roles,expected,submit=False,destination=None):
  require(type(submit) is bool,'提交选项无效。');p=self.preflight(ident,revision,roles,destination)
  require(p['set_sha256']==expected,'对比集版本与预览不同。');require(p['storage']['fits'],'当前空间不足以覆盖本轮留量与磁盘保留值，请减少本轮成员或调整保存位置。')
  key=digest({k:p[k] for k in ('id','revision','set_sha256','roles','site_ids','destination')}|dict(submit=submit))
  with self.lock:
   for f in (self.root/'data/research-set-preparations').glob('setprep_*/state.json'):
    old=read_json(f)
    if old.get('key')==key:return self.get(old['id'])
   s=dict(id='setprep_'+uuid.uuid4().hex,key=key,created=now(),started_epoch=time.time(),unit_seconds=[],state='preparing',message='等待准备本组输入',plan=p,submit=submit,cases=[],error='',owner_pid=os.getpid(),pause_requested=False)
   self.write(s);self.futures[s['id']]=self.pool.submit(self.run,s['id']);return self.get(s['id'])
 def resume(self,ident):
  with self.lock:
   s=self.raw(ident);f=self.futures.get(ident)
   if f and not f.done():return self.get(ident)
   require(s['state'] in ('interrupted','failed','preparing','paused'),'本准备记录无需恢复。')
   require(s['state']!='preparing' or not owner_alive(s.get('owner_pid')),'另一服务仍在准备本组，请先查看其进度。')
   p=s['plan'];latest=Sets(self.catalog(),self.root).get(p['id']);require(members_match(latest,p),'本轮成员已有新版本，请按最新版本重新准备；旧清单保留。')
   for c in s['cases']:
    if c.get('batch_id'):Queue(self.root).control(c['batch_id'],'resume')
   s.update(state='preparing',started_epoch=time.time(),error='',message='从已完成清单继续准备',owner_pid=os.getpid(),pause_requested=False);self.write(s,clear_pause=True);self.futures[ident]=self.pool.submit(self.run,ident);return self.get(ident)
 def pause(self,ident):
  with self.lock:
   s=self.raw(ident);s.update(pause_requested=True,message='正在暂停：当前计算完成后停下，尚未提交项保留')
   f=self.futures.get(ident)
   if not f or f.done():s['state']='paused'
   for c in s['cases']:
    if c.get('batch_id'):Queue(self.root).control(c['batch_id'],'pause')
   self.write(s);return self.get(ident)
 def run(self,ident):
  try:
   s=self.raw(ident);p=s['plan'];catalog=self.catalog();sets=Sets(catalog,self.root);snapshot=sets.get(p['id'],p['revision']);records=sets.records(snapshot)
   destination=p.get('destination') or output_storage.capture('local',self.root)
   from input_pipeline import build_bundle,EVENTS
   from preparation_recovery import prepare
   for sid in p['site_ids']:
    for role in p['roles']:
     if self.raw(ident).get('pause_requested'):
      s.update(state='paused',message='本组已暂停；已提交的当前计算完成后停下');self.write(s);return
     existing=next((c for c in s['cases'] if c['role']==role and c['site_id']==sid),None)
     if existing:
      if s['submit'] and not existing['batch_id']:
       with self.lock:
        if self.raw(ident).get('pause_requested'):
         s.update(state='paused',message='本组已暂停；已完成清单保留');self.write(s);return
        require(members_match(sets.get(p['id']),p),'本轮成员已更新，已完成清单保留但未提交。')
        existing['batch_id']=Queue(self.root).submit(existing['review_id'],existing['plan_sha256'],destination)['id'];self.write(s)
        if self.workers:ensure_worker(self.root)
      continue
     require(members_match(sets.get(p['id']),p),'本轮成员已更新，停止准备剩余项；已提交任务仍绑定原版本。')
     policy=self.policy();space=output_storage.planning(self.root,destination,1,policy['disk_reserve_gib'])
     require(space['fits'],'结果位置或工作区磁盘余量不足，已保留进度；恢复原位置或腾出空间后可继续准备。')
     s['message']='正在准备 '+catalog['sites'][sid]['name']+' · '+LABELS[role];self.write(s)
     r=records[role];require(ref(r)==p['members'][role],'成员快照与本组准备记录不一致。')
     def progress(**values):
      if values.get('stage','').startswith('等待其他') and self.raw(ident).get('pause_requested'):raise PreparationPaused()
      s['preparation_progress']=dict(values,city=catalog['sites'][sid]['name'],role=role,label=LABELS[role]);self.write(s)
     with slot(self.root,progress):
      if self.raw(ident).get('pause_requested'):raise PreparationPaused()
      require(members_match(sets.get(p['id']),p),'等待期间成员已更新，已完成部分保留。')
      unit_start=time.monotonic()
      m=build_bundle(r,catalog,self.root,site_ids=[sid],progress=lambda **v:progress(phase='generate',**v))
      progress(phase='prepare',stage='核对输出并准备预算清单',completed=0,total=1)
      token=EVENTS.set(lambda **v:progress(phase='prepare',**v))
      try:prepared=prepare(self.root,m['id'],sets.store,dict(id=r['id'],revision=r['revision']),output_contract=baseline_contract(r) if role=='baseline' else OUTPUT_CONTRACT)
      finally:EVENTS.reset(token)
      s.setdefault('unit_seconds',[]).append(round(time.monotonic()-unit_start,3))
     require(len(prepared['cases'])==1 and prepared['cases'][0]['site_id']==sid,'地点清单与准备请求不一致。')
     row=dict(role=role,site_id=sid,city=catalog['sites'][sid]['name'],review_id=prepared['id'],plan_sha256=prepared['plan_sha256'],bundle_id=m['id'],batch_id=None)
     with self.lock:
      if s['submit'] and not self.raw(ident).get('pause_requested'):
       require(members_match(sets.get(p['id']),p),'本轮成员已更新，当前清单已保留但未提交。')
       batch=Queue(self.root).submit(row['review_id'],row['plan_sha256'],destination);row['batch_id']=batch['id']
       if self.workers:ensure_worker(self.root)
      s['cases'].append(row);self.write(s)
   if self.raw(ident).get('pause_requested'):s.update(state='paused',message='本组已暂停；已完成清单保留')
   else:s.update(state='submitted' if s['submit'] else 'prepared',message='清单已提交；计算状态见下方逐地点进度' if s['submit'] else '清单已准备，尚未提交计算')
   self.write(s)
  except PreparationPaused:
   s=self.raw(ident);s.update(state='paused',message='本组准备已暂停，已完成清单保留');self.write(s)
  except Exception as e:
   s=self.raw(ident);s.update(state='failed',error=str(e),message='准备已停在问题位置，已完成部分保留');self.write(s)
 def get(self,ident):
  with self.lock:
   s=self.raw(ident);f=self.futures.get(ident)
   if s['state']=='preparing' and not f and not owner_alive(s.get('owner_pid')):
    s.update(state='interrupted',message='准备服务曾重启，可从已保存清单继续')
  from preparation_status import group,approved_sources
  bindings={};p=s['plan']
  if p.get('id'):
   sets=Sets(self.catalog(),self.root);snapshot=sets.get(p['id'])
   if not members_match(snapshot,p):snapshot=sets.get(p['id'],p['revision'])
   for role in p['roles']:
    r=p['members'][role];record=sets.store.get(r['id'],r['revision'])
    if ref(record)==r:bindings[role]=approved_sources(sets,record,snapshot)
  s=group(self.root,s,bindings=bindings)
  if s.get('started_epoch'):
   s['preparation_elapsed_seconds']=round((time.time() if s['state']=='preparing' else s.get('finished_epoch',s['started_epoch']))-s['started_epoch'],1)
  values=s.get('unit_seconds',[]);left=max(0,s['plan']['cases']-len(s['cases']))
  if values and left:s['remaining_range_seconds']=[round(sum(values)/len(values)*left*.65),round(sum(values)/len(values)*left*1.65)]
  return s
 def listing(self,set_id,revision=None):
  rows=[];snapshot=Sets(self.catalog(),self.root).get(set_id,revision)
  for f in (self.root/'data/research-set-preparations').glob('setprep_*/state.json'):
   s=read_json(f)
   if s['plan']['id']!=set_id:continue
   if s['plan']['revision']==snapshot['revision'] or members_match(snapshot,s['plan']):
    rows.append(self.get(s['id']))
  return sorted(rows,key=lambda s:s['created'],reverse=True)
 def submit_prepared(self,ident):
  with self.lock:
   s=self.raw(ident);require(s['state']=='prepared','清单尚未全部准备完成。');p=s['plan']
   projection=self.get(ident)
   require(not projection['lifecycle']['unknown'],'准备与提交关联待核对；未新增计算。')
   pending={c['review_id'] for c in projection['cases'] if c['lifecycle']['kind']=='unsubmitted'}
   if not pending:return projection
   destination=p.get('destination') or output_storage.capture('local',self.root)
   output_storage.verify(destination,self.root,True)
   require(members_match(Sets(self.catalog(),self.root).get(p['id']),p),'本轮成员已更新，请按新版本核对；旧清单保留。')
   for c in s['cases']:
    if c['review_id'] in pending:load_review(self.root,c['review_id'],c['plan_sha256'])
   for c in s['cases']:
    if c['review_id'] not in pending:continue
    c['batch_id']=Queue(self.root).submit(c['review_id'],c['plan_sha256'],destination)['id'];self.write(s)
   s.update(state='submitted',submit=True,message='已提交本组计算');self.write(s)
   if self.workers:ensure_worker(self.root)
   return self.get(ident)
 def close(self):self.pool.shutdown(wait=False)
