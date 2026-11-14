from pathlib import Path
from unittest.mock import patch
import unittest,tempfile,json
from foundation import sha
from execution_queue import Queue
import result_availability as ra

class ResultAvailabilityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.q=Queue(self.root);self.batch='batch_'+'a'*32
  self.folder=self.root/'runs'/('b'*32);self.folder.mkdir(parents=True);self.sql=self.folder/'eplusout.sql';self.sql.write_bytes(b'original data')
  self.summary=self.folder/'result.json';self.raw=dict(identity='same',status='passed',loads={'total_kWh':12},artifacts={str(self.sql):sha(self.sql)})
  with self.q.db() as db:
   db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(self.batch,'review','{}','hash','pause','now'))
   db.execute('INSERT INTO jobs(batch,idx,status,identity,attempt,updated) VALUES(?,?,?,?,?,?)',(self.batch,0,'passed','same','attempt_'+'b'*32,'now'))
  self.save()
 def save(self):
  self.summary.write_text(json.dumps(self.raw),encoding='utf8')
  with self.q.db() as db:db.execute('UPDATE jobs SET result=?,result_sha256=?',(str(self.summary),sha(self.summary)))
 def check(self,**kw):return ra.inspect(self.root,self.batch,0,**kw)
 def test_complete_read_only_and_impact_not_executable(self):
  before={p:sha(p) for p in (self.summary,self.sql,self.q.path)};r=self.check()
  self.assertTrue(r['summary_verified'] and r['artifacts_verified']);self.assertFalse(r['retention']['executable']);self.assertIsNone(r['capabilities'][-1]['ready']);self.assertEqual(before,{p:sha(p) for p in before})
 def test_missing_detail_preserves_summary_not_function_availability(self):
  self.sql.unlink();r=self.check();self.assertEqual(r['state'],'summary_only');self.assertEqual(r['files'][0]['status'],'missing');self.assertEqual(r['summary']['loads']['total_kWh'],12);self.assertFalse(r['capabilities'][1]['ready'])
 def test_changed_detail_not_missing(self):
  self.sql.write_bytes(b'changed');r=self.check();self.assertEqual(r['files'][0]['status'],'changed');self.assertTrue(r['summary_verified']);self.assertFalse(r['artifacts_verified'])
 def test_bad_summary_no_numbers(self):
  self.summary.write_text('{}');r=self.check();self.assertIsNone(r['summary']);self.assertFalse(r['summary_verified'])
 def test_identity_and_status_mismatch(self):
  for key,value in [('identity','different'),('status','review')]:
   old=self.raw[key];self.raw[key]=value;self.save();self.assertFalse(self.check()['summary_verified']);self.raw[key]=old
 def test_offline_unknown_not_missing(self):
  with patch.object(ra,'path_checked',side_effect=OSError('external drive offline')):r=self.check()
  self.assertEqual(r['summary_file']['status'],'unknown');self.assertIsNone(r['summary'])
 def test_timeout_and_unsafe_path(self):
  self.assertEqual(self.check(budget_seconds=-1)['summary_file']['status'],'unknown')
  self.raw['artifacts']={'relative/eplusout.sql':'a'*64};self.save();r=self.check();self.assertEqual(r['files'][0]['status'],'unknown')
 def test_review_summary_not_accepted(self):
  self.raw['status']='review';self.save()
  with self.q.db() as db:db.execute("UPDATE jobs SET status='review'")
  r=self.check();self.assertTrue(r['artifacts_verified']);self.assertFalse(r['capabilities'][1]['ready'])
 def test_listing_does_not_read_artifacts_and_unknown_case_rejected(self):
  with patch.object(ra,'check_file',side_effect=AssertionError('should not hash')):self.assertEqual(len(ra.listing(self.root,self.batch)['cases']),1)
  with self.assertRaises(ValueError):ra.inspect(self.root,self.batch,10)
  with self.assertRaises(ValueError):ra.listing(self.root,'../escape')
 def test_registration_changed_during_check(self):
  original=ra.jobs;calls=[]
  def changing(*args):
   rows=original(*args);calls.append(1)
   if len(calls)>1:rows[0]['updated']='later'
   return rows
  with patch.object(ra,'jobs',side_effect=changing):r=self.check()
  self.assertFalse(r['summary_verified']);self.assertIsNone(r['summary'])
 def test_no_registered_result(self):
  with self.q.db() as db:db.execute("UPDATE jobs SET result=NULL,status='pending'")
  self.assertFalse(self.check()['summary_verified'])

if __name__=='__main__':unittest.main()
