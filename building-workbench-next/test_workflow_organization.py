import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from foundation import digest,sha
from component_library import Library
import daily_library as dl
import reference_library as rl
import preparation_status as ps
from research_execution import Runs
import plan_workflow

class DailyFlowTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=rl.daily_profiles()[0]['snapshot']
 def tearDown(self):self.tmp.cleanup()
 def copy(self,name='测试用途',source=None):
  s=source or self.source
  return dl.save(self.root,name,copy.deepcopy(s['content']),copied_from={k:s[k] for k in ('id','revision','sha256')})
 def test_reference_and_room_route_share_snapshot_and_source_chain(self):
  a=dl.copy_reference(self.root,self.source['content']['provenance']['reference_id'],'同一用途')
  b=self.copy('同一用途');self.assertEqual(a['profile'],b['profile']);self.assertTrue(b['reused'])
  self.assertEqual(a['profile']['content']['provenance']['source_provenance'],self.source['content']['provenance'])
  self.assertEqual(len(Library(self.root).all('daily')),1)
 def test_same_values_different_name_or_origin_not_merged(self):
  a=self.copy('用途一');b=self.copy('用途二');self.assertNotEqual(a['profile']['id'],b['profile']['id'])
  c=copy.deepcopy(self.source['content']);c['provenance']={'different_source':'another workbook'}
  other=dl.save(self.root,'另一来源',c)['profile'];d=self.copy('用途一',other)
  self.assertNotEqual(d['profile']['id'],a['profile']['id']);self.assertEqual(d['profile']['content']['provenance']['source_provenance'],c['provenance'])
 def test_same_name_different_curve_not_merged_and_old_version_unchanged(self):
  a=self.copy()['profile'];c=copy.deepcopy(a['content']);c['values'][0]=.123
  b=dl.save(self.root,a['name'],c,parent={k:a[k] for k in ('id','revision','sha256')})['profile']
  self.assertEqual(b['revision'],2);self.assertEqual(dl.find(self.root,a['id'],1)['snapshot'],a)
  with self.assertRaises(ValueError):dl.save(self.root,a['name'],c,parent={'id':a['id'],'revision':1})
 def test_bad_source_fingerprint_rejected(self):
  with self.assertRaises(ValueError):dl.save(self.root,'bad',self.source['content'],copied_from={'id':self.source['id'],'revision':1,'sha256':'wrong'})
  self.assertEqual(Library(self.root).all('daily'),[])
 def test_repeated_concurrent_save_reused_and_hidden_status_preserved(self):
  with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(lambda _:self.copy(),range(3)))
  self.assertEqual(len({r['profile']['id'] for r in rows}),1)
  a=rows[0]['profile'];dl.set_visibility(self.root,a['id'],True,0);self.assertTrue(self.copy()['hidden'])
  self.assertEqual(dl.find(self.root,a['id'],1)['snapshot'],a)

class PreparationLifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);folder=self.root/'data/execution';folder.mkdir(parents=True)
  self.db=sqlite3.connect(folder/'queue.sqlite');self.db.executescript('CREATE TABLE batches(id TEXT,review TEXT,checksum TEXT,mode TEXT,created TEXT,plan TEXT); CREATE TABLE jobs(batch TEXT,idx INT,status TEXT,error TEXT);')
  self.record={'id':'draft_test','revision':3};self.ident='review_'+'a'*32
  self.plan=dict(id=self.ident,record_id=self.record['id'],revision=3,record_sha256=digest(self.record),output_contract='monthly_period_v1',cases=[dict(index=0,site_id='city',identity='physical-and-output-identity')])
  self.path=folder/'reviews'/self.ident/'plan.json';self.path.parent.mkdir(parents=True);self.path.write_text(json.dumps(self.plan),encoding='utf8');self.checksum=sha(self.path)
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def batch(self,name='b1',plan=None,status='passed',checksum=None):
  p=plan or self.plan;self.db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(name,p['id'],checksum or self.checksum,'run','now',json.dumps(p)))
  for i,c in enumerate(p['cases']):self.db.execute('INSERT INTO jobs VALUES(?,?,?,NULL)',(name,i,status))
  self.db.commit()
 def status(self):return ps.Submissions(self.root).review(self.ident,self.checksum)
 def receipt(self):return dict(id='setprep_'+'b'*32,state='prepared',created='now',message='尚未提交',plan=dict(cases=1),cases=[dict(role='fixed',site_id='city',review_id=self.ident,plan_sha256=self.checksum,batch_id=None)])
 def test_unsubmitted_then_exact_submission_tracks_live_status(self):
  self.assertEqual(self.status()['kind'],'unsubmitted');self.batch(status='running');self.assertEqual(self.status()['kind'],'submitted')
  self.db.execute("UPDATE jobs SET status='review'");self.db.commit();s=self.status();self.assertEqual(s['kind'],'finished');self.assertEqual(s['counts'],{'review':1});self.assertNotIn('已接受',s['label'])
 def test_equivalent_review_requires_record_and_output_and_case_identity(self):
  p=copy.deepcopy(self.plan);p['id']='review_'+'c'*32
  for field,value in [('revision',4),('record_sha256','different'),('output_contract','daily_sensible_reference_v1')]:
   changed=dict(p,**{field:value});self.batch(field,changed);self.assertEqual(self.status()['kind'],'unsubmitted')
  changed=copy.deepcopy(p);changed['cases'][0]['identity']='different-input';self.batch('different',changed);self.assertEqual(self.status()['kind'],'unsubmitted')
  self.batch('exact-input',p);self.assertEqual(self.status()['kind'],'finished');self.assertEqual(self.status()['batches'][0]['relation'],'same_saved_input_and_output')
 def test_multiple_batches_retained_and_unknown_not_unsubmitted(self):
  self.batch('done');self.batch('running',status='running');s=self.status();self.assertEqual(len(s['batches']),2);self.assertEqual(s['kind'],'submitted')
  self.path.write_text('{}');self.assertEqual(self.status()['kind'],'unknown')
 def test_partial_coverage_and_unavailable_job_not_complete(self):
  p=copy.deepcopy(self.plan);p['cases'].append(dict(index=1,site_id='other',identity='other'));self.batch()
  s=ps.Submissions(self.root).plan(p,self.checksum);self.assertEqual(s['kind'],'partial')
  self.db.execute('DELETE FROM jobs');self.db.commit();self.assertEqual(self.status()['kind'],'unknown')
 def test_group_projection_is_readonly_and_completed_submit_is_noop(self):
  self.batch();receipt=self.receipt();original=copy.deepcopy(receipt);s=ps.group(self.root,receipt)
  self.assertEqual(receipt,original);self.assertTrue(s['lifecycle']['history']);self.assertFalse(s['can_submit']);self.assertNotIn('prepared',s['counts'])
  folder=self.root/'data/research-set-preparations'/receipt['id'];folder.mkdir(parents=True);path=folder/'state.json';path.write_text(json.dumps(receipt));before=path.read_bytes()
  runs=Runs(self.root,lambda:{},workers=False)
  try:
   with patch('research_execution.Queue',side_effect=AssertionError('must not submit')):self.assertTrue(runs.submit_prepared(receipt['id'])['lifecycle']['finished'])
  finally:runs.close()
  self.assertEqual(path.read_bytes(),before)
 def test_plan_workflow_moves_submitted_preparation_to_history(self):
  self.batch();r=dict(review=self.ident,checksum=self.checksum,bundle_id='inputs_test',bundle_sha256='x',created='now')
  with patch.object(plan_workflow,'registry',return_value=[r]):
   pending,issues,history=plan_workflow.preparations(self.record,{},self.root,include_history=True)
  self.assertFalse(pending);self.assertFalse(issues);self.assertEqual(history[0]['id'],self.ident)
 def test_bad_checksum_never_claims_finished(self):
  self.batch(checksum='wrong');self.assertEqual(self.status()['kind'],'unknown')
 def test_source_history_does_not_show_never_prepared_or_no_batch(self):
  record=dict(self.record,factors={'condition':{'controls':[]},'scope':{'site_ids':['city']}})
  activity=dict(batches=[],inputs=[],comparisons=[],other_versions=[],issues=[])
  with patch.object(plan_workflow.navigation_cache,'activity',return_value=activity),patch.object(plan_workflow,'describe',return_value={'supported':True}),patch.object(plan_workflow,'calculation_recipe',return_value='same'),patch.object(ps,'approved_sources',return_value=[]),patch('research_sets.Sets'),patch.object(plan_workflow,'preparations',return_value=([],[],[{'id':self.ident}])):
   result=plan_workflow.build(record,record,{},None,self.root)
  nodes={n['id']:n for n in result['nodes']}
  self.assertEqual(nodes['budget']['label'],'已有提交记录');self.assertEqual(nodes['results']['label'],'已有关联计算')
 def test_input_job_reads_current_queue_without_rewriting_receipt(self):
  from input_preparation_jobs import Jobs
  job=dict(id='job_test',state='ready',kind='prepare',started_epoch=1,finished_epoch=2,record_id=self.record['id'],revision=3,result=dict(id=self.ident,plan_sha256=self.checksum))
  original=copy.deepcopy(job);jobs=Jobs(self.root,lambda ident,revision:[])
  try:
   self.assertEqual(jobs.public(job)['lifecycle']['kind'],'unsubmitted')
   self.batch();done=jobs.public(job)
   self.assertEqual(done['lifecycle']['kind'],'finished');self.assertEqual(done['result']['existing_batch']['id'],'b1')
   self.path.write_text('{}');self.assertEqual(jobs.public(job)['lifecycle']['kind'],'unknown')
   self.assertEqual(job,original)
  finally:jobs.close()
 def test_explicit_source_binding_requires_current_recipe_and_same_case(self):
  from types import SimpleNamespace
  from research_sets import ref
  source={'id':'source','revision':1};p=dict(self.plan,id='review_'+'d'*32,record_id='source',revision=1,record_sha256=digest(source))
  self.batch('source_batch',p)
  candidate=dict(source=ref(source),recipe='same',batch_id='source_batch',plan_sha256=self.checksum)
  snapshot={'members':{'fixed':dict(record=ref(self.record),results=[candidate])}}
  sets=SimpleNamespace(store=SimpleNamespace(get=lambda ident,revision:source))
  with patch('research_sets.recipe',return_value='same'):
   bindings=ps.approved_sources(sets,self.record,snapshot)
   self.assertEqual(ps.Submissions(self.root).plan(self.plan,self.checksum,bindings=bindings)['kind'],'finished')
   candidate['recipe']='old';self.assertEqual(ps.approved_sources(sets,self.record,snapshot),[])
  self.assertEqual(self.status()['kind'],'unsubmitted')
 def test_source_binding_wrong_checksum_or_output_never_covers(self):
  from research_sets import ref
  source={'id':'source','revision':1};p=dict(self.plan,id='review_'+'e'*32,record_id='source',record_sha256=digest(source),revision=1,output_contract='daily_sensible_reference_v1')
  self.batch('source',p)
  binding=dict(target=ref(self.record),source=ref(source),batch_id='source',plan_sha256=self.checksum)
  self.assertEqual(ps.Submissions(self.root).plan(self.plan,self.checksum,bindings=[binding])['kind'],'unsubmitted')
  p['output_contract']=self.plan['output_contract'];self.db.execute('UPDATE batches SET plan=?',(json.dumps(p),));self.db.commit();binding['plan_sha256']='wrong'
  self.assertEqual(ps.Submissions(self.root).plan(self.plan,self.checksum,bindings=[binding])['kind'],'unsubmitted')

if __name__=='__main__':unittest.main()
