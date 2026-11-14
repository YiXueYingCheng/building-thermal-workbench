from pathlib import Path
from unittest.mock import patch
import unittest,json,os
import test_summary_retention as fixture
import retention_cleanup as rc
import summary_retention as sr
from foundation import sha,digest,write_json
from result_reading import results

class RetentionCleanupTests(unittest.TestCase):
 def setUp(self):
  f=fixture.SummaryRetentionTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.root=f.root
 def preview(self):return rc.preview(self.root,self.f.attempt)
 def execute(self,p):return rc.execute(self.root,p['id'],p['sha256'],True)
 def test_preview_confirm_idempotent_and_summary_preserved(self):
  f=self.f;before={p:sha(p) for p in (f.p,f.log,f.q.path)};p=self.preview();self.assertFalse(p['blocked'],p['blocked']);self.assertTrue(f.sql.exists())
  with self.assertRaises(ValueError):rc.execute(self.root,p['id'],p['sha256'],False)
  r=self.execute(p);self.assertEqual(r['removed'],1);self.assertEqual(r,self.execute(p));self.assertFalse(f.sql.exists());self.assertEqual(before,{p:sha(p) for p in before});self.assertTrue(results(self.root,f.batch)['results'][0]['data_retention'])
 def test_new_calendar_or_verification_reference_blocks(self):
  for path in ('data/calendar/linked.json','verification/scientific-review/linked.json'):
   p=self.preview();doc=self.root/path;write_json(doc,{'source':str(self.f.sql)},self.root)
   with self.assertRaises(ValueError):self.execute(p)
   self.assertTrue(self.f.sql.exists());doc.unlink()
 def test_comparison_and_export_references_allow_summary_path(self):
  for path in ('data/comparison-exports/comparison_export_'+32*'c'+'/dataset.json','data/research-set-exports/set_export_'+32*'d'+'/dataset.json'):write_json(self.root/path,{'source':str(self.f.sql)},self.root)
  self.assertFalse(self.preview()['blocked'])
 def test_active_or_changed_file_blocks(self):
  p=self.preview()
  with self.assertRaises(ValueError):rc.execute(self.root,p['id'],p['sha256'],True,True)
  self.f.sql.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.execute(p)
 def test_shared_and_unregistered_missing_block(self):
  other=self.root/'shared';os.link(self.f.sql,other);self.assertTrue(self.preview()['blocked']);other.unlink();self.f.sql.unlink();self.assertTrue(self.preview()['blocked'])
 def test_review_and_daily_contract_protected(self):
  for field,value in [('scientific_review',{'not':'a-valid-acceptance'}),('daily_reference',{'days':365})]:
   raw=dict(self.f.raw,**{field:value});self.f.p.write_text(json.dumps(raw))
   with self.f.q.db() as db:db.execute('UPDATE jobs SET result_sha256=?',(sha(self.f.p),))
   self.assertTrue(self.preview()['blocked'])
 def test_partial_failure_then_new_preview_preserves_old_removal(self):
  csv=self.f.sql.with_suffix('.csv');csv.write_bytes(b'extra');p=self.preview();unlink=Path.unlink
  def fail(path,*args,**kw):
   if path==csv:raise PermissionError('busy')
   return unlink(path,*args,**kw)
  with patch.object(Path,'unlink',fail):r=self.execute(p)
  self.assertEqual((r['removed'],r['retained']),(1,1));self.assertTrue(results(self.root,self.f.batch)['results'][0]['data_retention'])
  p=self.preview();self.assertFalse(p['blocked'],p['blocked']);self.execute(p);self.assertFalse(csv.exists());self.assertTrue(results(self.root,self.f.batch)['results'][0]['data_retention'])
 def test_forged_candidate_or_expired_preview_cannot_delete(self):
  p=self.preview()
  with patch.object(rc.time,'time',return_value=p['expires_epoch']+1):
   with self.assertRaises(ValueError):self.execute(p)
  path=self.root/'data/storage-management/previews'/(p['id']+'.json');v=json.loads(path.read_text());v['files'][0]['relative']=self.f.log.relative_to(self.root).as_posix();write_json(path,v,self.root)
  with self.assertRaises(ValueError):rc.execute(self.root,p['id'],digest(v),True)
  self.assertTrue(self.f.sql.exists() and self.f.log.exists())
 def test_interrupted_confirmation_never_implies_success(self):
  p=self.preview();original=sr.write;count=[]
  def stop(root,payload):
   count.append(1)
   if len(count)==2:raise OSError('simulated crash after unlink')
   original(root,payload)
  with patch.object(sr,'write',side_effect=stop):
   with self.assertRaises(OSError):self.execute(p)
  with self.assertRaises(ValueError):results(self.root,self.f.batch)
  self.assertFalse(self.f.sql.exists())

if __name__=='__main__':unittest.main()
