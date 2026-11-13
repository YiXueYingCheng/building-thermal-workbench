"""Logical queue evidence for accepted-reference calendar previews.

Dispatch bookkeeping is not a scientific source change. Frozen plans and accepted
result bindings are; actual result files remain covered by inspection_io hashes.
"""
from pathlib import Path
import copy,hashlib,json,sqlite3
from contextlib import closing

def key(root):return 'calendar_queue_snapshot:'+str(Path(root).resolve())

def read_queue(root):
    path=Path(root).resolve()/'data/execution/queue.sqlite'
    if not path.exists():return [],{}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        batches=[dict(r) for r in db.execute('SELECT * FROM batches ORDER BY created DESC,rowid DESC')]
        jobs={(r['batch'],r['idx']):dict(r) for r in db.execute('SELECT * FROM jobs')}
    return batches,jobs

def signature(snapshot):
    batches,jobs=snapshot
    # Creation order is significant when equivalent daily CSVs are available.
    plans=[{k:b[k] for k in ('id','created','review','checksum','plan')} for b in batches]
    accepted=[{k:j[k] for k in ('batch','idx','status','identity','attempt','result','result_sha256')}
              for _,j in sorted(jobs.items()) if j['status'] in ('passed','reused')]
    data=json.dumps([plans,accepted],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
    return hashlib.sha256(data).hexdigest()

def watch_queue(reads,root):
    ident=key(root)
    if ident in reads.memo:return
    snapshot=read_queue(root)
    reads.watch_value(ident,lambda:signature(read_queue(root)),signature(snapshot))
    # Every daily-reference read in this preview sees this same transaction.
    reads.memo[ident]=copy.deepcopy(snapshot)

def watched_queue(reads,root):
    ident=key(root)
    return copy.deepcopy(reads.memo[ident]) if ident in reads.memo else None
