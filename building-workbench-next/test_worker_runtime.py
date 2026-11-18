import json,os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from foundation import ROOT,now,write_json,config
import worker_runtime as wr
import output_storage as storage
from execution_queue import Queue

class WorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.q=Queue(self.root)
    def heartbeat(self,**kw):
        write_json(self.q.folder/'worker.json',dict(pid=123,root=str(self.root),heartbeat=now(),active=0,**kw),self.root)
    def batch(self,ident,mode,statuses):
        plan=dict(record_id='fixture',record_name='隔离批次',revision=1,case_count=len(statuses),cases=[dict(index=i,city='test',mode='controlled',site_id='test',period=[1,1,1,2],step_minutes=5) for i in range(len(statuses))])
        with self.q.db() as db:
            db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(ident,ident,json.dumps(plan),'test',mode,now()))
            for i,s in enumerate(statuses):db.execute('INSERT INTO jobs(batch,idx,status,identity,updated) VALUES(?,?,?,?,?)',(ident,i,s,'test',now()))
    def test_dead_or_reused_pid_never_online(self):
        self.heartbeat(process_created='old')
        for info in [dict(alive=False,created=None),dict(alive=True,created='new'),dict(alive=None,created=None)]:
            with patch.object(wr,'process_info',return_value=info):self.assertFalse(wr.status(self.root)['online'])
    def test_reuses_confirmed_worker_without_spawning(self):
        self.heartbeat()
        with patch.object(wr,'process_info',return_value=dict(alive=True,created=None)),patch.object(wr.subprocess,'Popen') as popen:
            self.assertTrue(wr.ensure(self.root)['ready']);popen.assert_not_called()
    def test_startup_failure_includes_log_and_does_not_remove_lock(self):
        lock=self.q.folder/'worker.lock';lock.write_bytes(b'0')
        def start(*a,**kw):
            kw['stdout'].write(b'PermissionError: worker.lock access denied\n');kw['stdout'].flush()
            return MagicMock(pid=123,poll=lambda:1)
        with patch.object(wr.subprocess,'Popen',side_effect=start):
            result=wr.ensure(self.root)
        self.assertFalse(result['ready']);self.assertIn('PermissionError',result['error'])
        self.assertEqual(lock.read_bytes(),b'0');self.assertIn('PermissionError',wr.status(self.root)['diagnostic'])
    def test_alive_but_stale_worker_not_duplicated(self):
        self.heartbeat();p=self.q.folder/'worker.json';v=json.loads(p.read_text('utf8'));v['heartbeat']='2020-01-01T00:00:00+08:00';write_json(p,v,self.root)
        with patch.object(wr,'process_info',return_value=dict(alive=True,created=None)),patch.object(wr.subprocess,'Popen') as popen:
            self.assertFalse(wr.ensure(self.root)['ready']);popen.assert_not_called()
    def test_slow_launch_before_first_heartbeat_not_duplicated(self):
        write_json(self.q.folder/'worker-start.json',dict(pid=456,state='failed',process_created='launch'),self.root)
        def info(pid):return dict(alive=pid==456,created='launch' if pid==456 else None)
        with patch.object(wr,'process_info',side_effect=info),patch.object(wr.subprocess,'Popen') as popen:
            self.assertFalse(wr.ensure(self.root)['ready']);popen.assert_not_called()
            self.assertIn('未收到就绪心跳',wr.status(self.root)['diagnostic'])
    def test_probe_cleanup_failure_nonfatal_and_write_failure_fatal(self):
        real=Path.unlink
        def deny(p,*a,**kw):
            if p.name.startswith('.write-check-'):raise PermissionError('cleanup denied')
            return real(p,*a,**kw)
        with patch.object(Path,'unlink',deny),self.assertWarns(RuntimeWarning):storage.writable(self.root)
        with patch.object(Path,'open',side_effect=PermissionError('write denied')):
            with self.assertRaises(PermissionError):storage.writable(self.root)
    def test_two_34_case_batches_only_probe_on_submission(self):
        import execution_queue
        cases=[dict(index=i,identity=str(i)) for i in range(34)]
        with patch.object(execution_queue,'load_review',return_value=dict(cases=cases)),patch.object(storage,'writable',wraps=storage.writable) as probe:
            for batch_no in range(2):
                self.q.submit('review-'+str(batch_no),'checksum')
                for _ in range(34):
                    job=self.q.claim();folder=storage.attempt_folder(self.root,job['attempt'])
                    folder.mkdir();(folder/'write.txt').write_text('actual write')
                    self.q.finish(job,'failed',error='isolated fixture without engine')
            self.assertEqual(probe.call_count,2)
    def test_http_resume_happens_after_recovery_and_other_pause_preserved(self):
        import server
        cfg=config(ROOT);cfg.update(initialization='new_workspace',port=18933);write_json(self.root/'config.json',cfg,self.root)
        (self.root/'VERSION').write_text('isolated')
        self.batch('one','run',['running','pending','passed']);self.batch('two','pause',['pending'])
        def ensure(_):self.q.recover();return dict(ready=True)
        with patch.object(server,'ensure_worker',side_effect=ensure),patch.object(server.disk_sampling.Sampler,'start'):
            service=server.make_server(self.root,0,start_workers=True)
            th=threading.Thread(target=service.serve_forever,daemon=True);th.start()
            try:
                token=json.loads((self.root/'data/session-token.json').read_text('utf8'))['token']
                def post(path,data):
                    req=Request(f'http://127.0.0.1:{service.server_port}'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Workbench-Token':token})
                    with urlopen(req) as r:return json.load(r)
                post('/api/execution/control',dict(id='one',action='retry'))
                with self.q.db() as db:
                    self.assertEqual(dict(db.execute('SELECT id,mode FROM batches')),{'one':'run','two':'pause'})
                    self.assertEqual([r[0] for r in db.execute("SELECT status FROM jobs WHERE batch='one' ORDER BY idx")],['pending','pending','passed'])
                self.q.control('one','pause');post('/api/execution/wake',{})
                with self.q.db() as db:self.assertEqual(db.execute("SELECT mode FROM batches WHERE id='one'").fetchone()[0],'pause')
                with patch.object(server,'ensure_worker',return_value=dict(ready=False,error='PermissionError diagnostic')):
                    with self.assertRaises(HTTPError) as exc:post('/api/execution/control',dict(id='one',action='resume'))
                    self.assertEqual(exc.exception.code,503)
                with self.q.db() as db:self.assertEqual(db.execute("SELECT mode FROM batches WHERE id='one'").fetchone()[0],'pause')
            finally:service.shutdown();service.server_close();th.join(5)

if __name__=='__main__':unittest.main()
