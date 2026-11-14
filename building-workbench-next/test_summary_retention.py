from pathlib import Path
import tempfile,unittest,json,copy
from foundation import sha
from execution_queue import Queue
from execution_results import verify_artifacts
import summary_retention as sr
from result_reading import results

class SummaryRetentionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.batch='batch_'+'a'*32;self.attempt='attempt_'+'b'*32;self.q=Queue(self.root)
  self.folder=self.root/'runs'/self.attempt[8:];(self.folder/'run').mkdir(parents=True)
  self.sql=self.folder/'run/eplusout.sql';self.sql.write_bytes(b'original')
  self.log=self.folder/'run/eplusout.err';self.log.write_bytes(b'preserved')
  self.p=self.folder/'result.json';self.raw=dict(identity='same',status='passed',pending_warnings=[],loads=dict(heating_kWh=12,cooling_kWh=3,total_kWh=15),monthly=[dict(month=1,heating_kWh=12,cooling_kWh=3,total_kWh=15)],artifacts={str(p):sha(p) for p in (self.sql,self.log)})
  self.p.write_text(json.dumps(self.raw),encoding='utf8')
  self.plan=dict(record_name='测试',record_id='test',revision=1,bundle_id='b',conditioned_area_m2=10)
  with self.q.db() as db:
   db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(self.batch,'r',json.dumps(self.plan),'h','pause','now'))
   db.execute('INSERT INTO jobs(batch,idx,status,identity,attempt,result,result_sha256,updated) VALUES(?,?,?,?,?,?,?,?)',(self.batch,0,'passed','same',self.attempt,str(self.p),sha(self.p),'now'))
  with self.q.db() as db:self.job=dict(db.execute('select * from jobs').fetchone())
  self.proof=dict(kind='summary_retention_v1',binding=sr.binding(self.job),state='complete',files=[dict(relative=self.sql.relative_to(self.root).as_posix(),sha256=sha(self.sql),status='removed')])
 def test_controlled_missing_preserves_numbers_and_strict_reader_rejects(self):
  before=results(self.root,self.batch);sr.write(self.root,self.proof);self.sql.unlink();after=results(self.root,self.batch)
  self.assertEqual(before['results'][0]['loads'],after['results'][0]['loads']);self.assertEqual(before['results'][0]['monthly'],after['results'][0]['monthly']);self.assertEqual(after['results'][0]['data_retention']['mode'],'summary_retained')
  with self.assertRaises((OSError,ValueError)):verify_artifacts(self.raw)
  self.assertEqual(json.loads(self.p.read_text()),self.raw)
 def test_accidental_missing_or_changed_never_relaxed(self):
  self.sql.unlink()
  with self.assertRaises(ValueError):results(self.root,self.batch)
  sr.write(self.root,self.proof);self.sql.write_bytes(b'wrong')
  with self.assertRaises(ValueError):results(self.root,self.batch)
 def test_pending_or_other_file_not_authorized(self):
  self.proof['files'][0]['status']='pending';sr.write(self.root,self.proof);self.sql.unlink()
  with self.assertRaises(ValueError):results(self.root,self.batch)
  self.proof['files'][0]['status']='removed';sr.write(self.root,self.proof);self.log.unlink()
  with self.assertRaises(ValueError):results(self.root,self.batch)
 def test_tampered_proof_binding_and_path_rejected(self):
  self.sql.unlink()
  for patch in ('identity','path'):
   p=copy.deepcopy(self.proof)
   if patch=='identity':p['binding']['identity']='other'
   else:p['files'][0]['relative']='config.json'
   sr.write(self.root,p)
   with self.assertRaises(ValueError):results(self.root,self.batch)
 def test_missing_summary_or_evidence_blocks(self):
  sr.write(self.root,self.proof);self.sql.unlink();self.p.write_text('{}')
  with self.assertRaises(ValueError):results(self.root,self.batch)
 def test_export_notice_has_no_original_file_claim(self):
  sr.write(self.root,self.proof);self.sql.unlink();data=results(self.root,self.batch);folder=self.root/'export';folder.mkdir();sr.export_notice(folder,data)
  self.assertTrue((folder/'summary-retention.json').is_file());self.assertIn('不能还原已删明细',(folder/'保留汇总说明.txt').read_text('utf-8-sig'))
if __name__=='__main__':unittest.main()
