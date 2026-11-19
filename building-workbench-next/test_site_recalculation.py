"""Isolated failed-site recovery, acceptance and per-site pairing regressions."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from foundation import ROOT, digest, read_json, sha, write_json
from execution_inputs import prepare
from execution_queue import Queue
from comparison_results import execution, assemble
from batch_results import build, tables
from site_recalculation import submit, adopt, change_model_step


def fixture(root, size=2, engine=None, weather=None, model=None, frozen_record=None, *, bundle_id=None, fail_last=True, snapshot=None, step=5):
    root=Path(root)
    q=Queue(root)
    bundle_id=bundle_id or 'inputs_'+'1'*32
    base=root/'data/model-inputs'/bundle_id
    base.mkdir(parents=True)
    if engine is None:
        engine=base/'energyplus.exe'
        engine.write_bytes(b'engine fixture')
    if weather is None:
        weather=base/'weather.epw'
        weather.write_bytes(b'weather fixture')
    if model is None:
        model={'Timestep':{'step':{'number_of_timesteps_per_hour':60//step}}}
    record=frozen_record or read_json(ROOT.parent/'examples/drawing26/template/records.json')['global_w00']
    ids=['s'+str(i) for i in range(size)]
    sites={sid:dict(id=sid,name='地点'+str(i),climate='D',eligible=True) for i,sid in enumerate(ids)}
    sites[ids[-1]]['name']='补算验证地点'
    record['factors']['scope']['site_ids']=ids
    record['numerics']['step_minutes']=step
    record['numerics']['engine_files']={str(engine):sha(engine)}
    source=base/'base.epJSON'
    write_json(source,model,root)
    record['factors']['building']['model_snapshot']=snapshot or dict(path=str(source),sha256=sha(source))
    record['factors']['building']['zones']=len(model.get('Zone',{}))
    paths=[weather,*{Path(s['file_name']) for s in model.get('Schedule:File',{}).values()}]
    manifest=dict(id=bundle_id,identity=dict(record=digest(record)),verified_sources=[dict(path=str(p),sha256=sha(p)) for p in paths],
                  engine_files=record['numerics']['engine_files'],cases=[dict(site_id=s,city=sites[s]['name'],mode='controlled',
                  period=record['factors']['scope']['period'],step_minutes=step,weather=str(weather),model_file=source.name,
                  model_sha256=sha(source)) for s in ids])
    write_json(base/'manifest.json',manifest,root)
    write_json(base/'record.json',record,root)
    review=prepare(root,bundle_id)
    batch=q.submit(review['id'],review['plan_sha256'])['id']
    plan=read_json(q.folder/'reviews'/review['id']/'plan.json')
    jobs=[]
    for i,case in enumerate(plan['cases']):
        job=q.claim()
        if fail_last and i==size-1:
            q.finish(job,'failed',error='隔离测试原失败记录')
        else:
            finish_fixture(q,job)
        jobs.append(job)
    catalog=dict(records={record['id']:record},sites=sites,global_bundle=dict(classes=[
        dict(id='D',climate='D',name='D',expected_sites=size)]))
    return q,record,catalog,batch,jobs


def finish_fixture(q,job,status='passed'):
    case=job['case']
    dest=q.root/'runs'/job['attempt'][8:]/'result.json'
    loads=dict(heating_kWh=2.,cooling_kWh=1.,total_kWh=3.)
    data={k:case[k] for k in ('identity','site_id','city','period','step_minutes','mode')}
    write_json(dest,dict(data,status=status,days=2,artifacts={str(q.path.parent/'reviews'/job['plan']['id']/'plan.json'):job['checksum']},
                        pending_warnings=[],loads=loads,monthly=[dict(month=1,**loads)]),q.root)
    q.finish(job,status,str(dest))
    return sha(dest)


class SiteRecalculationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.q,self.record,self.catalog,self.batch,self.jobs=fixture(self.root,34)
        self.attempt=self.jobs[-1]['attempt']

    def submit(self,step=1):
        return submit(self.q,self.batch,33,self.attempt,step)['id']

    def test_queue_shows_live_recovery_and_retries_only_unlinked_sites(self):
        from navigation_cache import queue_state

        def original():
            return next(b for b in queue_state(self.q,self.root)['batches'] if b['id']==self.batch)

        self.assertEqual(original()['jobs'][33]['recalculations'],[])
        child=self.submit()
        def expect_link(status,adopted=False):
            row=original()['jobs'][33]
            self.assertEqual((row['status'],row['attempt']),('failed',self.attempt))
            self.assertEqual(row['recalculations'],[dict(step=1,status=status,adopted=adopted)])

        expect_link('pending')
        job=self.q.claim()
        expect_link('running')
        checksum=finish_fixture(self.q,job)
        expect_link('passed')
        adopt(self.q,self.batch,33,child,checksum)
        expect_link('passed',adopted=True)

        with self.q.db() as db:
            db.execute("UPDATE jobs SET status='interrupted' WHERE batch=? AND idx=0",(self.batch,))
        self.assertEqual(original()['jobs'][0]['recalculations'],[])
        self.q.control(self.batch,'retry')
        self.assertEqual(original()['jobs'][0]['status'],'pending')
        expect_link('passed',adopted=True)

    def test_confirmed_overlay_preserves_originals_and_pairs_per_site(self):
        q=self.q
        def original_jobs():
            with q.db() as db:return [dict(r) for r in db.execute('SELECT * FROM jobs WHERE batch=? ORDER BY idx',(self.batch,))]
        originals=original_jobs()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(lambda _:self.submit(),range(2)))
        self.assertEqual(ids[0],ids[1])
        child=ids[0]
        with self.assertRaises(ValueError):adopt(q,self.batch,33,child,'wrong')
        job=q.claim()
        self.assertEqual((job['batch'],job['idx'],job['case']['step_minutes']),(child,0,1))
        self.assertIsNone(q.claim())
        checksum=finish_fixture(q,job)
        prior=build(self.batch,self.catalog,self.root)
        self.assertEqual(prior['counts']['accepted'],33)
        with self.assertRaises(ValueError):adopt(q,self.batch,33,child,'wrong')
        for _ in range(2):adopt(q,self.batch,33,child,checksum)
        q.control(self.batch,'retry')
        self.assertIsNone(q.claim())
        self.assertEqual(original_jobs(),originals)
        data=build(self.batch,self.catalog,self.root)
        self.assertEqual(data['counts']['accepted'],34)
        self.assertEqual(data['step_label'],'1 min × 1、5 min × 33')
        table,_=tables(data)
        self.assertEqual(table['sites'][-1]['original_failed_attempt'],self.attempt)
        self.assertEqual(table['monthly'][-1]['step_minutes'],1)
        self.assertEqual(sum(r['total_kWh'] for r in table['sites']),102)
        verified=execution(self.record,self.batch,'controlled',self.root)
        other=copy.deepcopy(verified)
        other['cases']['s33']['step_minutes']=5
        relation=dict(metric='total')
        def compare():return assemble(relation,self.record,self.record,other,verified,self.catalog,'controlled')
        comparison=compare()
        self.assertEqual(comparison['paired_sites'],33)
        self.assertIn('参考 5 min，研究 1 min',comparison['sites'][-1]['reason'])
        self.assertIsNone(comparison['sites'][-1]['total_saved_kWh'])
        other['cases']['s33']['step_minutes']=1
        self.assertEqual(compare()['paired_sites'],34)
        self.assertEqual(verified['cases']['s33']['evidence']['original_failure']['attempt'],self.attempt)

    def test_reject_invalid_input_review_and_changed_result(self):
        for i,attempt,step in ((0,self.jobs[0]['attempt'],1),(33,'stale',1),(33,self.attempt,5),(33,self.attempt,True)):
            with self.assertRaises(ValueError):submit(self.q,self.batch,i,attempt,step)
        child=self.submit()
        job=self.q.claim()
        checksum=finish_fixture(self.q,job,'review')
        with self.assertRaises(ValueError):adopt(self.q,self.batch,33,child,checksum)
        self.assertEqual(build(self.batch,self.catalog,self.root)['counts']['accepted'],33)
        second=self.submit(2)
        job=self.q.claim()
        checksum=finish_fixture(self.q,job)
        adopt(self.q,self.batch,33,second,checksum)
        path=self.root/'runs'/job['attempt'][8:]/'result.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ValueError):build(self.batch,self.catalog,self.root)

    def test_same_step_after_failure_keeps_each_attempt(self):
        first=self.submit()
        job=self.q.claim()
        self.q.finish(job,'failed',error='first follow-up failed')
        second=self.submit()
        self.assertNotEqual(first,second)
        self.assertEqual(self.submit(),second)
        job=self.q.claim()
        adopt(self.q,self.batch,33,second,finish_fixture(self.q,job))
        data=build(self.batch,self.catalog,self.root)
        self.assertEqual([r['status'] for r in data['results'][-1]['recalculations']],['failed','passed'])

    def test_feedback_clocks_and_calendar_keep_units(self):
        rec=copy.deepcopy(self.record)
        c=dict(mode='feedback',update=dict(kind='solver_step'))
        rec['factors']['condition']['controls']=[c]
        lines=['SET ECA_W1_Age = ECA_W1_Age + 5','SET NX_G0_ALL_Clock = NX_G0_ALL_Clock + 5','IF NX_G0_ALL_Clock >= 5','IF DayOfYear >= 100']
        model={'Timestep':{'t':{'number_of_timesteps_per_hour':12}},'EnergyManagementSystem:Program':{'ECA_Update':{'lines':[dict(program_line=l) for l in lines]}}}
        change_model_step(model,rec,5,1)
        changed=[r['program_line'] for r in model['EnergyManagementSystem:Program']['ECA_Update']['lines']]
        self.assertEqual(changed,[l[:-1]+'1' for l in lines[:3]]+[lines[3]])
        c.update(reference_step_minutes=5,update=dict(kind='minutes',minutes=5))
        with self.assertRaises(ValueError):change_model_step(model,rec,1,5)

class BeijingStepTests(unittest.TestCase):
    def test_calibrated_case_recovery_retains_step_and_original_failure(self):
        record = read_json(ROOT.parent/'examples/drawing26/template/records.json')['global_w00']
        record['numerics']['heat_transfer_profile'] = 'five_storey_condfd_1min_v1'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, _, catalog, parent, jobs = fixture(root, frozen_record=record, step=1)
            passed, failed = build(parent, catalog, root)['results']
            self.assertEqual(failed['available_steps'], [1])
            self.assertIn('1 分钟', failed['step_note'])
            self.assertEqual(passed['available_steps'], [])
            for step in (2, 5, 10, 15, 30, 60, True, '1'):
                with self.subTest(step=step), self.assertRaises(ValueError):
                    submit(queue, parent, 1, jobs[1]['attempt'], step)
            with self.assertRaises(ValueError):
                submit(queue, parent, 0, jobs[0]['attempt'], 5, 'comparison')
            self.assertIsNone(queue.claim())
            from recent_batch_views import RecentBatches
            cache = RecentBatches(root)
            cache.get(parent, catalog)
            result = submit(queue, parent, 1, jobs[1]['attempt'], 1)
            report = cache.get(parent, catalog)
            self.assertFalse(report['reused'])
            self.assertEqual(report['summary']['results'][1]['recalculations'][0]['status'], 'pending')
            self.assertEqual(submit(queue, parent, 1, jobs[1]['attempt'], 1)['id'], result['id'])
            child = queue.claim()
            self.assertEqual(child['case']['step_minutes'], 1)
            self.assertEqual(child['case']['model_sha256'], jobs[1]['case']['model_sha256'])
            self.assertIsNone(queue.claim())
            checksum = finish_fixture(queue, child)
            self.assertEqual(build(parent, catalog, root)['results'][1]['status'], 'failed')
            adopt(queue, parent, 1, child['batch'], checksum)
            report = cache.get(parent, catalog)
            self.assertFalse(report['reused'])
            rows = report['summary']['results']
            self.assertEqual(rows[0]['evidence']['attempt'], jobs[0]['attempt'])
            self.assertEqual(rows[1]['evidence']['original_failure']['attempt'], jobs[1]['attempt'])
