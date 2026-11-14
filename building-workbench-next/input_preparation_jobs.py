"""Persistent progress receipts for bounded input jobs; never launch a simulator."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import copy,time,uuid
from foundation import read_json,write_json,digest,now
import input_pipeline as pipeline
from preparation_gate import slot

class Jobs:
 def __init__(self,root,source_bindings=None):
  self.source_bindings=source_bindings
  self.root=Path(root);self.folder=self.root/'data/input-preparations';self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='input-preparation');self.lock=RLock();self.jobs={}
  for path in self.folder.glob('job_*.json'):
   try:
    j=read_json(path)
    if j['state'] in ('running','queued'):j.update(state='interrupted',finished_epoch=j.get('updated_epoch',time.time()),error='服务已重启；完成项仍保留，点击重试可核对后续接。' if j['kind'] in ('generate','daily') else '服务已重启；原输入仍完整保留，可重新准备预算清单。')
    self.jobs[j['id']]=j
   except (ValueError,KeyError,OSError):continue
 def public(self,j):
  out=copy.deepcopy(j);out.pop('key',None);out.pop('_case_started',None)
  out['elapsed_seconds']=round((time.time() if j['state'] in ('queued','running') else j.get('finished_epoch',time.time()))-j['started_epoch'],1)
  values=j.get('case_seconds',[]);left=max(0,j.get('total',0)-j.get('completed',0))
  if values and left:out['remaining_range_seconds']=[round(sum(values)/len(values)*left*.65),round(sum(values)/len(values)*left*1.65)]
  if j['state']=='ready' and j['kind'] in ('prepare','daily') and j.get('result',{}).get('plan_sha256'):
   from preparation_status import Submissions
   result=out['result']
   try:
    bindings=self.source_bindings(j['record_id'],j['revision']) if self.source_bindings else []
    life=Submissions(self.root).review(result['id'],result['plan_sha256'],bindings=bindings)
   except (OSError,ValueError,KeyError,TypeError) as exc:
    life=dict(kind='unknown',label='准备关联待核对',batches=[],counts={},covered=0,total=0,note=str(exc))
   out['lifecycle']=life
   out['stage']=life['label']
   if life['batches']:
    result['existing_batch']={k:life['batches'][0][k] for k in ('id','mode','created')}
    result['existing_batch_count']=len(life['batches'])
  return out
 def update(self,j,**values):
  with self.lock:
   if j['kind']=='prepare' or (j['kind']=='daily' and values.get('phase',j.get('phase'))=='prepare'):
    if values.get('stage')=='逐地点准备预算清单':j['_case_started']=time.monotonic()
    if values.get('stage')=='算例清单已保存' and j.get('_case_started') is not None:
     j.setdefault('case_seconds',[]).append(round(time.monotonic()-j.pop('_case_started'),3))
   j.update(values,updated_epoch=time.time());write_json(self.folder/(j['id']+'.json'),j,self.root)
 def latest(self,ident,revision,kind=None):
  if kind is not None and kind not in ('generate','prepare','daily'):raise ValueError('准备记录类型无效。')
  with self.lock:
   rows=[j for j in self.jobs.values() if (j['record_id'],j['revision'])==(ident,revision) and (j['kind']==kind if kind else j['kind'] in ('generate','prepare'))]
   return self.public(max(rows,key=lambda j:j['started_epoch'])) if rows else None
 def get(self,ident):
  with self.lock:
   if ident not in self.jobs:raise ValueError('输入准备记录不存在，请重新打开计算安排。')
   return self.public(self.jobs[ident])
 def start(self,record,catalog,kind='generate',bundle_id=None,expected_record_sha256=None):
  if kind not in ('generate','prepare','daily'):raise ValueError('输入准备类型无效。')
  if kind=='daily':
   from daily_reference import require_baseline,record_key
   require_baseline(record)
   if record_key(record)!=expected_record_sha256:raise ValueError('逐日准备内容与保存版本不同，请重新核对。')
  if kind=='prepare':
   from preparation_recovery import saved_input
   from record_store import Store
   saved_input(self.root,bundle_id,Store(catalog,self.root),dict(id=record['id'],revision=record['revision']))
  key=digest([kind,digest(record),bundle_id,pipeline.code_identity()])
  with self.lock:
   for j in self.jobs.values():
    if j['key']==key and j['state'] in ('queued','running'):return self.public(j)
   if any(j['state'] in ('queued','running') for j in self.jobs.values()):raise ValueError('已有输入准备正在进行；完成后再开始下一份，避免叠加内存。')
   total=len(record['factors']['scope']['site_ids'])*(2 if record['factors']['condition']['operation']['mode']=='both' else 1)
   j=dict(id='job_'+uuid.uuid4().hex,key=key,kind=kind,record_id=record['id'],revision=record['revision'],record_name=record['name'],bundle_id=bundle_id,
       state='queued',phase='prepare' if kind=='prepare' else 'generate',stage='等待开始',completed=0,total=total,started_epoch=time.time(),created=now(),case_seconds=[],new_simulations=0)
   self.jobs[j['id']]=j;self.update(j);self.pool.submit(self.run,j,record,catalog);return self.public(j)
 def run(self,j,record,catalog):
  self.update(j,state='running');token=pipeline.EVENTS.set(lambda **v:self.update(j,**v))
  try:
   with slot(self.root,lambda **v:self.update(j,**v)):
    if j['kind']=='generate':result=pipeline.build_bundle(record,catalog,self.root,progress=lambda **v:self.update(j,**v))
    elif j['kind']=='daily':
     from record_store import Store
     from daily_reference import record_key
     from daily_execution import freeze
     result=freeze(self.root,Store(catalog,self.root),catalog,record['id'],record['revision'],record_key(record),progress=lambda **v:self.update(j,**v))
    else:
     from record_store import Store
     from preparation_recovery import prepare
     result=prepare(self.root,j['bundle_id'],Store(catalog,self.root),dict(id=record['id'],revision=record['revision']))
   self.update(j,state='ready',stage='准备完成，尚未提交计算',completed=j['total'],result=result,finished_epoch=time.time())
  except Exception as error:self.update(j,state='failed',error=str(error),stage='准备未完成，完成项保留' if j['kind'] in ('generate','daily') else '清单准备未完成，原输入保留',finished_epoch=time.time())
  finally:pipeline.EVENTS.reset(token)
 def close(self):self.pool.shutdown(wait=False,cancel_futures=True)
