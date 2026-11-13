"""One persistent queue and resource budget for every batch in this workspace."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import uuid
from foundation import ROOT, now, owned, read_json, sha, canonical
import output_storage
from execution_inputs import load_review
from execution_results import verify_artifacts
import resources

class Queue:
    def __init__(self,root=ROOT):
        self.root=Path(root).resolve();self.folder=owned(self.root/'data/execution',self.root);self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder/'queue.sqlite'
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,review TEXT UNIQUE NOT NULL,plan TEXT NOT NULL,checksum TEXT NOT NULL,mode TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(batch TEXT NOT NULL,idx INTEGER NOT NULL,status TEXT NOT NULL,identity TEXT NOT NULL,attempt TEXT,pid INTEGER,result TEXT,error TEXT,updated TEXT NOT NULL,PRIMARY KEY(batch,idx));
            CREATE TABLE IF NOT EXISTS cache(identity TEXT PRIMARY KEY,path TEXT NOT NULL,checksum TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,created TEXT NOT NULL,batch TEXT,action TEXT NOT NULL,details TEXT NOT NULL);
            ''')
            output_storage.schema(c)
            if 'result_sha256' not in [r[1] for r in c.execute('PRAGMA table_info(jobs)')]:c.execute('ALTER TABLE jobs ADD COLUMN result_sha256 TEXT')
            c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('resources',canonical(resources.settings({'profile':'custom','max_parallel':1,'reserve_gib':2}))))

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row
        try:
            c.execute('PRAGMA busy_timeout=15000');c.execute('BEGIN IMMEDIATE')
            yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()

    def event(self,c,batch,action,details):c.execute('INSERT INTO events(created,batch,action,details) VALUES(?,?,?,?)',(now(),batch,action,canonical(details)))

    def policy(self):
        with self.db() as c:return json.loads(c.execute("SELECT value FROM settings WHERE key='resources'").fetchone()[0])

    def set_policy(self,value):
        value=resources.settings(value)
        with self.db() as c:
            c.execute("UPDATE settings SET value=? WHERE key='resources'",(canonical(value),));self.event(c,None,'resources',value)
        return value

    def submit(self,review,checksum,storage=None):
        plan=load_review(self.root,review,checksum)
        with self.db() as c:
            existing=c.execute('SELECT id FROM batches WHERE review=?',(review,)).fetchone()
            if existing:return dict(id=existing[0],reused_submission=True)
            destination=storage or output_storage.capture(root=self.root)
            output_storage.verify(destination,self.root,probe=True)
            ident='batch_'+uuid.uuid4().hex
            c.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(ident,review,canonical(plan),checksum,'run',now()))
            from foundation import digest
            c.execute('INSERT INTO batch_storage VALUES(?,?,?)',(ident,canonical(destination),digest(destination)))
            for case in plan['cases']:c.execute('INSERT INTO jobs(batch,idx,status,identity,updated) VALUES(?,?,?,?,?)',(ident,case['index'],'pending',case['identity'],now()))
            self.event(c,ident,'submit',dict(review=review,case_count=len(plan['cases']),storage=destination))
        return dict(id=ident,reused_submission=False)

    def control(self,ident,action):
        if action not in ('pause','resume','cancel_pending','retry'):raise ValueError('不支持的队列操作。')
        with self.db() as c:
            if not c.execute('SELECT 1 FROM batches WHERE id=?',(ident,)).fetchone():raise ValueError('未找到批次。')
            mode='pause' if action=='pause' else 'cancel' if action=='cancel_pending' else 'run'
            c.execute('UPDATE batches SET mode=? WHERE id=?',(mode,ident))
            if action=='cancel_pending':c.execute("UPDATE jobs SET status='cancelled',updated=? WHERE batch=? AND status IN ('pending','interrupted')",(now(),ident))
            if action=='retry':
                c.execute("UPDATE jobs SET status='pending',pid=NULL,error=NULL,updated=? WHERE batch=? AND status IN ('failed','interrupted')",(now(),ident))
            self.event(c,ident,action,{})
        return dict(id=ident,action=action)

    def recover(self):
        # Only the exclusively locked worker calls this. Successful jobs stay intact.
        with self.db() as c:
            rows=c.execute("SELECT DISTINCT batch FROM jobs WHERE status='running'").fetchall()
            for row in rows:
                c.execute("UPDATE batches SET mode='pause' WHERE id=?",(row[0],));self.event(c,row[0],'worker_interruption',{})
            c.execute("UPDATE jobs SET status='interrupted',pid=NULL,error='调度进程中断；现场保留，需重试未完成项。',updated=? WHERE status='running'",(now(),))

    def next_pending(self):
        with self.db() as c:
            row=c.execute("SELECT j.batch,j.idx,b.plan FROM jobs j JOIN batches b ON b.id=j.batch WHERE j.status='pending' AND b.mode='run' ORDER BY b.created,b.rowid,j.idx LIMIT 1").fetchone()
        if not row:return None
        plan=json.loads(row['plan']);return dict(batch=row['batch'],idx=row['idx'],mode=plan['cases'][row['idx']]['mode'])

    def claim(self,expected=None):
        with self.db() as c:
            row=c.execute("SELECT j.*,b.plan,b.checksum FROM jobs j JOIN batches b ON b.id=j.batch WHERE j.status='pending' AND b.mode='run' ORDER BY b.created,b.rowid,j.idx LIMIT 1").fetchone()
            if not row:return None
            if expected and (row['batch'],row['idx'])!=(expected['batch'],expected['idx']):return None
            row=dict(row);row['plan']=json.loads(row['plan']);row['case']=row['plan']['cases'][row['idx']]
            attempt='attempt_'+uuid.uuid4().hex
            c.execute("UPDATE jobs SET status='running',attempt=?,result=NULL,error=NULL,updated=? WHERE batch=? AND idx=?",(attempt,now(),row['batch'],row['idx']))
            self.event(c,row['batch'],'claim',dict(index=row['idx'],attempt=attempt))
            row['storage']=output_storage.bind_attempt(c,row['batch'],attempt,self.root)
            row['attempt']=attempt
            return row

    def set_pid(self,job,pid):
        with self.db() as c:c.execute('UPDATE jobs SET pid=?,updated=? WHERE batch=? AND idx=?',(pid,now(),job['batch'],job['idx']))

    def finish(self,job,status,result=None,error=None):
        if status not in ('passed','review','failed','reused'):raise ValueError('Invalid terminal job state')
        with self.db() as c:
            c.execute('UPDATE jobs SET status=?,result=?,result_sha256=?,error=?,pid=NULL,updated=? WHERE batch=? AND idx=?',(status,result,sha(result) if result else None,error,now(),job['batch'],job['idx']))
            if status=='passed':c.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(job['identity'],result,sha(result)))
            self.event(c,job['batch'],status,dict(index=job['idx'],attempt=job['attempt'],result=result,error=error))

    def cached(self,identity):
        with self.db() as c:r=c.execute('SELECT * FROM cache WHERE identity=?',(identity,)).fetchone()
        if not r:return None
        try:
            path=output_storage.checked_path(r['path'],self.root)
            if sha(path)!=r['checksum']:return None
            result=read_json(path)
            if result['status']!='passed' or result['identity']!=identity:return None
            verify_artifacts(result);return str(path)
        except (OSError,KeyError,ValueError):return None

    def state(self):
        with self.db() as c:
            batches=[dict(x) for x in c.execute('SELECT * FROM batches ORDER BY created DESC,rowid DESC')]
            jobs=[dict(x) for x in c.execute('SELECT * FROM jobs ORDER BY idx')]
        for b in batches:
            plan=json.loads(b.pop('plan'));b.pop('checksum');b.update(record_name=plan['record_name'],revision=plan['revision'],case_count=plan['case_count'],output_contract=plan.get('output_contract','monthly_period_v1'))
            b['storage']=output_storage.batch_destination(self.root,b['id'])
            b['jobs']=[]
            for row in jobs:
                if row['batch']!=b['id']:continue
                case=plan['cases'][row['idx']];b['jobs'].append({k:row[k] for k in ('idx','status','pid','attempt','error','updated')}|{k:case[k] for k in ('city','mode','site_id','period','step_minutes')})
            b['counts']={s:sum(j['status']==s for j in b['jobs']) for s in ('pending','running','passed','reused','review','failed','interrupted','cancelled')}
        path=self.folder/'worker.json';worker=read_json(path) if path.exists() else None
        return dict(resources=self.policy(),batches=batches,worker=worker)

    def results(self,ident):
        with self.db() as c:
            b=c.execute('SELECT plan FROM batches WHERE id=?',(ident,)).fetchone()
            if not b:raise ValueError('未找到批次。')
            jobs=[dict(x) for x in c.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx',(ident,))]
        plan=json.loads(b[0]);results=[]
        for j in jobs:
            if not j['result']:continue
            p=output_storage.checked_path(j['result'],self.root)
            if not j['result_sha256'] or sha(p)!=j['result_sha256']:raise ValueError('结果汇总的校验记录缺失或文件变化，请核查。')
            r=read_json(p)
            if r['identity']!=j['identity']:raise ValueError('结果与任务身份不符。')
            verify_artifacts(r);results.append(dict(index=j['idx'],**r))
        return dict(id=ident,record_name=plan['record_name'],record_id=plan['record_id'],revision=plan['revision'],bundle_id=plan['bundle_id'],conditioned_area_m2=plan['conditioned_area_m2'],results=results)

def ensure_worker(root=ROOT):
    root=Path(root).resolve();q=Queue(root)
    import sys
    with (q.folder/'worker.log').open('ab') as log:
        subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'execution_worker.py'),'--root',str(root)],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
