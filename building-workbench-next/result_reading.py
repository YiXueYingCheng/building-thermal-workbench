"""Display/export reader; execution/reuse/review retain strict original verification."""
from pathlib import Path
from contextlib import closing
import sqlite3,json
from foundation import sha,read_json
import output_storage
import summary_retention

def results(root,ident):
 def snapshot():
  with closing(sqlite3.connect((Path(root)/'data/execution/queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
   db.row_factory=sqlite3.Row;db.execute('BEGIN')
   b=db.execute('SELECT plan FROM batches WHERE id=?',(ident,)).fetchone()
   if not b:raise ValueError('未找到批次。')
   return b[0],[dict(j) for j in db.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx',(ident,))]
 before,jobs=snapshot();plan=json.loads(before);out=[]
 for j in jobs:
  if not j['result']:continue
  p=output_storage.checked_path(j['result'],root)
  if not j['result_sha256'] or sha(p)!=j['result_sha256']:raise ValueError('结果汇总缺失或内容变化，不能读取。')
  r=read_json(p)
  if r['identity']!=j['identity']:raise ValueError('结果与任务身份不一致。')
  mark=summary_retention.verify(root,j,r)
  if sha(p)!=j['result_sha256']:raise ValueError('读取期间汇总发生变化。')
  out.append(dict(r,index=j['idx'],**({'data_retention':mark} if mark else {})))
 if snapshot()!=(before,jobs):raise ValueError('读取期间任务变化，请重新读取。')
 return dict(id=ident,**{k:plan[k] for k in ('record_name','record_id','revision','bundle_id','conditioned_area_m2')},results=out)
