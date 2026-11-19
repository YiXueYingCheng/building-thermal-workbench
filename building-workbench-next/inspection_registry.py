"""Logical queue evidence for accepted-reference calendar previews.

Dispatch bookkeeping is not a scientific source change. Frozen plans and accepted
result bindings are; actual result files remain covered by inspection_io hashes.
"""
from pathlib import Path
import hashlib,json,sqlite3
from contextlib import closing

def key(root):return 'calendar_queue_snapshot:'+str(Path(root).resolve())

def read_queue(root,record):
    """Freeze only accepted jobs that can supply this calendar's W00 reference."""
    from execution_inputs import DAILY_CONTRACT
    from surface_materials import restore_reference_step
    from foundation import digest,owned
    path=Path(root).resolve()/'data/execution/queue.sqlite'
    if not path.exists():return [],{}
    reference={**record,'numerics':dict(record['numerics'])}
    restore_reference_step(reference)
    sites=set(reference['factors']['scope']['site_ids'])
    batches=[];jobs={}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        candidates=list(db.execute("""SELECT * FROM batches AS b
            WHERE EXISTS (SELECT 1 FROM jobs WHERE batch=b.id AND status IN ('passed','reused'))
            AND json_extract(b.plan,'$.output_contract')=? ORDER BY b.created DESC,b.rowid DESC""",(DAILY_CONTRACT,)))
        accepted_by_batch={b['id']:db.execute("SELECT * FROM jobs WHERE batch=? AND status IN ('passed','reused')",
                                               (b['id'],)).fetchall() for b in candidates}
    # Release the queue's read transaction before doing any filesystem work.
    reviews=path.parent/'reviews'
    for batch in candidates:
        plan=json.loads(batch['plan'])
        indices={c['index'] for c in plan['cases'] if c['site_id'] in sites and
                 c['mode']=='controlled' and c['period']==[1,1,12,31] and c['step_minutes']==reference['numerics']['step_minutes']}
        accepted={j['idx']:dict(j) for j in accepted_by_batch[batch['id']] if j['idx'] in indices}
        if not accepted:continue
        frozen=owned(reviews/batch['review']/'record.json',reviews)
        source=json.loads(frozen.read_text(encoding='utf-8-sig'))
        if digest(source)!=plan['record_sha256']:raise ValueError('逐日参考的冻结方案与清单不一致。')
        if source['factors']['building']['id']!=reference['factors']['building']['id']:continue
        batches.append(dict(batch))
        jobs.update({(batch['id'],idx):job for idx,job in accepted.items()})
    return batches,jobs

def signature(snapshot):
    batches,jobs=snapshot
    # Creation order is significant when equivalent daily CSVs are available.
    plans=[{k:b[k] for k in ('id','created','review','checksum','plan')} for b in batches]
    accepted=[{k:j[k] for k in ('batch','idx','status','identity','attempt','result','result_sha256')}
              for _,j in sorted(jobs.items()) if j['status'] in ('passed','reused')]
    data=json.dumps([plans,accepted],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
    return hashlib.sha256(data).hexdigest()

def watch_queue(reads,root,record):
    ident=key(root)
    if ident in reads.memo:return
    snapshot=read_queue(root,record)
    reads.watch_value(ident,lambda:signature(read_queue(root,record)),signature(snapshot),
                      '本次建筑和地点范围内可用的 W00 逐日参考登记已变化')
    # Every daily-reference read in this preview sees this same transaction.
    reads.memo[ident]=snapshot

def watched_queue(reads,root):
    ident=key(root)
    return reads.memo.get(ident)
