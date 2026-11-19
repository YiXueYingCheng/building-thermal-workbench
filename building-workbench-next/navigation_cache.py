"""Disposable navigation snapshots. Never used to authorize calculation or results.

File metadata invalidates ordinary viewing; scientific operations still perform
their original content checks. Each saved snapshot has its own content checksum.
"""
from pathlib import Path
from collections import defaultdict
import threading
import copy,sqlite3
from contextlib import closing
from foundation import digest,read_json,write_json,now,sha
CODE=sha(__file__)
_locks=defaultdict(threading.RLock)
def stamps(paths):
    out=[]
    for p in sorted({str(Path(p).resolve()) for p in paths}):
        try:
            s=Path(p).stat();v=[s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino]
        except FileNotFoundError:v=None
        out.append([p,v])
    return out
def cached(root,slot,identity,watch,loader):
    root=Path(root);p=root/'data/navigation-cache'/('view-'+digest(slot)+'.json')
    with _locks[str(p)]:
        before=stamps(watch());key=digest([CODE,identity,before])
        try:
            saved=read_json(p)
            if saved['key']==key and digest(saved['value'])==saved['sha256'] and stamps(saved.get('dependencies',[]))==saved.get('dependency_stamps',[]):
                return saved['value']
        except (OSError,ValueError,KeyError,TypeError):pass
        from inspection_io import reading
        with reading() as scope:value=loader()
        dependencies=list(scope.hashes);after=stamps(watch())
        if before!=after:raise ValueError('查看期间记录有更新，请重新打开。')
        saved=dict(key=key,value=value,sha256=digest(value),created=now(),dependencies=dependencies,dependency_stamps=stamps(dependencies))
        try:write_json(p,saved,root)
        except OSError:pass  # Read-only viewing still works when a cache cannot be written.
        return value
def activity_watch(root):
    root=Path(root);paths=[root/'data/drafts.sqlite',root/'data/drafts.sqlite-wal']
    for pattern in ('data/model-inputs/inputs_*/record.json','data/model-inputs/inputs_*/manifest.json','data/execution/reviews/review_*/plan.json','data/execution/reviews/review_*/record.json'):
        paths.extend(root.glob(pattern))
    return paths
def live_queue(root, *, with_recalculations=False):
    path=Path(root)/'data/execution/queue.sqlite'
    if not path.exists():return [],[],[]
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        batches=[dict(r) for r in db.execute('SELECT id,review,checksum,mode,created FROM batches ORDER BY created DESC,rowid DESC')]
        columns='batch,idx,status,pid,attempt,error,updated'
        if with_recalculations:columns+=',manual_start'
        jobs=[dict(r) for r in db.execute('SELECT '+columns+' FROM jobs ORDER BY idx')]
        if with_recalculations:
            history=defaultdict(list)
            for link in db.execute(
                'SELECT s.parent,s.idx,s.step,s.adopted,j.status FROM site_recalculations s '
                'LEFT JOIN jobs j ON j.batch=s.child AND j.idx=0 ORDER BY s.rowid'
            ):
                history[link['parent'],link['idx']].append(dict(
                    step=link['step'],adopted=link['adopted'] is not None,status=link['status']))
            for job in jobs:
                if job['status'] in ('failed','interrupted'):
                    job['recalculations']=history.get((job['batch'],job['idx']),[])
        storage=[tuple(r) for r in db.execute('SELECT * FROM batch_storage ORDER BY batch')] if db.execute("SELECT 1 FROM sqlite_master WHERE name='batch_storage'").fetchone() else []
    return batches,jobs,storage
def queue_identity(rows,storage):return [[{k:v for k,v in b.items() if k!='mode'} for b in rows],storage]
def refresh_batches(value,rows,jobs):
    from plan_activity import STATUSES
    modes={b['id']:b['mode'] for b in rows};live={(j['batch'],j['idx']):j for j in jobs};out=copy.deepcopy(value)
    for b in out['batches']:
        b['mode']=modes[b['id']];current=[j for j in jobs if j['batch']==b['id']]
        b['counts']={s:sum(j['status']==s for j in current) for s in STATUSES}
        if sum(b['counts'].values())!=b['case_count']:raise ValueError('批次状态有变化，请刷新任务摘要。')
        for j in b.get('jobs',[]):j.update({k:v for k,v in live[(b['id'],j['idx'])].items() if k!='batch'})
    return out
def activity(record,catalog,store,root):
    import plan_activity
    if not (Path(root)/'config.json').exists():return plan_activity.build(record,catalog,store,root)
    rows,jobs,storage=live_queue(root)
    value=cached(root,['activity',record['id'],record['revision']],[digest(record),queue_identity(rows,storage)],lambda:activity_watch(root),lambda:plan_activity.build(record,catalog,store,root))
    return refresh_batches(value,rows,jobs)
def geometry(record,catalog,root):
    import building_geometry
    building={k:v for k,v in record['factors']['building'].items() if k not in ('usage_profile','envelope_overrides')}
    context=[building,record['provenance']['adapter'],catalog.get('ordinary_buildings'),catalog.get('snapshot_id')]
    value=cached(root,['geometry',building['id']],digest(context),lambda:[Path(root)/'data/current.json'],lambda:building_geometry.describe(record,catalog))
    return dict(value,record_id=record['id'],revision=record['revision'])
def queue_state(queue,root):
    from contextlib import closing
    import sqlite3
    root=Path(root);dbpath=root/'data/execution/queue.sqlite'
    def build():
        value=queue.state();value.pop('worker',None);value.pop('resources',None)
        with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
            ids=dict(db.execute("SELECT id,json_extract(plan,'$.record_id') FROM batches"))
        for b in value['batches']:b['record_id']=ids[b['id']]
        return value
    rows,jobs,storage=live_queue(root,with_recalculations=True)
    value=cached(root,'queue',queue_identity(rows,storage),lambda:[],build)
    value=refresh_batches(value,rows,jobs)
    from worker_runtime import status
    exclusive=next((dict(batch=j['batch'],index=j['idx']) for j in jobs if j.get('manual_start')=='exclusive'),None)
    return dict(value,resources=queue.policy(),worker=status(root),exclusive_job=exclusive)
