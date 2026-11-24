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
            CREATE TABLE IF NOT EXISTS site_recalculations(parent TEXT NOT NULL,idx INTEGER NOT NULL,original_attempt TEXT NOT NULL,child TEXT PRIMARY KEY,step INTEGER NOT NULL,predecessor TEXT NOT NULL,adopted TEXT,selected_attempt TEXT,selected_hash TEXT,UNIQUE(parent,idx,original_attempt,step,predecessor));
            CREATE TABLE IF NOT EXISTS comparison_step_choices(comparison TEXT NOT NULL,left_batch TEXT NOT NULL,right_batch TEXT NOT NULL,mode TEXT NOT NULL,site TEXT NOT NULL,selection TEXT NOT NULL,PRIMARY KEY(comparison,left_batch,right_batch,mode,site));
            CREATE UNIQUE INDEX IF NOT EXISTS one_adopted_site ON site_recalculations(parent,idx) WHERE adopted IS NOT NULL;
            CREATE TRIGGER IF NOT EXISTS preserve_failed_site BEFORE UPDATE OF status,attempt,result,result_sha256 ON jobs
            WHEN OLD.status='failed' AND EXISTS(SELECT 1 FROM site_recalculations WHERE parent=OLD.batch AND idx=OLD.idx)
            BEGIN SELECT RAISE(ABORT,'原失败记录已关联地点补算，请在原地点确认补算结果。'); END;
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,created TEXT NOT NULL,batch TEXT,action TEXT NOT NULL,details TEXT NOT NULL);
            ''')
            output_storage.schema(c)
            if 'result_sha256' not in [r[1] for r in c.execute('PRAGMA table_info(jobs)')]:c.execute('ALTER TABLE jobs ADD COLUMN result_sha256 TEXT')
            if 'manual_start' not in [r[1] for r in c.execute('PRAGMA table_info(jobs)')]:
                c.execute('ALTER TABLE jobs ADD COLUMN manual_start TEXT')
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_exclusive_start ON jobs(manual_start) WHERE manual_start='exclusive'")
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
        with self.db() as c:value=json.loads(c.execute("SELECT value FROM settings WHERE key='resources'").fetchone()[0])
        # Old workspaces retain their policy; the new optional control is off.
        return dict(value,cpu_limit_enabled=value.get('cpu_limit_enabled',False),cpu_limit_percent=value.get('cpu_limit_percent',80))

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
            if 'site_recalculation' in plan:
                from site_recalculation import attach
                attach(c,plan,ident)
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
            if action=='pause':c.execute("UPDATE jobs SET manual_start=NULL WHERE batch=? AND status='pending'",(ident,))
            if action=='cancel_pending':c.execute("UPDATE jobs SET status='cancelled',manual_start=NULL,updated=? WHERE batch=? AND status IN ('pending','interrupted')",(now(),ident))
            if action=='retry':
                c.execute("UPDATE jobs SET status='pending',pid=NULL,error=NULL,updated=? WHERE batch=? AND status IN ('failed','interrupted') AND NOT EXISTS (SELECT 1 FROM site_recalculations s WHERE s.parent=jobs.batch AND s.idx=jobs.idx)",(now(),ident))
            self.event(c,ident,action,{})
        return dict(id=ident,action=action)

    def control_job(self,batch,index,action):
        if type(index) is not int or index < 0 or action not in ('requeue_cancelled','force_one','release_force'):
            raise ValueError('请选择有效的算例和操作。')
        with self.db() as db:
            row=db.execute('SELECT j.status,j.manual_start,b.mode FROM jobs j JOIN batches b ON b.id=j.batch WHERE j.batch=? AND j.idx=?',(batch,index)).fetchone()
            if not row:raise ValueError('找不到所选算例。')
            if action=='requeue_cancelled':
                if row['status']!='cancelled':raise ValueError('仅能重新排队已取消的算例，请刷新队列。')
                # A paused batch may contain other pending jobs. Wake just this row.
                db.execute("UPDATE jobs SET status='pending',manual_start='normal',pid=NULL,error=NULL,updated=? WHERE batch=? AND idx=?",(now(),batch,index))
                if not db.execute("SELECT 1 FROM jobs WHERE batch=? AND idx<>? AND status='pending'",(batch,index)).fetchone():
                    db.execute("UPDATE batches SET mode='run' WHERE id=?",(batch,))
            elif action=='force_one':
                if row['status']!='pending' or (row['mode']!='run' and not row['manual_start']):
                    raise ValueError('请先将该算例加入运行队列。')
                if row['manual_start']=='exclusive':return dict(id=batch,index=index,action=action)
                if db.execute("SELECT 1 FROM jobs WHERE manual_start='exclusive'").fetchone():
                    raise ValueError('已有一个算例申请或正在独占运行。请等它结束或撤回申请。')
                db.execute("UPDATE jobs SET manual_start='exclusive' WHERE batch=? AND idx=?",(batch,index))
            else:
                if row['status']!='pending' or row['manual_start']!='exclusive':raise ValueError('独占申请已结束或已经开始运行，请刷新队列。')
                db.execute("UPDATE jobs SET manual_start='normal' WHERE batch=? AND idx=?",(batch,index))
            self.event(db,batch,action,dict(index=index))
        return dict(id=batch,index=index,action=action)

    def recover(self):
        # Only the exclusively locked worker calls this. Successful jobs stay intact.
        with self.db() as c:
            rows=c.execute("SELECT DISTINCT batch FROM jobs WHERE status='running'").fetchall()
            for row in rows:
                c.execute("UPDATE batches SET mode='pause' WHERE id=?",(row[0],));self.event(c,row[0],'worker_interruption',{})
            c.execute("UPDATE jobs SET status='interrupted',manual_start=NULL,pid=NULL,error='调度进程中断；现场保留，需重试未完成项。',updated=? WHERE status='running'",(now(),))

    def _pending(self,db):
        return db.execute("""SELECT j.*,b.plan,b.checksum FROM jobs j JOIN batches b ON b.id=j.batch
            WHERE j.status='pending' AND (b.mode='run' OR j.manual_start IS NOT NULL)
            ORDER BY CASE WHEN j.manual_start='exclusive' THEN 0 ELSE 1 END,b.created,b.rowid,j.idx LIMIT 1""").fetchone()

    def next_pending(self):
        with self.db() as c:
            row=self._pending(c)
        if not row:return None
        plan=json.loads(row['plan']);return dict(batch=row['batch'],idx=row['idx'],mode=plan['cases'][row['idx']]['mode'],exclusive=row['manual_start']=='exclusive')

    def claim(self,expected=None):
        with self.db() as c:
            row=self._pending(c)
            if not row:return None
            exclusive=row['manual_start']=='exclusive'
            if expected and (row['batch'],row['idx'],exclusive)!=(expected['batch'],expected['idx'],expected.get('exclusive',False)):return None
            if c.execute("SELECT 1 FROM jobs WHERE status='running' AND (? OR manual_start='exclusive') LIMIT 1",(exclusive,)).fetchone():return None
            row=dict(row);row['plan']=json.loads(row['plan']);row['case']=row['plan']['cases'][row['idx']]
            attempt='attempt_'+uuid.uuid4().hex
            c.execute("UPDATE jobs SET status='running',attempt=?,result=NULL,error=NULL,updated=? WHERE batch=? AND idx=?",(attempt,now(),row['batch'],row['idx']))
            self.event(c,row['batch'],'claim',dict(index=row['idx'],attempt=attempt,exclusive=exclusive))
            row['storage']=output_storage.bind_attempt(c,row['batch'],attempt,self.root)
            row['attempt']=attempt
            return row

    def set_pid(self,job,pid):
        with self.db() as c:c.execute('UPDATE jobs SET pid=?,updated=? WHERE batch=? AND idx=?',(pid,now(),job['batch'],job['idx']))

    def finish(self,job,status,result=None,error=None):
        if status not in ('passed','review','failed','reused'):raise ValueError('Invalid terminal job state')
        with self.db() as c:
            c.execute('UPDATE jobs SET status=?,manual_start=NULL,result=?,result_sha256=?,error=?,pid=NULL,updated=? WHERE batch=? AND idx=?',(status,result,sha(result) if result else None,error,now(),job['batch'],job['idx']))
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
            verify_artifacts(result,self.root);return str(path)
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
                case=plan['cases'][row['idx']];b['jobs'].append({k:row[k] for k in ('idx','status','pid','attempt','error','updated','manual_start')}|{k:case[k] for k in ('city','mode','site_id','period','step_minutes')})
            b['counts']={s:sum(j['status']==s for j in b['jobs']) for s in ('pending','running','passed','reused','review','failed','interrupted','cancelled')}
        from worker_runtime import status
        worker=status(self.root)
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
            verify_artifacts(r,self.root);results.append(dict(index=j['idx'],**r))
        return dict(id=ident,record_name=plan['record_name'],record_id=plan['record_id'],revision=plan['revision'],bundle_id=plan['bundle_id'],conditioned_area_m2=plan['conditioned_area_m2'],results=results)

def ensure_worker(root=ROOT):
    from worker_runtime import ensure
    return ensure(root)
