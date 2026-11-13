"""Labels for the library and result choices; no pairing or numerical changes."""
from pathlib import Path
from contextlib import closing
import sqlite3
from foundation import loads,digest

STATUSES=('pending','running','passed','reused','review','failed','interrupted','cancelled')

def batch_index(root,compact=False):
 path=Path(root)/'data/execution/queue.sqlite'
 if not path.exists():return {}
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
  db.row_factory=sqlite3.Row;db.execute('BEGIN')
  rows=[dict(r) for r in db.execute("SELECT id,json_object('record_id',json_extract(plan,'$.record_id'),'revision',json_extract(plan,'$.revision'),'record_sha256',json_extract(plan,'$.record_sha256'),'case_count',json_extract(plan,'$.case_count'),'record_name',json_extract(plan,'$.record_name')) AS plan,mode,created FROM batches" if compact else 'SELECT id,plan,mode,created FROM batches')]
  counts={}
  for r in db.execute('SELECT batch,status,COUNT(*) n FROM jobs GROUP BY batch,status'):counts.setdefault(r['batch'],{})[r['status']]=r['n']
 return {b['id']:{**b,'plan':loads(b['plan']),'counts':counts.get(b['id'],{})} for b in rows}

def batch_status(counts,total,mode):
 if total<=0 or set(counts)-set(STATUSES) or sum(counts.values())!=total:return '状态待核对'
 c={s:counts.get(s,0) for s in STATUSES}
 if c['passed']+c['reused']==total:return '已完成'
 if c['running']:return '计算中，完成当前后暂停' if mode=='pause' else '计算中'
 if c['pending']:return '已暂停，仍有待算项' if mode=='pause' else '排队中'
 if c['failed'] or c['interrupted']:return '有失败或中断项'
 if c['review']:return '计算结束，待复核'
 if c['cancelled']:return '批次结束，含取消项'
 return '状态待核对'

def library_metadata(records,index):
 result={}
 for r in records:
  checksum=digest(r)
  matches=[b for b in index.values() if (b['plan']['record_id'],b['plan']['revision'],b['plan']['record_sha256'])==(r['id'],r['revision'],checksum)]
  result[r['id']]=dict(period=r['factors']['scope']['period'],batch_count=len(matches),latest_batch_created=max((b['created'] for b in matches),default=''))
 return result

def describe_sources(data,store,catalog,index):
 data['record_details']={}
 for side in ('left','right'):
  ref=data['comparison'][side];r=store.get(ref['id'],ref['revision']);f=r['factors']
  data['record_details'][side]=dict(id=r['id'],name=r['name'],revision=r['revision'],period=f['scope']['period'],step_minutes=r['numerics']['step_minutes'],site_count=len(f['scope']['site_ids']))
  for choice in data[side]:
   if choice['id']=='historical':
    jobs=[j for j in catalog['global_bundle']['jobs'].values() if j['case']==r['provenance']['case'] and j['site_id'] in f['scope']['site_ids']]
    passed=sum(j['review_status'].startswith('accepted') and catalog['sites'][j['site_id']]['eligible'] for j in jobs)
    meta=dict(kind='historical',status='原正式历史结果',case_count=len(jobs),site_count=len({j['site_id'] for j in jobs}),counts={'passed':passed,'review':len(jobs)-passed},created=None)
   else:
    b=index.get(choice['id'])
    if b is None:continue
    p=b['plan'];meta=dict(kind='execution',status=batch_status(b['counts'],p['case_count'],b['mode']),case_count=p['case_count'],site_count=len({c['site_id'] for c in p['cases']}),counts=b['counts'],created=b['created'])
   choice['display']=dict(**meta,period=f['scope']['period'],step_minutes=r['numerics']['step_minutes'])
 return data
