"""Read-only submission projection. Never grants result acceptance or changes a receipt."""
from pathlib import Path
from contextlib import closing
from collections import Counter
import sqlite3,json,copy,re
from foundation import read_json,sha,owned

ACTIVE={'pending','running'}
FINISHED={'passed','reused','review','failed','interrupted','cancelled'}

class Submissions:
 def __init__(self,root):
  self.root=Path(root);self.batches=[];self.cases={}
  path=self.root/'data/execution/queue.sqlite'
  if not path.exists():return
  with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
   db.row_factory=sqlite3.Row;db.execute('BEGIN')
   self.batches=[dict(r) for r in db.execute("""SELECT id,review,checksum,mode,created,
    json_extract(plan,'$.record_id') record_id,json_extract(plan,'$.revision') revision,
    json_extract(plan,'$.record_sha256') record_sha256,
    json_extract(plan,'$.output_contract') output_contract FROM batches""")]
   for row in db.execute("""SELECT b.id batch_id,CAST(c.key AS INTEGER) idx,
    json_extract(c.value,'$.identity') identity,json_extract(c.value,'$.site_id') site_id,
    j.status,j.error FROM batches b,json_each(b.plan,'$.cases') c
    LEFT JOIN jobs j ON j.batch=b.id AND j.idx=CAST(c.key AS INTEGER)"""):
    self.cases.setdefault(row['batch_id'],[]).append(dict(row))

 def review(self,ident,checksum,expected_batch=None,bindings=None):
  try:
   if not re.fullmatch(r'review_[a-f0-9]{32}',str(ident)):raise ValueError('准备清单编号无效')
   path=owned(self.root/'data/execution/reviews'/ident/'plan.json',self.root)
   if not checksum or sha(path)!=checksum:raise ValueError('准备清单摘要不符')
   plan=read_json(path)
   if plan.get('id')!=ident:raise ValueError('准备清单身份不符')
   return self.plan(plan,checksum,expected_batch,bindings)
  except (OSError,ValueError,KeyError,TypeError) as exc:
   return dict(kind='unknown',label='准备关联待核对',batches=[],counts={},covered=0,total=0,note=str(exc))

 def plan(self,plan,checksum,expected_batch=None,bindings=None):
  fields=('record_id','revision','record_sha256','output_contract')
  if any(plan.get(k) is None for k in fields) or not plan.get('cases'):
   return dict(kind='unknown',label='准备信息不完整',batches=[],counts={},covered=0,total=0,note='缺少保存版本、输出要求或算例身份。')
  def bound(b):
   return any((plan['record_id'],plan['revision'],plan['record_sha256'])==(r['target']['id'],r['target']['revision'],r['target']['sha256'])
       and (b['id'],b['checksum'],b['record_id'],b['revision'],b['record_sha256'],b['output_contract'])==
       (r['batch_id'],r['plan_sha256'],r['source']['id'],r['source']['revision'],r['source']['sha256'],plan['output_contract']) for r in bindings or [])
  candidates=[b for b in self.batches if all(b[k]==plan[k] for k in fields) or bound(b)]
  matched=[];covered=set();unknown=False
  for b in candidates:
   exact=b['review']==plan['id'] and b['checksum']==checksum
   if b['review']==plan['id'] and not exact:unknown=True;continue
   jobs=[]
   for i,c in enumerate(plan['cases']):
    for j in self.cases.get(b['id'],[]):
     if (exact and j['idx']==c.get('index',i) or c.get('identity') and j['identity']==c['identity']) and j['site_id']==c['site_id']:
      covered.add(i);jobs.append(j)
   if jobs:matched.append(dict(id=b['id'],review=b['review'],mode=b['mode'],created=b['created'],relation='exact_review' if exact else 'bound_source_same_case' if bound(b) else 'same_saved_input_and_output',jobs=jobs))
  if expected_batch and not any(b['id']==expected_batch for b in matched):unknown=True
  counts=Counter(j['status'] or 'unknown' for b in matched for j in b['jobs'])
  total=len(plan['cases'])
  if unknown or counts.get('unknown'):kind='unknown';label='提交关联待核对'
  elif len(covered)==total:
   kind='finished' if counts and all(k in FINISHED for k in counts) else 'submitted'
   label='已有计算记录 · 队列已结束' if kind=='finished' else '已提交 · 查看批次进度'
  elif covered:kind='partial';label='部分算例已有提交'
  else:kind='unsubmitted';label='已准备 · 未提交'
  return dict(kind=kind,label=label,batches=matched,counts=dict(counts),covered=len(covered),total=total,
      note='按保存版本、清单摘要及含输出要求的算例身份匹配；队列结束不等于结果已接受。')

def approved_sources(sets,record,snapshot=None):
 """Only explicit, still-valid source bindings may cover another record ID."""
 from research_sets import ref,recipe
 target=ref(record);out=[]
 if snapshot is None:
  owner=sets.store.member_owners().get(record['id'])
  if not owner:return out
  snapshot=sets.get(owner['set_id'])
 for member in snapshot['members'].values():
  if member['record']!=target:continue
  for candidate in member.get('results',[]):
   try:
    source=sets.store.get(candidate['source']['id'],candidate['source']['revision'])
    if ref(source)==candidate['source'] and recipe(source)==recipe(record)==candidate['recipe']:
     out.append(dict(candidate,target=target))
   except (OSError,ValueError,KeyError,TypeError):continue
 return out

def group(root,receipt,submissions=None,bindings=None):
 s=copy.deepcopy(receipt);q=submissions or Submissions(root);counts=Counter();kinds=Counter()
 for c in s['cases']:
  life=q.review(c.get('review_id'),c.get('plan_sha256'),c.get('batch_id'),(bindings or {}).get(c['role']));c['lifecycle']=life;kinds[life['kind']]+=1
  states=life['counts']
  c['status']=next((k for k in ('running','pending','review','failed','interrupted','cancelled','reused','passed') if states.get(k)), 'prepared' if life['kind']=='unsubmitted' else 'unknown')
  c['error']=life['note'] if life['kind']=='unknown' else c.get('error')
  c['paused']=bool(life['batches'] and all(b['mode']=='pause' for b in life['batches']))
  counts[c['status']]+=1
 complete=len(s['cases'])==s['plan']['cases']
 history=complete and bool(s['cases']) and not any(kinds[k] for k in ('unsubmitted','partial','unknown')) and s['state']!='preparing'
 finished=history and kinds['finished']==len(s['cases'])
 s['counts']=dict(counts);s['can_submit']=s['state']=='prepared' and bool(kinds['unsubmitted']) and not kinds['unknown'] and not kinds['partial']
 s['lifecycle']=dict(history=history,finished=finished,unsubmitted=kinds['unsubmitted'],unknown=kinds['unknown']+kinds['partial'],
   label='历史安排 · 关联队列已结束' if finished else '已提交的安排' if history else '准备关联待核对' if kinds['unknown']+kinds['partial'] else s['message'])
 return s
