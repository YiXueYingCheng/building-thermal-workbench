from pathlib import Path
import tempfile
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from execution_queue import Queue
from resource_history import History, Sample
from resources import dispatch_budget, settings


class SingleDispatchTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.q=Queue(Path(temp.name))
        plan={'cases':[{'index':i,'identity':str(i),'mode':'controlled'} for i in range(3)]}
        with patch('execution_queue.load_review',return_value=plan):
            self.a,self.b=[self.q.submit(review,'digest')['id'] for review in ('a','b')]

    def test_single_wins_concurrent_requests_and_is_exclusive_across_batches(self):
        q=self.q
        first=q.claim()
        def request(batch):
            try:q.control_job(batch,1,'force_one');return batch
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners=list(filter(None,pool.map(request,(self.a,self.b))))
        self.assertEqual(len(winners),1)
        selected=q.next_pending()
        self.assertEqual((selected['batch'],selected['idx'],selected['exclusive']),(winners[0],1,True))
        self.assertIsNone(q.claim(selected))
        q.finish(first,'failed',error='fixture')
        forced=q.claim(selected)
        self.assertEqual(forced['manual_start'],'exclusive')
        self.assertIsNone(q.claim())
        q.finish(forced,'failed',error='fixture')
        self.assertIsNotNone(q.claim())

    def test_cancelled_requeues_only_selected_row_and_release_invalidates_old_budget(self):
        q=self.q
        q.control(self.a,'cancel_pending')
        q.control(self.b,'pause')
        q.control_job(self.a,2,'requeue_cancelled')
        with self.assertRaises(ValueError):q.control_job(self.a,2,'requeue_cancelled')
        normal=q.next_pending()
        q.control_job(self.a,2,'force_one')
        self.assertIsNone(q.claim(normal))
        forced=q.next_pending()
        q.control_job(self.a,2,'release_force')
        self.assertIsNone(q.claim(forced))
        job=q.claim()
        self.assertEqual((job['batch'],job['idx']),(self.a,2))
        with q.db() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT status FROM jobs WHERE batch=? ORDER BY idx',(self.a,))],['cancelled','cancelled','running'])
            self.assertEqual(db.execute('SELECT count(*) FROM batches').fetchone()[0],2)
        self.assertIsNone(q.claim())

    def test_interruption_releases_exclusive_permission(self):
        q=self.q
        q.control_job(self.a,0,'force_one')
        q.claim()
        q.recover()
        q.control_job(self.b,1,'force_one')
        self.assertEqual(q.claim()['batch'],self.b)

    def test_historical_physical_and_commit_estimates(self):
        h=History()
        h.add(Sample('annual5','b','a5',1.479,'5min','year5'))
        h.add(Sample('annual1','b','a1',4.108,'1min','year1'))
        key=dict(family='b',timing='1min',workload='jan',configuration='j1')
        estimate=h.estimate(key)
        self.assertEqual((estimate['basis'],estimate['used_samples'],estimate['legacy_peak']),('same_step',1,True))
        h.add(Sample('jan1','b','j1',2.8,'1min','jan',1.4,2.8))
        est=h.estimate(key)
        self.assertEqual(est['basis'],'exact')
        self.assertAlmostEqual(est['reserved_gib'],1.8)
        self.assertAlmostEqual(est['reserved_commit_gib'],3.55)
        self.assertEqual(h.estimate(dict(key,configuration='other'))['basis'],'comparable')

    def test_http_acknowledgement_and_cancelled_job(self):
        from foundation import ROOT,read_json,write_json
        from server import make_server
        root=self.q.root
        write_json(root/'config.json',read_json(ROOT/'config.example.json'),root)
        (root/'VERSION').write_text('isolated',encoding='utf8')
        self.q.control(self.a,'cancel_pending')
        server=make_server(root,0,start_workers=False)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        token=read_json(root/'data/session-token.json')['token']
        def post(action,**params):
            data=json.dumps(dict(id=self.a,index=1,action=action,**params)).encode()
            req=Request(f'http://127.0.0.1:{server.server_port}/api/execution/job-control',data=data,
                        headers={'Content-Type':'application/json','X-Workbench-Token':token})
            with urlopen(req) as response:return json.load(response)
        try:
            post('requeue_cancelled')
            for flags in ({},{'confirmed':True},{'confirmed':True,'risk_acknowledged':'yes'}):
                with self.assertRaises(HTTPError) as err:post('force_one',**flags)
                self.assertEqual(err.exception.code,400)
                self.assertFalse(self.q.next_pending()['exclusive'])
            post('force_one',confirmed=True,risk_acknowledged=True)
            self.assertTrue(self.q.next_pending()['exclusive'])
            post('release_force')
            self.assertFalse(self.q.next_pending()['exclusive'])
        finally:
            server.shutdown();server.server_close();thread.join(5)

    def test_forced_budget_still_requires_real_resources(self):
        p=settings(dict(profile='custom',max_parallel=1,reserve_gib=2))
        m=dict(available_gib=4.83,commit_available_gib=8,disk_free_gib=9)
        self.assertFalse(dispatch_budget(p,m,[],5.19)['allowed'])
        self.assertTrue(dispatch_budget(p,m,[],5.19,exclusive=True)['allowed'])
        for key in ('available_gib','commit_available_gib','disk_free_gib'):
            self.assertFalse(dispatch_budget(p,dict(m,**{key:1}),[],5.19,exclusive=True)['allowed'])
        self.assertFalse(dispatch_budget(p,m,[{}],5.19,exclusive=True)['allowed'])
        self.assertFalse(dispatch_budget(dict(p,max_parallel=4),m,[dict(exclusive=True)])['allowed'])

    def test_worker_dispatches_one_confirmed_case_then_returns_to_ordinary_budget(self):
        import execution_worker as worker
        q=self.q
        q.control_job(self.b,1,'force_one')
        m=dict(available_gib=4.83,commit_available_gib=8,disk_free_gib=30)
        est=dict(reserved_gib=5.19,reserved_commit_gib=5.19,configuration_samples=0,
                 family_samples=2,basis='same_step',observed_family_peak_gib=4.108)
        seen=[]
        def fake_end(job,phase,error):
            seen.append((job['batch'],job['idx'],job['manual_start']))
            q.finish(job,'failed',error='fixture')
        # Exit after observing the next ordinary candidate blocked by the real admission check.
        class StopProbe(Exception):pass
        with patch.object(worker,'ProcessGroup'),patch.object(worker,'engine_pids',side_effect=[[999],[],[],[]]), \
             patch.object(worker.resources,'snapshot',return_value=m),patch.object(worker,'ResourceHistory') as history, \
             patch.object(worker.output_storage,'dispatch_capacity',side_effect=[{'reason':None},{'reason':'disk offline'},{'reason':None},{'reason':None}]), \
             patch.object(worker,'load_review',side_effect=ValueError('fixture')),patch.object(worker,'publish_status'), \
             patch.object(worker,'fail_attempt',side_effect=lambda queue,job,phase,error:fake_end(job,phase,error)), \
             patch.object(worker.time,'sleep',side_effect=[None,None,None,StopProbe]):
            history.return_value.estimate.return_value=est
            with self.assertRaises(StopProbe):worker.run(q.root)
        self.assertEqual(seen,[(self.b,1,'exclusive')])
        self.assertFalse(q.next_pending()['exclusive'])

